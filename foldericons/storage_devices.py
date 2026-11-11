"""Discover portable storage without formatting, mounting, or modifying devices.

The host integration supplies lsblk's JSON and /proc/self/mountinfo. Device
identity comes from filesystem UUIDs rather than changing /dev/sdX names.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath


def mount_unescape(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), value)


def parse_mountinfo(text: str) -> list[dict]:
    result = []
    for line in text.splitlines():
        before, separator, after = line.partition(" - ")
        left, right = before.split(), after.split()
        if not separator or len(left) < 6 or len(right) < 3:
            continue
        result.append({"device": left[2], "root": mount_unescape(left[3]),
                       "path": mount_unescape(left[4]), "options": left[5].split(","),
                       "filesystem": right[0], "source": mount_unescape(right[1])})
    return result


def device_id(identity: str) -> str:
    return "device-" + hashlib.sha256(identity.encode()).hexdigest()[:20]


def clean_label(value: object, fallback: str) -> str:
    label = re.sub(r"[\x00-\x1f\x7f/\\]", " ", str(value or ""))
    return " ".join(label.split())[:100] or fallback


def portable_devices(blocks: dict, mountinfo: str, known_roots=()) -> list[dict]:
    """Return connected USB/SD volumes and already-mounted phone storage.

    Internal disks, boot partitions, swap, encryption containers, duplicate
    bind mounts, and the application's own mirror mount are not drive entries.
    Unknown/unmounted volumes remain status-only until the OS mounts them.
    """
    mounts = parse_mountinfo(mountinfo)
    known = {str(PurePosixPath(p)) for p in known_roots}
    result = {}
    mounted_uuids = {}
    allowed_roots = ("/media/", "/mnt/", "/run/media/")

    def visit(node, parent=None, auxiliary=False):
        parent = parent or {}
        transport = str(node.get("tran") or parent.get("tran") or "").lower()
        removable = bool(node.get("rm") or parent.get("rm"))
        hotplug = bool(node.get("hotplug") or parent.get("hotplug"))
        model = str(node.get("model") or parent.get("model") or "").strip()
        serial = str(node.get("serial") or parent.get("serial") or "").strip()
        inherited = {"tran": transport, "rm": removable, "hotplug": hotplug,
                     "model": model, "serial": serial}
        filesystem = str(node.get("fstype") or "").lower()
        kind = str(node.get("type") or "")
        portable = transport == "usb" or removable or transport == "mmc"
        encrypted = filesystem in {"bitlocker", "crypto_luks"}
        if portable and not auxiliary and filesystem and filesystem not in {"swap", "lvm2_member", "linux_raid_member"} and not (encrypted and node.get('children')) and kind in {"disk", "part", "crypt"}:
            major_minor = str(node.get("maj:min") or "")
            system_volume = any(m["device"] == major_minor and
                                (m["path"] in {"/", "/boot", "/boot/efi", "/DATA"} or m["path"].startswith("/var/lib/docker"))
                                for m in mounts)
            candidates = [m for m in mounts if m["device"] == major_minor and m["root"] == "/"
                          and m["path"].startswith(allowed_roots)
                          and not m["path"].startswith("/media/FilePoint-Devices/")]
            if not system_volume and not any(m["path"] in known for m in candidates):
                mount = min(candidates, key=lambda m: (len(m["path"]), m["path"]), default=None)
                uuid = str(node.get("uuid") or "")
                identity = "block:" + (uuid or serial + ":" + str(node.get("partuuid") or major_minor))
                key = device_id(identity)
                # Cloned UUIDs must never silently merge two physical drives.
                if key in result and mounted_uuids.get(key) != major_minor:
                    key = device_id(identity + ":" + serial + ":" + major_minor)
                mounted_uuids[key] = major_minor
                device_kind = "sd" if transport == "mmc" else "usb"
                result[key] = {"id": key, "label": clean_label(node.get("label") or model, "SD card" if device_kind == "sd" else "USB drive"),
                               "kind": device_kind, "icon": "sd_card" if device_kind == "sd" else "usb",
                               "filesystem": filesystem, "readOnly": bool(node.get("ro")) or bool(mount and "ro" in mount["options"]),
                               "mountPath": mount["path"] if mount else None,
                               "status": "ready" if mount else "locked" if encrypted else "waiting-for-mount",
                               "size": int(node.get("size") or 0)}
                if encrypted and not mount:
                    result[key]['icon'] = 'lock'
        children = node.get("children") or []
        has_data_partition = any(int(c.get('size') or 0) > 128 * 1024 ** 2 for c in children)
        for child in children:
            parttype = str(child.get('parttype') or '').lower()
            auxiliary = parttype in {'c12a7328-f81f-11d2-ba4b-00a0c93ec93b','e3c9e316-0b5c-4db8-817d-f92df00215ae'}
            auxiliary = auxiliary or (has_data_partition and str(child.get('fstype') or '').lower() in {'vfat','fat','fat16','fat32'} and int(child.get('size') or 0) <= 128 * 1024 ** 2)
            visit(child, inherited, auxiliary)

    for block in blocks.get("blockdevices") or []:
        visit(block)
    phone_devices = set()
    for mount in mounts:
        # Only canonical direct phone mounts, never propagated aliases or mirrors.
        if str(PurePosixPath(mount["path"]).parent) != "/media/FilePoint-Phones":
            continue
        fs = mount["filesystem"].lower()
        if fs not in {"fuse.jmtpfs", "fuse.simple-mtpfs", "fuse.go-mtpfs", "fuse.ifuse"}:
            continue
        if mount["path"] in known or mount["path"].startswith("/media/FilePoint-Devices/"):
            continue
        if mount['device'] in phone_devices:
            continue
        phone_devices.add(mount['device'])
        key = device_id("phone:" + mount["source"] + ":" + mount["path"])
        label = re.sub(r' [0-9a-f]{8}$', '', PurePosixPath(mount['path']).name).replace('_', ' ')
        result[key] = {"id": key, "label": clean_label(label, "iPhone" if fs == "fuse.ifuse" else "Phone"),
                       "kind": "phone", "icon": "smartphone", "filesystem": fs,
                       "readOnly": "ro" in mount["options"], "mountPath": mount["path"], "status": "ready", "size": 0}
    return sorted(result.values(), key=lambda d: (d["label"].casefold(), d["id"]))
