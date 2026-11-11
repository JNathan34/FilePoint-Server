#!/usr/bin/env python3
"""Authenticated folder.ico support and a transparent FileBrowser proxy."""

from __future__ import annotations

import base64
import configparser
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
import gzip
import errno
import fnmatch
import functools
import os
import re
import select
import secrets
import shlex
import shutil
import socket
import socketserver
import stat
import struct
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from native_writes import MAX_CHUNK, NativeWrites, WriteError

try:
    from samba.dcerpc import xattr as samba_xattr
    from samba.ndr import ndr_pack, ndr_unpack
except ImportError:  # Samba's Python bindings are provided by the ZimaOS host.
    samba_xattr = None
    ndr_pack = None
    ndr_unpack = None

try:
    import fcntl
except ImportError:  # Only used for native FAT/exFAT attributes on Linux.
    fcntl = None


LISTEN_HOST = os.environ.get("FOLDERICONS_LISTEN_HOST", "192.168.0.151")
LISTEN_PORT = int(os.environ.get("FOLDERICONS_LISTEN_PORT", "8704"))
UPSTREAM_HOST = os.environ.get("FOLDERICONS_UPSTREAM_HOST", "192.168.0.151")
UPSTREAM_PORT = int(os.environ.get("FOLDERICONS_UPSTREAM_PORT", "8701"))
DATA_DIR = Path(os.environ.get("FOLDERICONS_DATA_DIR", "/DATA/AppData/plexpoint-files-office"))
CLIENT_JS = DATA_DIR / "foldericons" / "client.js"
RECYCLE_ICON_FILES = {
    "empty": DATA_DIR / "foldericons" / "assets" / "recycle-bin-empty.png",
    "full": DATA_DIR / "foldericons" / "assets" / "recycle-bin-full.png",
}
CRITICAL_CANVAS_STYLE = b"""<style id="plexpoint-critical-canvas">
html,body,body>#app,#app,#main{background:#1b242b!important;background-color:#1b242b!important;color-scheme:dark}
#main>.loading-spinner,#main>[class*="loading-spinner"],#main .listing-view-root>h2.message.delayed,#main .listing-view-root>.message.delayed,#main .listing-view-root>.loading-spinner,#main .listing-view-root>[class*="loading-spinner"]{display:none!important}
</style>"""
STORAGE_MAP = DATA_DIR / "storage-map.json"
NATIVE_WRITE_CONFIG = DATA_DIR / "native-write-sources.json"
native_writes = NativeWrites()
CONNECTED_STORAGE = DATA_DIR / "connected-storage.json"
DEVICE_ICON_KINDS = frozenset({"usb", "video", "printer", "lock", "phone", "device", "computer", "camera"})
HOME_LAYOUT_DIR = DATA_DIR / "home-layout"
HIDDEN_ITEMS_DIR = DATA_DIR / "hidden-items"
FOLDER_ICONS_DIR = DATA_DIR / "folder-material-icons"
OPERATION_HISTORY_DIR = DATA_DIR / "operation-history"
MATERIAL_ICONS_FILE = DATA_DIR / "foldericons" / "material-icons.json"
MICROSOFT_CONFIG_FILE = DATA_DIR / "microsoft-bridge.json"
MICROSOFT_RCLONE_CONFIG_FILE = DATA_DIR / "microsoft-rclone.conf"
MICROSOFT_RCLONE_REMOTE = os.environ.get("FOLDERICONS_MICROSOFT_RCLONE_REMOTE", "plexpoint-onedrive")
MICROSOFT_DATA_DIR = DATA_DIR / "microsoft-bridge"
HOME_FOLDER_NAMES = frozenset({"Backup", "Documents", "Downloads", "Gallery", "Media"})
MAX_ICON_BYTES = 8 * 1024 * 1024
MAX_LAYOUT_BYTES = 64 * 1024
MAX_HIDDEN_BYTES = 1024 * 1024
MAX_OPERATION_HISTORY_BYTES = 4 * 1024 * 1024
MAX_OPERATION_HISTORY_ITEMS = 100
RECYCLE_DIRECTORY_NAME = ".plexpoint-recycle-bin"
HISTORY_DIRECTORY_NAME = ".plexpoint-history"
AUTH_TTL_SECONDS = 5.0
MANIFEST_TTL_SECONDS = 3.0
INFO_CACHE_SECONDS = 60.0
SEARCH_CACHE_SECONDS = 30.0
SEARCH_MAX_RESULTS = 500
SEARCH_MAX_SCANNED = 100_000
SEARCH_MAX_SECONDS = 12.0
MICROSOFT_SCOPES = "offline_access Files.ReadWrite.AppFolder"
MICROSOFT_RCLONE_CLIENT_ID = "b15665d9-eda6-4092-8539-0eec376afd59"
MICROSOFT_RCLONE_ENCRYPTED_CLIENT_SECRET = "_JUdzh3LnKNqSPcf4Wu5fgMFIQOI8glZu_akYgR8yf6egowNBg-R"
MICROSOFT_RCLONE_OBSCURE_KEY = bytes((
    0x9C, 0x93, 0x5B, 0x48, 0x73, 0x0A, 0x55, 0x4D,
    0x6B, 0xFD, 0x7C, 0x63, 0xC8, 0x86, 0xA9, 0x2B,
    0xD3, 0x90, 0x19, 0x8E, 0xB8, 0x12, 0x8A, 0xFB,
    0xF4, 0xDE, 0x16, 0x2B, 0x8B, 0x95, 0xF6, 0x38,
))
MICROSOFT_MAX_FILE_BYTES = 100 * 1024 * 1024
MICROSOFT_MAX_TOTAL_BYTES = 250 * 1024 * 1024
MICROSOFT_JSON_LIMIT = 4 * 1024 * 1024
MICROSOFT_OFFICE_APPS = {
    ".docx": "Word", ".odt": "Word",
    ".xlsx": "Excel", ".xlsb": "Excel", ".xlsm": "Excel", ".ods": "Excel",
    ".pptx": "PowerPoint", ".ppsx": "PowerPoint", ".odp": "PowerPoint",
}
MICROSOFT_OFFICE_EXTENSIONS = frozenset(MICROSOFT_OFFICE_APPS)
MICROSOFT_DESKTOP_EXTENSIONS = frozenset({".docx", ".xlsx", ".xlsm", ".xlsb", ".pptx"})
MICROSOFT_CONVERSION_EXTENSIONS = {
    ".doc": ".docx", ".dot": ".docx", ".dotx": ".docx", ".docm": ".docx", ".dotm": ".docx", ".rtf": ".docx",
    ".xls": ".xlsx", ".csv": ".xlsx", ".xlt": ".xlsx", ".xltx": ".xlsx",
    ".ppt": ".pptx", ".pps": ".pptx", ".pot": ".pptx", ".potx": ".pptx", ".pptm": ".pptx", ".ppsm": ".pptx", ".potm": ".pptx",
}
DOS_ATTRIBUTE_NAME = "user.DOSATTRIB"
NTFS_ATTRIBUTE_NAME = "system.ntfs_attrib"
NTFS_ATTRIBUTE_BIG_ENDIAN_NAME = "system.ntfs_attrib_be"
DOS_ATTRIBUTE_HIDDEN = 0x02
DOS_ATTRIBUTE_DIRECTORY = 0x10
DOS_ATTRIBUTE_ARCHIVE = 0x20
FAT_IOCTL_GET_ATTRIBUTES = 0x80047210
FAT_IOCTL_SET_ATTRIBUTES = 0x40047211

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

_cache_lock = threading.Lock()
_hidden_lock = threading.Lock()
_folder_icons_lock = threading.Lock()
_operation_lock = threading.RLock()
_microsoft_lock = threading.Lock()
_microsoft_operation_lock = threading.RLock()
_auth_cache: dict[str, tuple[float, dict[str, str], str]] = {}
_manifest_cache: dict[tuple[str, str, str, int], tuple[float, bytes]] = {}
_storage_cache: tuple[int, dict[str, Path]] | None = None
_info_jobs: dict[tuple[str, str], dict[str, object]] = {}
_search_jobs: dict[tuple[str, str, str, str, bool, bool], dict[str, object]] = {}
_microsoft_pending: dict[str, dict[str, object]] = {}


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

def native_upload_cleanup(stop: threading.Event) -> None:
    while not stop.wait(60):
        native_writes.expire()


def safe_components(value: str) -> tuple[str, ...] | None:
    if "\x00" in value or "\\" in value or value.startswith("/"):
        return None
    if value == "":
        return ()
    parts = tuple(value.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        return None
    return parts


def scope_allows(scope: str, requested: tuple[str, ...]) -> bool:
    scope_parts = tuple(part for part in PurePosixPath(scope or "/").parts if part != "/")
    return requested[: len(scope_parts)] == scope_parts


def connected_devices(scopes: dict[str, str]) -> list[dict]:
    if "Home" not in scopes:
        return []
    try:
        state = json.loads(CONNECTED_STORAGE.read_text(encoding="utf-8"))
        fresh = 0 <= time.time() - float(state.get("updatedAt", 0)) < 20
        result = []
        for device in state.get("devices", [])[:64]:
            parts = safe_components(str(device.get("path", "")))
            if not parts or len(parts) != 2 or parts[0] != "Connected devices" or not scope_allows(scopes["Home"], parts):
                continue
            item = {key:device[key] for key in ("id", "label", "name", "kind", "icon", "path", "source", "status", "readOnly", "total", "free", "size") if key in device}
            if not fresh:
                item["status"] = "unavailable"
            kind = 'lock' if item.get('status') == 'locked' else str(item.get('kind','device'))
            if kind not in DEVICE_ICON_KINDS:
                kind = 'device'
            item['iconUrl'] = '/__foldericons/device-icon?kind=' + kind
            result.append(item)
        return result
    except (OSError, ValueError, TypeError):
        return []


def load_storage_map() -> tuple[int, dict[str, Path]]:
    global _storage_cache
    stamp = STORAGE_MAP.stat().st_mtime_ns
    with _cache_lock:
        if _storage_cache is not None and _storage_cache[0] == stamp:
            return _storage_cache
    raw = json.loads(STORAGE_MAP.read_text(encoding="utf-8"))
    mapping = {str(name): Path(str(path)).resolve() for name, path in raw.items()}
    result = (stamp, mapping)
    with _cache_lock:
        _storage_cache = result
    return result


def resolve_location(
    source: str, relative: str, scopes: dict[str, str]
) -> tuple[Path, tuple[str, ...], tuple[str, ...], int] | None:
    parts = safe_components(relative)
    if parts is None or source not in scopes:
        return None
    if not scope_allows(scopes[source], parts):
        return None
    stamp, mapping = load_storage_map()
    if source == "Home":
        if not parts or parts[0] not in mapping:
            return None
        root = mapping[parts[0]]
        within_root = parts[1:]
    else:
        root = mapping.get(source)
        within_root = parts
        if root is None:
            return None
    return root, within_root, parts, stamp


def open_directory(root: Path, components: tuple[str, ...]) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    current = os.open(root, flags)
    try:
        for component in components:
            following = os.open(component, flags, dir_fd=current)
            os.close(current)
            current = following
        return current
    except BaseException:
        os.close(current)
        raise


def detect_image_type(header: bytes) -> str | None:
    if len(header) >= 6 and header[:4] == b"\x00\x00\x01\x00":
        count = int.from_bytes(header[4:6], "little")
        return "image/x-icon" if 1 <= count <= 256 else None
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"BM"):
        return "image/bmp"
    return None


def open_valid_icon(directory_fd: int) -> tuple[int, os.stat_result, str] | None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    icon_fd: int | None = None
    try:
        icon_fd = os.open("folder.ico", flags, dir_fd=directory_fd)
        info = os.fstat(icon_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size < 22 or info.st_size > MAX_ICON_BYTES:
            os.close(icon_fd)
            return None
        header = os.read(icon_fd, 16)
        content_type = detect_image_type(header)
        if content_type is None:
            os.close(icon_fd)
            return None
        os.lseek(icon_fd, 0, os.SEEK_SET)
        return icon_fd, info, content_type
    except (OSError, ValueError):
        if icon_fd is not None:
            os.close(icon_fd)
        return None


def icon_version(info: os.stat_result) -> str:
    return f"{info.st_ino:x}-{info.st_size:x}-{info.st_mtime_ns:x}"


def normalize_order(value: object, allowed: set[str] | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value[:256]:
        if (
            not isinstance(item, str)
            or not item
            or len(item) > 4096
            or (allowed is not None and item not in allowed)
            or item in seen
        ):
            continue
        seen.add(item)
        result.append(item)
    return result


def user_data_path(directory: Path, username: str) -> Path:
    identity = hashlib.sha256(username.encode("utf-8")).hexdigest()
    return directory / f"{identity}.json"


def load_hidden_items(username: str) -> set[str]:
    path = user_data_path(HIDDEN_ITEMS_DIR, username)
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_HIDDEN_BYTES:
            return set()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return set()
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str) and 0 < len(item) <= 4096}


def save_hidden_items(username: str, items: set[str]) -> None:
    HIDDEN_ITEMS_DIR.mkdir(parents=True, exist_ok=True, mode=0o750)
    path = user_data_path(HIDDEN_ITEMS_DIR, username)
    identity = path.stem
    temporary = HIDDEN_ITEMS_DIR / f".{identity}.{os.getpid()}.{threading.get_ident()}.tmp"
    temporary.write_bytes(json_bytes(sorted(items)))
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def load_folder_icons(username: str) -> dict[str, str]:
    path = user_data_path(FOLDER_ICONS_DIR, username)
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_HIDDEN_BYTES:
            return {}
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        key: icon
        for key, icon in value.items()
        if isinstance(key, str)
        and isinstance(icon, str)
        and 0 < len(key) <= 4096
        and re.fullmatch(r"[a-z0-9_]{1,128}", icon)
    }


def save_folder_icons(username: str, icons: dict[str, str]) -> None:
    FOLDER_ICONS_DIR.mkdir(parents=True, exist_ok=True, mode=0o750)
    path = user_data_path(FOLDER_ICONS_DIR, username)
    identity = path.stem
    temporary = FOLDER_ICONS_DIR / f".{identity}.{os.getpid()}.{threading.get_ident()}.tmp"
    temporary.write_bytes(json_bytes(dict(sorted(icons.items()))))
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def canonical_location(source: str, requested_parts: tuple[str, ...], within_root: tuple[str, ...]) -> str | None:
    if source == "Home":
        if not requested_parts:
            return None
        storage_name = requested_parts[0]
    else:
        storage_name = source
    return "/".join((storage_name, *within_root))


def stat_location(root: Path, components: tuple[str, ...]) -> os.stat_result:
    if not components:
        return os.stat(root, follow_symlinks=False)
    parent_fd = open_directory(root, components[:-1])
    try:
        return os.stat(components[-1], dir_fd=parent_fd, follow_symlinks=False)
    finally:
        os.close(parent_fd)


def open_location(root: Path, components: tuple[str, ...]) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    if not components:
        return os.open(root, flags)
    parent_fd = open_directory(root, components[:-1])
    try:
        return os.open(components[-1], flags, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def operation_owner_id(username: str) -> str:
    return hashlib.sha256(username.encode("utf-8")).hexdigest()


def operation_history_path(username: str) -> Path:
    return OPERATION_HISTORY_DIR / f"{operation_owner_id(username)}.json"


def load_operation_history(username: str) -> dict[str, list[dict[str, object]]]:
    path = operation_history_path(username)
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_OPERATION_HISTORY_BYTES:
            raise ValueError("operation history is too large")
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return {"undo": [], "redo": []}

    def valid_stack(name: str) -> list[dict[str, object]]:
        stack = value.get(name, []) if isinstance(value, dict) else []
        if not isinstance(stack, list):
            return []
        return [item for item in stack[-MAX_OPERATION_HISTORY_ITEMS:] if isinstance(item, dict)]

    return {"undo": valid_stack("undo"), "redo": valid_stack("redo")}


def save_operation_history(username: str, value: dict[str, list[dict[str, object]]]) -> None:
    OPERATION_HISTORY_DIR.mkdir(parents=True, exist_ok=True, mode=0o750)
    path = operation_history_path(username)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    payload = {
        "undo": list(value.get("undo", []))[-MAX_OPERATION_HISTORY_ITEMS:],
        "redo": list(value.get("redo", []))[-MAX_OPERATION_HISTORY_ITEMS:],
    }
    temporary.write_bytes(json_bytes(payload))
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def history_summary(value: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    undo = value.get("undo", [])
    redo = value.get("redo", [])
    return {
        "canUndo": bool(undo),
        "canRedo": bool(redo),
        "undoLabel": str(undo[-1].get("label", "")) if undo else "",
        "redoLabel": str(redo[-1].get("label", "")) if redo else "",
        "undoCount": len(undo),
        "redoCount": len(redo),
    }


def record_operation(username: str, record: dict[str, object]) -> dict[str, object]:
    stored = dict(record)
    stored.setdefault("id", secrets.token_hex(12))
    stored.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    with _operation_lock:
        value = load_operation_history(username)
        discarded = list(value["redo"])
        value["undo"].append(stored)
        discarded.extend(value["undo"][:-MAX_OPERATION_HISTORY_ITEMS])
        value["undo"] = value["undo"][-MAX_OPERATION_HISTORY_ITEMS:]
        value["redo"] = []
        save_operation_history(username, value)
        for old_record in discarded:
            discard_operation_artifacts(username, old_record)
        return history_summary(value)


def remove_recycle_items_from_history(username: str, identifiers: set[str]) -> None:
    if not identifiers:
        return
    with _operation_lock:
        value = load_operation_history(username)
        changed = False
        for stack_name in ("undo", "redo"):
            next_stack: list[dict[str, object]] = []
            for record in value[stack_name]:
                items = record.get("items", [])
                if str(record.get("kind", "")) in ("delete", "restore") and isinstance(items, list):
                    kept = [
                        item for item in items
                        if not isinstance(item, dict) or str(item.get("id", "")) not in identifiers
                    ]
                    if len(kept) != len(items):
                        changed = True
                    if not kept:
                        continue
                    record = {**record, "items": kept}
                next_stack.append(record)
            value[stack_name] = next_stack
        if changed:
            save_operation_history(username, value)


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def resolve_operation_target(
    source: str,
    relative: str,
    scopes: dict[str, str],
) -> tuple[Path, Path] | None:
    clean = str(relative or "").replace("\\", "/").strip("/")
    parts = safe_components(clean)
    if not parts or any(
        part in (RECYCLE_DIRECTORY_NAME, HISTORY_DIRECTORY_NAME)
        for part in parts
    ):
        return None
    resolved = resolve_location(str(source or ""), clean, scopes)
    if resolved is None:
        return None
    root, within_root, _requested_parts, _stamp = resolved
    try:
        root = root.resolve()
        target = root.joinpath(*within_root)
        target.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        return None
    return root, target


def _move_without_overwrite(source: Path, destination: Path) -> None:
    if not _path_lexists(source):
        raise FileNotFoundError(source)
    if _path_lexists(destination):
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, destination)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        shutil.move(os.fspath(source), os.fspath(destination))


def _remove_tree_or_file(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _write_private_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_bytes(json_bytes(value))
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def recycle_entry_path(root: Path, username: str, trash_id: str) -> Path:
    return root / RECYCLE_DIRECTORY_NAME / operation_owner_id(username) / trash_id


def history_entry_path(root: Path, username: str, record_id: str, index: int) -> Path:
    return root / HISTORY_DIRECTORY_NAME / operation_owner_id(username) / record_id / str(index)


def move_item_to_recycle(
    username: str,
    scopes: dict[str, str],
    source: str,
    relative: str,
    trash_id: str | None = None,
) -> dict[str, object]:
    resolved = resolve_operation_target(source, relative, scopes)
    if resolved is None:
        raise PermissionError("item is outside your access")
    root, target = resolved
    if not _path_lexists(target):
        raise FileNotFoundError("item no longer exists")

    identifier = trash_id or secrets.token_hex(16)
    entry = recycle_entry_path(root, username, identifier)
    payload = entry / "payload"
    entry.mkdir(parents=True, exist_ok=False)
    info = target.lstat()
    metadata: dict[str, object] = {
        "id": identifier,
        "source": source,
        "path": "/" + str(relative or "").replace("\\", "/").strip("/"),
        "name": target.name,
        "isDir": stat.S_ISDIR(info.st_mode),
        "size": int(info.st_size),
        "deletedAt": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _move_without_overwrite(target, payload)
        _write_private_json(entry / "metadata.json", metadata)
    except BaseException:
        if _path_lexists(payload) and not _path_lexists(target):
            try:
                _move_without_overwrite(payload, target)
            except OSError:
                pass
        shutil.rmtree(entry, ignore_errors=True)
        raise
    return metadata


def _recycle_item_location(
    username: str,
    scopes: dict[str, str],
    item: dict[str, object],
) -> tuple[Path, Path, Path]:
    resolved = resolve_operation_target(
        str(item.get("source", "")),
        str(item.get("path", "")),
        scopes,
    )
    if resolved is None:
        raise PermissionError("recycled item is outside your access")
    root, target = resolved
    entry = recycle_entry_path(root, username, str(item.get("id", "")))
    return entry, entry / "payload", target


def restore_recycle_item(
    username: str,
    scopes: dict[str, str],
    item: dict[str, object],
) -> None:
    entry, payload, target = _recycle_item_location(username, scopes, item)
    _move_without_overwrite(payload, target)
    metadata = dict(item)
    metadata["restoredAt"] = datetime.now(timezone.utc).isoformat()
    _write_private_json(entry / "metadata.json", metadata)


def recycle_item_again(
    username: str,
    scopes: dict[str, str],
    item: dict[str, object],
) -> None:
    entry, payload, target = _recycle_item_location(username, scopes, item)
    entry.mkdir(parents=True, exist_ok=True)
    _move_without_overwrite(target, payload)
    metadata = dict(item)
    metadata["deletedAt"] = datetime.now(timezone.utc).isoformat()
    metadata.pop("restoredAt", None)
    _write_private_json(entry / "metadata.json", metadata)


def list_recycle_items(username: str, scopes: dict[str, str]) -> list[dict[str, object]]:
    _stamp, mapping = load_storage_map()
    roots: dict[str, Path] = {}
    for root in mapping.values():
        try:
            roots[os.fspath(root.resolve())] = root.resolve()
        except OSError:
            continue
    result: list[dict[str, object]] = []
    owner = operation_owner_id(username)
    for root in roots.values():
        container = root / RECYCLE_DIRECTORY_NAME / owner
        try:
            entries = list(container.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                metadata = json.loads((entry / "metadata.json").read_text(encoding="utf-8"))
                if not isinstance(metadata, dict) or not _path_lexists(entry / "payload"):
                    continue
                resolved = resolve_operation_target(
                    str(metadata.get("source", "")),
                    str(metadata.get("path", "")),
                    scopes,
                )
                if resolved is None or resolved[0] != root:
                    continue
                result.append(metadata)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    result.sort(key=lambda item: str(item.get("deletedAt", "")), reverse=True)
    return result


def permanently_delete_recycle_item(
    username: str,
    scopes: dict[str, str],
    item: dict[str, object],
) -> None:
    entry, payload, _target = _recycle_item_location(username, scopes, item)
    if not _path_lexists(payload):
        raise FileNotFoundError("recycled item no longer exists")
    shutil.rmtree(entry)


def _resolved_record_path(
    item: dict[str, object],
    prefix: str,
    scopes: dict[str, str],
) -> tuple[Path, Path]:
    source = str(item.get(f"{prefix}Source", item.get("source", "")))
    path = str(item.get(f"{prefix}Path", item.get("path", "")))
    resolved = resolve_operation_target(source, path, scopes)
    if resolved is None:
        raise PermissionError("operation item is outside your access")
    return resolved


def _swap_with_history_payload(target: Path, payload: Path) -> None:
    if not _path_lexists(target) or not _path_lexists(payload):
        raise FileNotFoundError("an edited version is no longer available")
    temporary = payload.with_name(f"swap-{secrets.token_hex(8)}")
    os.replace(target, temporary)
    try:
        os.replace(payload, target)
        os.replace(temporary, payload)
    except BaseException:
        if _path_lexists(temporary) and not _path_lexists(target):
            os.replace(temporary, target)
        raise


def apply_operation_record(
    username: str,
    scopes: dict[str, str],
    record: dict[str, object],
    direction: str,
) -> None:
    kind = str(record.get("kind", ""))
    items = record.get("items", [])
    if not isinstance(items, list) or not items:
        raise ValueError("operation has no items")
    reverse = direction == "undo"

    if kind in ("delete", "restore"):
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("invalid recycled item")
            should_restore = reverse if kind == "delete" else not reverse
            if should_restore:
                restore_recycle_item(username, scopes, item)
            else:
                recycle_item_again(username, scopes, item)
        return

    if kind == "move":
        ordered = list(reversed(items)) if reverse else items
        for item in ordered:
            if not isinstance(item, dict):
                raise ValueError("invalid move item")
            from_prefix, to_prefix = ("to", "from") if reverse else ("from", "to")
            _from_root, from_path = _resolved_record_path(item, from_prefix, scopes)
            _to_root, to_path = _resolved_record_path(item, to_prefix, scopes)
            _move_without_overwrite(from_path, to_path)
        return

    if kind in ("create", "copy"):
        record_id = str(record.get("id", ""))
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError("invalid created item")
            root, target = _resolved_record_path(item, "to", scopes)
            payload = history_entry_path(root, username, record_id, index) / "payload"
            if reverse:
                payload.parent.mkdir(parents=True, exist_ok=True)
                _move_without_overwrite(target, payload)
            else:
                _move_without_overwrite(payload, target)
        return

    if kind == "edit":
        record_id = str(record.get("id", ""))
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError("invalid edited item")
            root, target = _resolved_record_path(item, "to", scopes)
            payload = history_entry_path(root, username, record_id, index) / "payload"
            _swap_with_history_payload(target, payload)
        return

    raise ValueError("unsupported operation")


def change_operation_history(
    username: str,
    scopes: dict[str, str],
    action: str,
) -> dict[str, object]:
    source_name, destination_name = ("undo", "redo") if action == "undo" else ("redo", "undo")
    with _operation_lock:
        value = load_operation_history(username)
        source = value[source_name]
        if not source:
            return {**history_summary(value), "changed": False, "message": f"Nothing to {action}."}
        record = source[-1]
        apply_operation_record(username, scopes, record, action)
        source.pop()
        value[destination_name].append(record)
        discarded = value[destination_name][:-MAX_OPERATION_HISTORY_ITEMS]
        value[destination_name] = value[destination_name][-MAX_OPERATION_HISTORY_ITEMS:]
        save_operation_history(username, value)
        for old_record in discarded:
            discard_operation_artifacts(username, old_record)
        label = str(record.get("label", "change"))
        return {
            **history_summary(value),
            "changed": True,
            "kind": str(record.get("kind", "")),
            "message": f"{('Undid' if action == 'undo' else 'Redid')} {label}.",
        }


def create_edit_history_plan(
    username: str,
    scopes: dict[str, str],
    source: str,
    relative: str,
) -> dict[str, object] | None:
    resolved = resolve_operation_target(source, relative, scopes)
    if resolved is None:
        return None
    root, target = resolved
    record_id = secrets.token_hex(12)
    descriptor = {
        "toSource": source,
        "toPath": "/" + relative.replace("\\", "/").strip("/"),
    }
    if not _path_lexists(target):
        return {
            "id": record_id,
            "kind": "create",
            "label": f"create {target.name}",
            "items": [descriptor],
        }

    entry = history_entry_path(root, username, record_id, 0)
    payload = entry / "payload"
    entry.mkdir(parents=True, exist_ok=False)
    if target.is_dir() and not target.is_symlink():
        shutil.copytree(target, payload, symlinks=True)
    else:
        shutil.copy2(target, payload, follow_symlinks=False)
    return {
        "id": record_id,
        "kind": "edit",
        "label": f"edit {target.name}",
        "items": [descriptor],
    }


def microsoft_file_versions(username: str, scopes: dict[str, str], source: str, relative: str) -> list[dict[str, object]]:
    """Only expose this account's still-recoverable pre-edit snapshots."""
    resolved = resolve_operation_target(source, relative, scopes)
    if resolved is None:
        return []
    root, target = resolved
    versions = []
    with _operation_lock:
        for record in reversed(load_operation_history(username)["undo"]):
            record_id = str(record.get("id", ""))
            if record.get("kind") != "edit" or not re.fullmatch(r"[a-f0-9]{24}", record_id):
                continue
            for index, item in enumerate(record.get("items", [])):
                if not isinstance(item, dict):
                    continue
                original = resolve_operation_target(str(item.get("toSource", "")), str(item.get("toPath", "")), scopes)
                if original is None or original[1] != target:
                    continue
                payload = history_entry_path(root, username, record_id, index) / "payload"
                # History must remain inside the resolved storage root, without
                # symlink traversal (including an altered history directory).
                if payload.resolve() != root.resolve() / payload.relative_to(root) or not payload.is_file():
                    continue
                versions.append({"id": f"{record_id}:{index}", "before": record.get("timestamp", ""),
                                 "bytes": payload.stat().st_size, "payload": payload})
    return versions


def microsoft_restore_version(username: str, scopes: dict[str, str], source: str, relative: str,
                              version_id: str, expected_revision: str) -> None:
    with _operation_lock:
        resolved = resolve_operation_target(source, relative, scopes)
        if resolved is None:
            raise MicrosoftBridgeError("File unavailable.", 404, "file_unavailable")
        root, target = resolved
        parts = list(target.relative_to(root).parts)
        before = stat_location(root, parts)
        revision = f"{before.st_mtime_ns}:{before.st_size}"
        if not expected_revision or revision != expected_revision:
            raise MicrosoftBridgeError("The file changed. Refresh the version list before restoring.", 409, "local_conflict")
        version = next((v for v in microsoft_file_versions(username, scopes, source, relative) if v["id"] == version_id), None)
        if version is None:
            raise MicrosoftBridgeError("This version is no longer available.", 404, "version_unavailable")
        parent_fd = open_directory(root, parts[:-1])
        temporary = f".plexpoint-restore-{secrets.token_hex(12)}.tmp"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent_fd)
            with os.fdopen(fd, "wb") as output, Path(version["payload"]).open("rb") as snapshot:
                shutil.copyfileobj(snapshot, output)
                output.flush()
                os.fchmod(output.fileno(), stat.S_IMODE(before.st_mode))
                os.fsync(output.fileno())
            current = stat_location(root, parts)
            if (current.st_mtime_ns, current.st_size) != (before.st_mtime_ns, before.st_size):
                raise MicrosoftBridgeError("The file changed during restore. Nothing was replaced.", 409, "local_conflict")
            backup = create_edit_history_plan(username, scopes, source, relative)
            if backup is None or backup.get("kind") != "edit":
                raise MicrosoftBridgeError("The current version could not be backed up. Nothing was replaced.", 500, "backup_failed")
            backup["label"] = f"restore version of {target.name}"
            # Index the recovery copy before replacement. If replacement fails,
            # the extra identical snapshot is harmless and remains recoverable.
            record_operation(username, backup)
            os.replace(temporary, parts[-1], src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            os.close(parent_fd)


def discard_operation_artifacts(username: str, record: dict[str, object]) -> None:
    if str(record.get("kind", "")) not in ("create", "copy", "edit"):
        return
    record_id = str(record.get("id", ""))
    owner = operation_owner_id(username)
    _stamp, mapping = load_storage_map()
    for root in mapping.values():
        shutil.rmtree(root / HISTORY_DIRECTORY_NAME / owner / record_id, ignore_errors=True)


def prepare_resource_proxy_operation(
    username: str,
    scopes: dict[str, str],
    method: str,
    parsed: urllib.parse.SplitResult,
    request_body: bytes | None,
) -> dict[str, object] | None:
    if parsed.path.rstrip("/") != "/api/resources":
        return None
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if method in ("POST", "PUT"):
        source = query.get("source", [""])[0]
        relative = query.get("path", [""])[0]
        if not source or not str(relative).strip("/"):
            return None
        return create_edit_history_plan(username, scopes, source, relative)

    if method != "PATCH" or not request_body:
        return None
    try:
        value = json.loads(request_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    action = str(value.get("action", "")).lower()
    raw_items = value.get("items", [])
    if action not in ("move", "rename", "copy") or not isinstance(raw_items, list):
        return None
    if value.get("overwrite") is True:
        # Restoring an overwritten destination requires a second snapshot per
        # item. Refuse to journal it rather than offering an unsafe partial undo.
        return None

    items: list[dict[str, object]] = []
    for raw in raw_items[:256]:
        if not isinstance(raw, dict):
            return None
        item = {
            "fromSource": str(raw.get("fromSource", "")),
            "fromPath": str(raw.get("fromPath", "")),
            "toSource": str(raw.get("toSource", "")),
            "toPath": str(raw.get("toPath", "")),
        }
        from_resolved = _resolved_record_path(item, "from", scopes)
        to_resolved = _resolved_record_path(item, "to", scopes)
        if not _path_lexists(from_resolved[1]):
            return None
        if _path_lexists(to_resolved[1]):
            if value.get("rename") is not True:
                return None
            try:
                item["_autoRename"] = {
                    "before": sorted(child.name for child in to_resolved[1].parent.iterdir()),
                    "parentPath": "/" + str(Path(item["toPath"]).parent).replace("\\", "/").strip("./"),
                }
            except OSError:
                return None
        items.append(item)
    if not items:
        return None
    noun = Path(str(items[0].get("fromPath", ""))).name or "item"
    return {
        "id": secrets.token_hex(12),
        "kind": "copy" if action == "copy" else "move",
        "label": f"{action} {noun}" if len(items) == 1 else f"{action} {len(items)} items",
        "items": items,
    }


def finalize_resource_proxy_operation(
    username: str,
    scopes: dict[str, str],
    record: dict[str, object] | None,
    succeeded: bool,
) -> None:
    if record is None:
        return
    if not succeeded:
        discard_operation_artifacts(username, record)
        return
    kind = str(record.get("kind", ""))
    items = record.get("items", [])
    if not isinstance(items, list):
        discard_operation_artifacts(username, record)
        return
    try:
        used_auto_destinations: set[tuple[str, str, str]] = set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("invalid operation item")
            auto = item.get("_autoRename")
            if isinstance(auto, dict):
                _requested_root, requested = _resolved_record_path(item, "to", scopes)
                before = {
                    str(name) for name in auto.get("before", [])
                    if isinstance(name, str)
                }
                additions = [
                    child.name for child in requested.parent.iterdir()
                    if child.name not in before
                    and child.name not in (RECYCLE_DIRECTORY_NAME, HISTORY_DIRECTORY_NAME)
                    and (
                        str(item.get("toSource", "")),
                        os.fspath(requested.parent),
                        child.name,
                    ) not in used_auto_destinations
                ]
                wanted = requested.name
                wanted_suffix = Path(wanted).suffix
                wanted_stem = wanted[:-len(wanted_suffix)] if wanted_suffix else wanted
                matches = [
                    name for name in additions
                    if (not wanted_suffix or Path(name).suffix.casefold() == wanted_suffix.casefold())
                    and (Path(name).stem if wanted_suffix else name).casefold().startswith(wanted_stem.casefold())
                ]
                candidates = sorted(matches or additions, key=str.casefold)
                if not candidates:
                    raise FileNotFoundError("auto-renamed destination was not found")
                actual_name = candidates[0]
                parent_path = str(auto.get("parentPath", "/")).rstrip("/")
                item["toPath"] = f"{parent_path}/{actual_name}".replace("//", "/")
                item.pop("_autoRename", None)
                used_auto_destinations.add((
                    str(item.get("toSource", "")),
                    os.fspath(requested.parent),
                    actual_name,
                ))
            _to_root, destination = _resolved_record_path(item, "to", scopes)
            if not _path_lexists(destination):
                raise FileNotFoundError(destination)
            if kind == "move":
                _from_root, source = _resolved_record_path(item, "from", scopes)
                if _path_lexists(source):
                    raise FileExistsError(source)
        record_operation(username, record)
    except (OSError, ValueError, PermissionError):
        discard_operation_artifacts(username, record)


class RawDosAttributes:
    """A Samba NDR blob whose attribute field can be updated in place."""

    __slots__ = (
        "payload",
        "attribute_offset",
        "valid_flags_offset",
        "compatibility_offset",
        "compatibility_length",
    )

    def __init__(
        self,
        payload: bytes,
        attribute_offset: int,
        valid_flags_offset: int | None = None,
        compatibility_offset: int | None = None,
        compatibility_length: int = 0,
    ) -> None:
        self.payload = bytearray(payload)
        self.attribute_offset = attribute_offset
        self.valid_flags_offset = valid_flags_offset
        self.compatibility_offset = compatibility_offset
        self.compatibility_length = compatibility_length

    def update(self, attributes: int) -> bytes:
        """Change only DOS attribute metadata, preserving timestamps and sizes."""
        struct.pack_into("<I", self.payload, self.attribute_offset, attributes)
        if self.valid_flags_offset is not None:
            valid_flags = struct.unpack_from("<I", self.payload, self.valid_flags_offset)[0]
            struct.pack_into(
                "<I",
                self.payload,
                self.valid_flags_offset,
                valid_flags | 0x00000001,
            )
        if self.compatibility_offset is not None and self.compatibility_length:
            encoded = f"0x{attributes:x}".encode("ascii")
            if len(encoded) == self.compatibility_length:
                start = self.compatibility_offset
                self.payload[start:start + self.compatibility_length] = encoded
        return bytes(self.payload)


def _aligned(value: int, boundary: int) -> int:
    return (value + boundary - 1) & ~(boundary - 1)


def raw_samba_dos_attributes(payload: bytes) -> tuple[int, RawDosAttributes]:
    """Decode Samba's xattr_DOSATTRIB wrapper without optional Samba bindings.

    The wrapper starts with a variable-length, NUL-terminated compatibility
    string.  Older versions put values such as ``0x20`` there, while current
    versions use an empty string.  The former implementation assumed that the
    version was always at byte 2, so it missed native Hidden attributes written
    by older Samba installations.
    """
    terminator = payload.find(b"\0")
    if terminator < 0:
        raise OSError(errno.EINVAL, "unsupported DOS attribute data")
    try:
        compatibility = payload[:terminator].decode("ascii")
    except UnicodeDecodeError as error:
        raise OSError(errno.EINVAL, "unsupported DOS attribute data") from error
    if compatibility and not re.fullmatch(r"0x[0-9a-fA-F]+", compatibility):
        raise OSError(errno.EINVAL, "unsupported DOS attribute data")

    version_offset = _aligned(terminator + 1, 2)
    if len(payload) < version_offset + 2:
        raise OSError(errno.EINVAL, "unsupported DOS attribute data")
    version = struct.unpack_from("<H", payload, version_offset)[0]
    discriminator_offset = _aligned(version_offset + 2, 4)
    if len(payload) < discriminator_offset + 4:
        raise OSError(errno.EINVAL, "unsupported DOS attribute data")
    discriminator = struct.unpack_from("<I", payload, discriminator_offset)[0]
    if discriminator != version or version not in {1, 2, 3, 4, 5}:
        raise OSError(errno.EINVAL, "unsupported DOS attribute data")

    union_offset = discriminator_offset + 4
    valid_flags_offset = union_offset if version in {3, 4, 5} else None
    attribute_offset = union_offset if version == 1 else union_offset + 4
    if len(payload) < attribute_offset + 4:
        raise OSError(errno.EINVAL, "unsupported DOS attribute data")
    attributes = struct.unpack_from("<I", payload, attribute_offset)[0]
    if valid_flags_offset is not None:
        valid_flags = struct.unpack_from("<I", payload, valid_flags_offset)[0]
        if not valid_flags & 0x00000001:
            attributes = 0
    return attributes, RawDosAttributes(
        payload,
        attribute_offset,
        valid_flags_offset,
        0 if compatibility else None,
        len(compatibility),
    )


def decode_dos_attributes(payload: bytes) -> tuple[int, object | None]:
    if samba_xattr is not None and ndr_unpack is not None:
        try:
            value = ndr_unpack(samba_xattr.DOSATTRIB, payload)
            return int(value.info.attrib), value
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    try:
        legacy = payload.strip().strip(b'"').decode("ascii")
        if legacy.lower().startswith("0x"):
            return int(legacy, 16), None
    except (UnicodeDecodeError, ValueError):
        pass

    return raw_samba_dos_attributes(payload)


def read_fat_attributes(file_fd: int) -> int:
    if fcntl is None:
        raise OSError(errno.ENOTSUP, "native FAT attributes are unavailable")
    value = bytearray(4)
    fcntl.ioctl(file_fd, FAT_IOCTL_GET_ATTRIBUTES, value, True)
    return struct.unpack("=I", value)[0]


def _attribute_missing(error: OSError) -> bool:
    missing = {errno.ENODATA}
    if hasattr(errno, "ENOATTR"):
        missing.add(errno.ENOATTR)
    return error.errno in missing


def _attribute_unavailable(error: OSError) -> bool:
    return error.errno in {
        errno.EINVAL,
        errno.ENOSYS,
        errno.ENOTTY,
        errno.ENOTSUP,
        errno.EOPNOTSUPP,
    }


def read_native_windows_attributes(file_fd: int) -> tuple[int, str] | None:
    """Read a drive's native Windows attribute bits when it exposes them."""
    for attribute_name, byte_order, storage in (
        (NTFS_ATTRIBUTE_NAME, "=I", "ntfs"),
        (NTFS_ATTRIBUTE_BIG_ENDIAN_NAME, ">I", "ntfs-be"),
    ):
        try:
            payload = os.getxattr(file_fd, attribute_name)
        except OSError as error:
            if _attribute_missing(error) or _attribute_unavailable(error):
                continue
            raise
        if len(payload) != 4:
            raise OSError(errno.EINVAL, f"invalid {attribute_name} data")
        return struct.unpack(byte_order, payload)[0], storage

    try:
        return read_fat_attributes(file_fd), "fat"
    except OSError as error:
        if _attribute_missing(error) or _attribute_unavailable(error):
            return None
        raise


def read_dos_attributes(file_fd: int) -> tuple[int, object | None, str]:
    try:
        payload = os.getxattr(file_fd, DOS_ATTRIBUTE_NAME)
    except OSError as error:
        if not (_attribute_missing(error) or _attribute_unavailable(error)):
            raise
        native = read_native_windows_attributes(file_fd)
        if native is None:
            return 0, None, "none"
        attributes, storage = native
        return attributes, None, storage
    attributes, value = decode_dos_attributes(payload)
    return attributes, value, "xattr"


def dos_hidden_location(root: Path, components: tuple[str, ...]) -> bool:
    file_fd = open_location(root, components)
    try:
        attributes, _value, _storage = read_dos_attributes(file_fd)
        return bool(attributes & DOS_ATTRIBUTE_HIDDEN)
    finally:
        os.close(file_fd)


def set_dos_hidden_location(root: Path, components: tuple[str, ...], hidden: bool) -> bool:
    file_fd = open_location(root, components)
    try:
        attributes, value, storage = read_dos_attributes(file_fd)
        updated = attributes | DOS_ATTRIBUTE_HIDDEN if hidden else attributes & ~DOS_ATTRIBUTE_HIDDEN
        if storage != "none" and updated == attributes:
            return bool(updated & DOS_ATTRIBUTE_HIDDEN)
        if storage == "none" and not hidden:
            return False
        if storage == "fat":
            if fcntl is None:
                raise OSError(errno.ENOTSUP, "native FAT attributes are unavailable")
            fcntl.ioctl(file_fd, FAT_IOCTL_SET_ATTRIBUTES, struct.pack("=I", updated))
            return bool(updated & DOS_ATTRIBUTE_HIDDEN)
        if storage == "ntfs":
            os.setxattr(file_fd, NTFS_ATTRIBUTE_NAME, struct.pack("=I", updated))
            return bool(updated & DOS_ATTRIBUTE_HIDDEN)
        if storage == "ntfs-be":
            os.setxattr(file_fd, NTFS_ATTRIBUTE_BIG_ENDIAN_NAME, struct.pack(">I", updated))
            return bool(updated & DOS_ATTRIBUTE_HIDDEN)
        if storage == "none":
            info = os.fstat(file_fd)
            updated |= DOS_ATTRIBUTE_DIRECTORY if stat.S_ISDIR(info.st_mode) else DOS_ATTRIBUTE_ARCHIVE
        if isinstance(value, RawDosAttributes):
            payload = value.update(updated)
        elif value is not None:
            if ndr_pack is None:
                raise OSError(errno.ENOTSUP, "Samba DOS attributes are unavailable")
            try:
                value.info.valid_flags |= samba_xattr.XATTR_DOSINFO_ATTRIB
            except AttributeError:
                pass
            value.info.attrib = updated
            payload = ndr_pack(value)
        elif samba_xattr is not None and ndr_pack is not None:
            value = samba_xattr.DOSATTRIB()
            value.version = 5
            value.info.valid_flags = samba_xattr.XATTR_DOSINFO_ATTRIB
            value.info.create_time = 0
            value.info.attrib = updated
            payload = ndr_pack(value)
        else:
            # Samba accepts its legacy hexadecimal representation too.  This
            # keeps Hidden working on small systems without Python Samba
            # bindings while remaining visible to Windows SMB clients.
            payload = f"0x{updated:x}".encode("ascii")
        os.setxattr(file_fd, DOS_ATTRIBUTE_NAME, payload)
        return bool(updated & DOS_ATTRIBUTE_HIDDEN)
    finally:
        os.close(file_fd)


def filesystem_hidden(
    root: Path,
    components: tuple[str, ...],
    username: str = "",
    canonical: str = "",
) -> bool:
    try:
        hidden = dos_hidden_location(root, components)
    except OSError:
        return False
    if not username or not canonical:
        return hidden
    legacy_items = load_hidden_items(username)
    if canonical not in legacy_items:
        return hidden
    try:
        if not hidden:
            hidden = set_dos_hidden_location(root, components, True)
        if hidden:
            with _hidden_lock:
                legacy_items = load_hidden_items(username)
                legacy_items.discard(canonical)
                save_hidden_items(username, legacy_items)
    except OSError:
        return False
    return hidden


SEARCH_KIND_EXTENSIONS = {
    "document": frozenset({
        ".doc", ".docx", ".dot", ".dotx", ".odt", ".pdf", ".rtf", ".txt",
        ".md", ".csv", ".xls", ".xlsx", ".xlsm", ".ods", ".ppt", ".pptx",
        ".pps", ".ppsx", ".odp",
    }),
    "picture": frozenset({
        ".avif", ".bmp", ".gif", ".heic", ".ico", ".jpeg", ".jpg", ".png",
        ".svg", ".tif", ".tiff", ".webp",
    }),
    "music": frozenset({
        ".aac", ".aiff", ".alac", ".flac", ".m4a", ".mp3", ".ogg", ".opus",
        ".wav", ".wma",
    }),
    "video": frozenset({
        ".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg",
        ".webm", ".wmv",
    }),
    "archive": frozenset({
        ".7z", ".bz2", ".gz", ".rar", ".tar", ".tgz", ".xz", ".zip",
    }),
    "program": frozenset({
        ".appimage", ".bat", ".cmd", ".com", ".exe", ".js", ".msi", ".ps1",
        ".py", ".sh",
    }),
}


def _search_tokens(value: str) -> list[str]:
    try:
        return shlex.split(value, posix=True)
    except ValueError:
        return [part for part in re.split(r"\s+", value.strip()) if part]


def _search_size(value: str) -> tuple[str, int] | None:
    presets = {
        "empty": ("=", 0),
        "tiny": ("range", (1, 16 * 1024)),
        "small": ("range", (16 * 1024 + 1, 1024 * 1024)),
        "medium": ("range", (1024 * 1024 + 1, 128 * 1024 * 1024)),
        "large": ("range", (128 * 1024 * 1024 + 1, 1024 * 1024 * 1024)),
        "huge": ("range", (1024 * 1024 * 1024 + 1, 4 * 1024 * 1024 * 1024)),
        "gigantic": (">", 4 * 1024 * 1024 * 1024),
    }
    normalized = value.strip().lower().replace(" ", "")
    if normalized in presets:
        return presets[normalized]  # type: ignore[return-value]
    match = re.fullmatch(r"(<=|>=|<|>|=)?(\d+(?:\.\d+)?)(b|kb|mb|gb|tb)?", normalized)
    if not match:
        return None
    operator = match.group(1) or "="
    amount = float(match.group(2))
    powers = {"b": 0, "kb": 1, "mb": 2, "gb": 3, "tb": 4}
    return operator, int(amount * (1024 ** powers.get(match.group(3) or "b", 0)))


def _search_date_range(value: str, now: datetime | None = None) -> tuple[float, float] | None:
    current = (now or datetime.now()).astimezone()
    today = current.replace(hour=0, minute=0, second=0, microsecond=0)
    normalized = re.sub(r"[\s_-]+", "", value.strip().lower())
    day = timedelta(days=1)
    if normalized == "today":
        start, end = today, today + day
    elif normalized == "yesterday":
        start, end = today - day, today
    elif normalized in {"thisweek", "week"}:
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)
    elif normalized == "lastweek":
        end = today - timedelta(days=today.weekday())
        start = end - timedelta(days=7)
    elif normalized in {"thismonth", "month"}:
        start = today.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1)
    elif normalized == "lastmonth":
        end = today.replace(day=1)
        start = (end - day).replace(day=1)
    elif normalized in {"thisyear", "year"}:
        start = today.replace(month=1, day=1)
        end = start.replace(year=start.year + 1)
    else:
        try:
            start = datetime.fromisoformat(value).astimezone()
        except ValueError:
            return None
        end = start + day
    return start.timestamp(), end.timestamp()


def parse_search_query(value: str) -> dict[str, object]:
    criteria: dict[str, object] = {
        "terms": [],
        "names": [],
        "extensions": set(),
        "kinds": set(),
        "sizes": [],
        "dates": [],
    }
    for token in _search_tokens(value[:1024]):
        field, separator, raw = token.partition(":")
        field = field.lower()
        if not separator or not raw:
            criteria["terms"].append(token.casefold())  # type: ignore[union-attr]
        elif field == "name":
            criteria["names"].append(raw.casefold())  # type: ignore[union-attr]
        elif field in {"ext", "extension"}:
            criteria["extensions"].add("." + raw.casefold().lstrip("*."))  # type: ignore[union-attr]
        elif field in {"kind", "type"}:
            criteria["kinds"].add(raw.casefold().rstrip("s"))  # type: ignore[union-attr]
        elif field == "size":
            parsed = _search_size(raw)
            if parsed:
                criteria["sizes"].append(parsed)  # type: ignore[union-attr]
        elif field in {"date", "modified", "datemodified"}:
            parsed = _search_date_range(raw)
            if parsed:
                criteria["dates"].append(parsed)  # type: ignore[union-attr]
        else:
            criteria["terms"].append(token.casefold())  # type: ignore[union-attr]
    return criteria


def _search_text_match(pattern: str, value: str) -> bool:
    return fnmatch.fnmatchcase(value, pattern) if any(char in pattern for char in "*?") else pattern in value


def search_item_matches(
    name: str,
    relative: str,
    is_dir: bool,
    size: int,
    modified: float,
    criteria: dict[str, object],
) -> bool:
    folded_name = name.casefold()
    folded_relative = relative.casefold()
    extension = Path(name).suffix.casefold()
    for term in criteria.get("terms", []):
        if not (_search_text_match(str(term), folded_name) or _search_text_match(str(term), folded_relative)):
            return False
    for pattern in criteria.get("names", []):
        if not _search_text_match(str(pattern), folded_name):
            return False
    extensions = criteria.get("extensions", set())
    if extensions and extension not in extensions:
        return False
    kinds = criteria.get("kinds", set())
    if kinds:
        matched_kind = False
        for kind in kinds:
            kind = str(kind)
            if kind in {"folder", "directory"} and is_dir:
                matched_kind = True
            elif kind == "file" and not is_dir:
                matched_kind = True
            elif not is_dir and extension in SEARCH_KIND_EXTENSIONS.get(kind, frozenset()):
                matched_kind = True
            elif not is_dir and kind.lstrip(".") == extension.lstrip("."):
                matched_kind = True
        if not matched_kind:
            return False
    if is_dir and (criteria.get("sizes") or criteria.get("dates")):
        return False
    for operator, amount in criteria.get("sizes", []):
        if operator == "range":
            if not amount[0] <= size <= amount[1]:
                return False
        elif operator == ">" and not size > amount:
            return False
        elif operator == ">=" and not size >= amount:
            return False
        elif operator == "<" and not size < amount:
            return False
        elif operator == "<=" and not size <= amount:
            return False
        elif operator == "=" and not size == amount:
            return False
    for start, end in criteria.get("dates", []):
        if not start <= modified < end:
            return False
    return True


def search_type_label(name: str, is_dir: bool) -> str:
    if is_dir:
        return "File folder"
    extension = Path(name).suffix.lstrip(".")
    return f"{extension.upper()} File" if extension else "File"


def search_tree(
    roots: list[tuple[str, Path, tuple[str, ...], tuple[str, ...]]],
    query: str,
    recursive: bool,
    show_hidden: bool,
    username: str,
) -> dict[str, object]:
    criteria = parse_search_query(query)
    legacy_hidden = load_hidden_items(username)
    results: list[dict[str, object]] = []
    scanned = 0
    truncated = False
    started = time.monotonic()
    deadline = started + SEARCH_MAX_SECONDS
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    stack: list[tuple[str, Path, int, tuple[str, ...], tuple[str, ...]]] = []
    for source, root, within_root, requested_parts in roots:
        try:
            stack.append((source, root, open_directory(root, within_root), within_root, requested_parts))
        except OSError:
            continue
    try:
        while stack:
            source, root, directory_fd, disk_parts, route_parts = stack.pop()
            try:
                with os.scandir(directory_fd) as entries:
                    for entry in entries:
                        if entry.name in (RECYCLE_DIRECTORY_NAME, HISTORY_DIRECTORY_NAME):
                            continue
                        scanned += 1
                        if scanned > SEARCH_MAX_SCANNED or time.monotonic() >= deadline:
                            truncated = True
                            break
                        try:
                            info = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        is_dir = stat.S_ISDIR(info.st_mode)
                        child_disk = (*disk_parts, entry.name)
                        child_route = (*route_parts, entry.name)
                        canonical = canonical_location(source, child_route, child_disk)
                        try:
                            hidden = dos_hidden_location(root, child_disk) or bool(canonical and canonical in legacy_hidden)
                        except OSError:
                            hidden = bool(canonical and canonical in legacy_hidden)
                        if recursive and is_dir and (show_hidden or not hidden):
                            try:
                                child_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                                stack.append((source, root, child_fd, child_disk, child_route))
                            except OSError:
                                pass
                        if hidden and not show_hidden:
                            continue
                        relative = "/".join(child_route)
                        if not search_item_matches(
                            entry.name,
                            relative,
                            is_dir,
                            int(info.st_size),
                            float(info.st_mtime),
                            criteria,
                        ):
                            continue
                        results.append({
                            "source": source,
                            "path": relative,
                            "name": entry.name,
                            "location": "/".join(child_route[:-1]),
                            "directory": is_dir,
                            "size": None if is_dir else int(info.st_size),
                            "modified": int(info.st_mtime * 1000),
                            "type": search_type_label(entry.name, is_dir),
                            "hidden": hidden,
                        })
                        if len(results) >= SEARCH_MAX_RESULTS:
                            truncated = True
                            break
            finally:
                os.close(directory_fd)
            if truncated:
                break
    finally:
        for _source, _root, directory_fd, _disk_parts, _route_parts in stack:
            try:
                os.close(directory_fd)
            except OSError:
                pass
    results.sort(key=lambda item: (
        not bool(item["directory"]),
        str(item["name"]).casefold(),
        str(item["location"]).casefold(),
    ))
    return {
        "status": "ready",
        "items": results,
        "count": len(results),
        "scanned": min(scanned, SEARCH_MAX_SCANNED),
        "truncated": truncated,
        "elapsedMs": int((time.monotonic() - started) * 1000),
    }


def scan_directory(directory_fd: int) -> dict[str, int]:
    logical_size = 0
    allocated_size = 0
    file_count = 0
    folder_count = 0
    stack = [os.dup(directory_fd)]
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.name in (RECYCLE_DIRECTORY_NAME, HISTORY_DIRECTORY_NAME):
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.S_ISREG(info.st_mode):
                        logical_size += info.st_size
                        allocated_size += getattr(info, "st_blocks", 0) * 512
                        file_count += 1
                    elif stat.S_ISDIR(info.st_mode):
                        folder_count += 1
                        try:
                            stack.append(os.open(entry.name, flags, dir_fd=current))
                        except OSError:
                            continue
        finally:
            os.close(current)
    return {
        "size": logical_size,
        "allocated": allocated_size,
        "files": file_count,
        "folders": folder_count,
    }


def filesystem_usage(path: Path) -> dict[str, int]:
    usage = os.statvfs(path)
    total = usage.f_blocks * usage.f_frsize
    free = usage.f_bavail * usage.f_frsize
    return {"total": total, "free": free, "used": max(0, total - free)}


def calculate_item_info(root: Path, components: tuple[str, ...], is_drive: bool) -> dict[str, int | str]:
    disk = filesystem_usage(root)
    if is_drive:
        return {"kind": "drive", **disk}
    info = stat_location(root, components)
    if stat.S_ISREG(info.st_mode):
        return {
            "kind": "file",
            "size": info.st_size,
            "allocated": getattr(info, "st_blocks", 0) * 512,
            **disk,
        }
    if not stat.S_ISDIR(info.st_mode):
        return {"kind": "other", "size": info.st_size, **disk}
    directory_fd = open_directory(root, components)
    try:
        scanned = scan_directory(directory_fd)
    finally:
        os.close(directory_fd)
    return {"kind": "folder", **scanned, **disk}


class MicrosoftBridgeError(RuntimeError):
    def __init__(self, message: str, status: int = 502, code: str = "microsoft_error") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def microsoft_serialized(method):
    """Keep bridge read/modify/write transactions from losing session updates."""
    @functools.wraps(method)
    def wrapped(*args, **kwargs):
        with _microsoft_operation_lock:
            return method(*args, **kwargs)
    return wrapped


class MicrosoftNoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def microsoft_identity(username: str) -> str:
    return hashlib.sha256(username.encode("utf-8")).hexdigest()


def microsoft_account_path(username: str) -> Path:
    return MICROSOFT_DATA_DIR / f"{microsoft_identity(username)}.json"


def load_microsoft_config() -> dict[str, object] | None:
    rclone = configparser.RawConfigParser()
    try:
        with MICROSOFT_RCLONE_CONFIG_FILE.open("r", encoding="utf-8") as handle:
            rclone.read_file(handle)
    except (OSError, UnicodeDecodeError, configparser.Error):
        rclone = configparser.RawConfigParser()
    if rclone.has_section(MICROSOFT_RCLONE_REMOTE) and (
        rclone.get(MICROSOFT_RCLONE_REMOTE, "type", fallback="").strip().lower() == "onedrive"
    ):
        return {
            "mode": "rclone",
            "rcloneConfig": str(MICROSOFT_RCLONE_CONFIG_FILE),
            "rcloneRemote": MICROSOFT_RCLONE_REMOTE,
            "maxFileBytes": MICROSOFT_MAX_FILE_BYTES,
            "maxTotalBytes": MICROSOFT_MAX_TOTAL_BYTES,
        }

    try:
        value = json.loads(MICROSOFT_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    client_id = str(value.get("clientId", "")).strip()
    tenant = str(value.get("tenant", "consumers")).strip() or "consumers"
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", client_id):
        return None
    if tenant not in ("common", "consumers", "organizations") and not re.fullmatch(
        r"[0-9a-fA-F-]{36}", tenant
    ):
        return None
    maximum = value.get("maxFileBytes", MICROSOFT_MAX_FILE_BYTES)
    total_maximum = value.get("maxTotalBytes", MICROSOFT_MAX_TOTAL_BYTES)
    try:
        maximum = max(1024 * 1024, min(int(maximum), 250 * 1024 * 1024))
        total_maximum = max(maximum, min(int(total_maximum), 1024 * 1024 * 1024))
    except (TypeError, ValueError):
        maximum = MICROSOFT_MAX_FILE_BYTES
        total_maximum = MICROSOFT_MAX_TOTAL_BYTES
    return {
        "mode": "entra",
        "clientId": client_id,
        "tenant": tenant,
        "maxFileBytes": maximum,
        "maxTotalBytes": total_maximum,
    }


def load_microsoft_account(username: str) -> dict[str, object]:
    path = microsoft_account_path(username)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    if not isinstance(value.get("sessions"), dict):
        value["sessions"] = {}
    return value


def save_microsoft_account(username: str, value: dict[str, object]) -> None:
    value["username"] = username
    MICROSOFT_DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o750)
    path = microsoft_account_path(username)
    temporary = MICROSOFT_DATA_DIR / (
        f".{path.stem}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(4)}.tmp"
    )
    temporary.write_bytes(json_bytes(value))
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def microsoft_http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    limit: int = MICROSOFT_JSON_LIMIT,
    timeout: int = 60,
) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(limit + 1)
            status = int(response.status)
    except urllib.error.HTTPError as error:
        payload = error.read(limit + 1)
        status = int(error.code)
    except (OSError, TimeoutError, urllib.error.URLError) as error:
        raise MicrosoftBridgeError("Microsoft could not be reached. Try again shortly.") from error
    if len(payload) > limit:
        raise MicrosoftBridgeError("Microsoft returned an unexpectedly large response.")
    try:
        value = json.loads(payload.decode("utf-8")) if payload else {}
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    return status, value


def microsoft_token_request(
    config: dict[str, object], values: dict[str, str]
) -> tuple[int, dict[str, object]]:
    tenant = urllib.parse.quote(str(config["tenant"]), safe="")
    body = urllib.parse.urlencode(values).encode("utf-8")
    return microsoft_http_json(
        "POST",
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        body=body,
    )


def microsoft_rclone_token(config: dict[str, object], *, refresh: bool) -> str:
    config_path = Path(str(config.get("rcloneConfig", "")))
    remote = str(config.get("rcloneRemote", "")).strip()
    if not remote or not config_path.is_file():
        raise MicrosoftBridgeError("Connect the server to Microsoft first.", 409, "not_connected")

    parser = configparser.RawConfigParser()
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
        token_value = parser.get(remote, "token", fallback="")
        token = json.loads(token_value)
    except (OSError, UnicodeDecodeError, configparser.Error, ValueError, json.JSONDecodeError) as error:
        raise MicrosoftBridgeError("The server's Microsoft connection is incomplete.", 409, "not_connected") from error
    access_token = str(token.get("access_token", "")) if isinstance(token, dict) else ""
    if not access_token:
        raise MicrosoftBridgeError("The server's Microsoft connection is incomplete.", 409, "not_connected")

    expiry = datetime.min.replace(tzinfo=timezone.utc)
    try:
        expiry = datetime.fromisoformat(str(token.get("expiry", "")).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    if not refresh or expiry > datetime.now(timezone.utc) + timedelta(minutes=2):
        return access_token

    refresh_token = str(token.get("refresh_token", ""))
    if not refresh_token:
        raise MicrosoftBridgeError("The server's Microsoft connection has expired.", 409, "not_connected")

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        obscured = MICROSOFT_RCLONE_ENCRYPTED_CLIENT_SECRET
        ciphertext = base64.urlsafe_b64decode(obscured + "=" * (-len(obscured) % 4))
        decryptor = Cipher(
            algorithms.AES(MICROSOFT_RCLONE_OBSCURE_KEY),
            modes.CTR(ciphertext[:16]),
        ).decryptor()
        client_secret = (decryptor.update(ciphertext[16:]) + decryptor.finalize()).decode("utf-8")
    except (ImportError, ValueError, UnicodeDecodeError) as error:
        raise MicrosoftBridgeError(
            "The server could not refresh its Microsoft connection.", 409, "not_connected"
        ) from error
    if not client_secret:
        raise MicrosoftBridgeError(
            "The server could not refresh its Microsoft connection.", 409, "not_connected"
        )

    body = urllib.parse.urlencode({
        "client_id": MICROSOFT_RCLONE_CLIENT_ID,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode("utf-8")
    status, refreshed = microsoft_http_json(
        "POST",
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        body=body,
    )
    if status != 200 or not refreshed.get("access_token"):
        raise MicrosoftBridgeError(
            "The server's Microsoft connection has expired. Reconnect it once on the server.",
            409,
            "not_connected",
        )

    expires_in = max(60, int(refreshed.get("expires_in", 3600)))
    token["access_token"] = str(refreshed["access_token"])
    token["token_type"] = str(refreshed.get("token_type") or token.get("token_type") or "Bearer")
    token["refresh_token"] = str(refreshed.get("refresh_token") or refresh_token)
    token["expires_in"] = expires_in
    token["expiry"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    parser.set(remote, "token", json.dumps(token, ensure_ascii=False, separators=(",", ":")))
    temporary = config_path.with_name(
        f".{config_path.name}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(4)}.tmp"
    )
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            parser.write(handle, space_around_delimiters=True)
        os.chmod(temporary, 0o600)
        os.replace(temporary, config_path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return str(token["access_token"])


def microsoft_access_token(
    username: str, config: dict[str, object], account: dict[str, object]
) -> tuple[str, dict[str, object]]:
    if config.get("mode") == "rclone":
        with _microsoft_lock:
            return microsoft_rclone_token(config, refresh=True), account

    access_token = str(account.get("accessToken", ""))
    expires_at = float(account.get("expiresAt", 0) or 0)
    if access_token and expires_at > time.time() + 120:
        return access_token, account

    refresh_token = str(account.get("refreshToken", ""))
    if not refresh_token:
        raise MicrosoftBridgeError("Connect your Microsoft account first.", 409, "not_connected")

    status, value = microsoft_token_request(
        config,
        {
            "client_id": str(config["clientId"]),
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": MICROSOFT_SCOPES,
        },
    )
    if status != 200 or not value.get("access_token"):
        raise MicrosoftBridgeError("Your Microsoft connection has expired. Connect it again.", 409, "not_connected")

    account["accessToken"] = str(value["access_token"])
    account["refreshToken"] = str(value.get("refresh_token") or refresh_token)
    account["expiresAt"] = time.time() + max(60, int(value.get("expires_in", 3600)))
    account["scope"] = str(value.get("scope") or account.get("scope") or "")
    with _microsoft_lock:
        save_microsoft_account(username, account)
    return str(account["accessToken"]), account


def microsoft_graph_json(
    access_token: str,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    content_type: str = "application/json",
    extra_headers: dict[str, str] | None = None,
    timeout: int = 90,
) -> tuple[int, dict[str, object]]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    if body is not None:
        headers["Content-Type"] = content_type
        headers["Content-Length"] = str(len(body))
    return microsoft_http_json(
        method,
        f"https://graph.microsoft.com/v1.0{path}",
        headers=headers,
        body=body,
        timeout=timeout,
    )


def microsoft_remove_temporary_copy(
    access_token: str, remote_id: str, saved_etag: str
) -> tuple[bool, dict[str, object]]:
    if not saved_etag or saved_etag == "*":
        return False, {"error": {"message": "Save the latest Microsoft copy back before retrying cleanup."}}
    encoded_id = urllib.parse.quote(remote_id, safe="")
    try:
        status, result = microsoft_graph_json(
            access_token,
            "DELETE",
            f"/me/drive/items/{encoded_id}",
            # Never bypass a lock without also protecting newer Word edits.
            extra_headers={
                "Prefer": "bypass-shared-lock, bypass-checked-out",
                "If-Match": saved_etag,
            },
        )
    except (MicrosoftBridgeError, OSError) as error:
        return False, {"error": {"message": str(error) or "Cleanup could not reach Microsoft. Retry cleanup later."}}
    if status == 412:
        return False, {"error": {"code": "remote_conflict", "message": "Word has newer changes. Save back again before removing the cloud copy."}}
    # Cleanup is idempotent: if the item has already disappeared, there is no
    # temporary cloud copy left to retain in the local session registry.
    return status in (200, 204, 404, 410), result


def microsoft_item_etag(access_token: str, remote_id: str) -> str:
    encoded_id = urllib.parse.quote(remote_id, safe="")
    status, item = microsoft_graph_json(access_token, "GET", f"/me/drive/items/{encoded_id}?$select=id,eTag")
    etag = item.get("eTag")
    if status != 200 or not isinstance(etag, str) or not etag or etag == "*":
        raise MicrosoftBridgeError(microsoft_error_message(item, "The Microsoft file version could not be verified. Please try again."))
    return etag


def microsoft_save_receipt(account: dict[str, object], canonical: str, session: dict[str, object], removed: bool) -> None:
    receipts = account.setdefault("lastSaves", {})
    receipts[canonical] = {key: session.get(key) for key in ("source", "path", "name", "app", "savedBackAt")}
    receipts[canonical]["cloudRemoved"] = removed
    while len(receipts) > 100:
        oldest = min(receipts, key=lambda key: float(receipts[key].get("savedBackAt") or 0))
        receipts.pop(oldest)


def microsoft_schedule_cleanup(session: dict[str, object], result: dict[str, object]) -> None:
    error = result.get("error", {})
    code = error.get("code", "") if isinstance(error, dict) else ""
    attempts = int(session.get("cleanupAttempts", 0))
    session["cleanupError"] = microsoft_error_message(result, "The temporary copy could not be removed.")
    # A changed version requires a new explicit save, never a newer delete tag.
    session["autoCleanup"] = code != "remote_conflict" and attempts < 6
    session["cleanupNextAttemptAt"] = time.time() + min(900, 30 * (2 ** attempts)) if session["autoCleanup"] else 0


@microsoft_serialized
def microsoft_retry_cleanup(username: str, *, now: float | None = None) -> None:
    now = time.time() if now is None else now
    account = load_microsoft_account(username)
    sessions = account.get("sessions", {})
    due = [(key, session) for key, session in sessions.items()
           if isinstance(session, dict) and session.get("autoCleanup") is True
           and session.get("autoSync") is not True
           and session.get("savedRemoteETag") and session.get("remoteId")
           and int(session.get("cleanupAttempts", 0)) < 6
           and float(session.get("cleanupNextAttemptAt", 0)) <= now]
    if not due:
        return
    config = load_microsoft_config()
    if config is None:
        return
    try:
        access_token, account = microsoft_access_token(username, config, account)
    except (MicrosoftBridgeError, OSError):
        for _key, session in due:
            session["autoCleanup"] = False
            session["cleanupError"] = "Reconnect Microsoft, then retry cloud cleanup. Your copy has been kept."
        save_microsoft_account(username, account)
        return
    for canonical, session in due:
        session["cleanupAttempts"] = int(session.get("cleanupAttempts", 0)) + 1
        removed, result = microsoft_remove_temporary_copy(access_token, str(session["remoteId"]), str(session["savedRemoteETag"]))
        if removed:
            microsoft_save_receipt(account, canonical, session, True)
            sessions.pop(canonical, None)
        else:
            microsoft_schedule_cleanup(session, result)
        save_microsoft_account(username, account)


def microsoft_copy_to_local(username, scopes, source, relative, root, within_root, session, config, access_token, force=False):
    """Download a stable cloud revision and replace only an unchanged original."""
    edit_history_record = None
    edit_history_committed = False
    try:
        local_info = stat_location(root, within_root)
        unchanged = (
            int(local_info.st_mtime_ns) == int(session.get("originalMtimeNs", -1)) and
            int(local_info.st_size) == int(session.get("originalSize", -1))
        )
        if not unchanged and not force:
            raise MicrosoftBridgeError(
                "The server file changed after the Microsoft copy was opened.",
                409,
                "local_conflict",
            )
        saved_etag = microsoft_item_etag(access_token, str(session["remoteId"]))
        remote_id = urllib.parse.quote(str(session["remoteId"]), safe="")
        request = urllib.request.Request(
            f"https://graph.microsoft.com/v1.0/me/drive/items/{remote_id}/content",
            headers={"Authorization": f"Bearer {access_token}"},
            method="GET",
        )
        maximum = int(config["maxFileBytes"])
        try:
            response = urllib.request.build_opener(MicrosoftNoRedirect()).open(request, timeout=180)
        except urllib.error.HTTPError as error:
            location = error.headers.get("Location", "")
            if error.code in (301, 302, 303, 307, 308) and location:
                error.close()
                download_url = urllib.parse.urlsplit(location)
                if download_url.scheme != "https" or not download_url.hostname:
                    raise MicrosoftBridgeError("Microsoft returned an unsafe download address.")
                try:
                    # The redirect URL is already short-lived and signed. Do
                    # not forward the Graph bearer token to Microsoft's file
                    # storage host; that host rejects it as unauthenticated.
                    response = urllib.request.urlopen(location, timeout=180)
                except urllib.error.HTTPError as download_error:
                    download_error.close()
                    raise MicrosoftBridgeError(
                        "The edited Microsoft copy could not be downloaded."
                    ) from download_error
            else:
                payload = error.read(MICROSOFT_JSON_LIMIT)
                try:
                    detail = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                    detail = {}
                error.close()
                raise MicrosoftBridgeError(microsoft_error_message(detail, "The edited Microsoft copy could not be downloaded.")) from error

        parent_fd = open_directory(root, within_root[:-1])
        temporary_name = f".{within_root[-1]}.plexpoint-microsoft-{secrets.token_hex(6)}.tmp"
        temporary_fd: int | None = None
        written = 0
        try:
            content_length = int(response.headers.get("Content-Length", "0") or 0)
            if content_length > maximum:
                raise MicrosoftBridgeError("The edited file is larger than the temporary Microsoft limit.", 413, "file_too_large")
            temporary_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > maximum:
                    raise MicrosoftBridgeError("The edited file is larger than the temporary Microsoft limit.", 413, "file_too_large")
                view = memoryview(chunk)
                while view:
                    count = os.write(temporary_fd, view)
                    view = view[count:]
            os.fchmod(temporary_fd, stat.S_IMODE(local_info.st_mode))
            os.fsync(temporary_fd)
            os.close(temporary_fd)
            temporary_fd = None
            if microsoft_item_etag(access_token, str(session["remoteId"])) != saved_etag:
                raise MicrosoftBridgeError("Word changed during the download. Wait for Word to finish saving, then save back again.", 409, "remote_conflict")
            current_info = stat_location(root, within_root)
            if (current_info.st_mtime_ns, current_info.st_size) != (local_info.st_mtime_ns, local_info.st_size):
                raise MicrosoftBridgeError("The server file changed during the download. Please review it before saving back again.", 409, "local_conflict")
            edit_history_record = create_edit_history_plan(
                username,
                scopes,
                source,
                relative,
            )
            if edit_history_record is None or edit_history_record.get("kind") != "edit":
                raise MicrosoftBridgeError("The original file could not be backed up. The Microsoft copy has been kept.", 500, "backup_failed")
            record_operation(username, edit_history_record)
            edit_history_committed = True
            os.replace(
                temporary_name,
                within_root[-1],
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
        finally:
            response.close()
            if temporary_fd is not None:
                os.close(temporary_fd)
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            os.close(parent_fd)

        return written, saved_etag
    except BaseException:
        if edit_history_record is not None and not edit_history_committed:
            discard_operation_artifacts(username, edit_history_record)
        raise


def microsoft_desktop_url(access_token: str, remote_id: str, app: str) -> str:
    encoded_id = urllib.parse.quote(remote_id, safe="")
    status, remote = microsoft_graph_json(access_token, "GET", f"/me/drive/items/{encoded_id}?$select=id,webDavUrl,webUrl")
    url = str(remote.get("webDavUrl") or "")
    if not url and str(remote.get("webUrl", "")).split("?", 1)[0].lower().endswith(tuple(MICROSOFT_DESKTOP_EXTENSIONS)):
        url = str(remote["webUrl"])
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    scheme = {"Word": "ms-word", "Excel": "ms-excel", "PowerPoint": "ms-powerpoint"}.get(app)
    if status != 200 or not scheme or parsed.scheme != "https" or parsed.username or parsed.password or "|" in url or any(ord(c) < 32 for c in url) or not (
        host == "d.docs.live.net" or host.endswith(".sharepoint.com") or host.endswith(".docs.live.net")
    ):
        raise MicrosoftBridgeError("Microsoft did not return a desktop editing address. The cloud copy has been kept.", 502, "desktop_url_unavailable")
    return f"{scheme}:ofe|u|{url}"


def microsoft_enable_autosync(session, scopes, root, within_root):
    # Explicit per-file grant, created only by an authenticated edit request.
    # No browser credential is stored; the grant cannot follow a source remap.
    info = stat_location(root, within_root)
    if (info.st_mtime_ns, info.st_size) != (session.get("originalMtimeNs"), session.get("originalSize")):
        raise MicrosoftBridgeError("The FilePoint original changed separately. Automatic syncing is paused; both copies have been kept.", 409, "local_conflict")
    session.update(autoSync=True, autoCleanup=False, cleanupNextAttemptAt=0,
                   syncScopes={session["source"]: scopes[session["source"]]},
                   syncRoot=str(root.resolve()), syncError="", syncState="waiting",
                   syncNextAttemptAt=0, syncAttempts=0)


@microsoft_serialized
def microsoft_sync_account(username: str, *, now: float | None = None) -> None:
    now = time.time() if now is None else now
    account = load_microsoft_account(username)
    config = load_microsoft_config()
    if config is None:
        return
    for canonical, session in account.get("sessions", {}).items():
        if not isinstance(session, dict) or session.get("autoSync") is not True or float(session.get("syncNextAttemptAt", 0)) > now:
            continue
        try:
            source, relative = str(session.get("source", "")), str(session.get("path", ""))
            scopes = session.get("syncScopes", {})
            resolved = resolve_location(source, relative.strip("/"), scopes)
            if resolved is None:
                raise MicrosoftBridgeError("The original location is unavailable. Both copies have been kept.", 409, "original_unavailable")
            root, within_root, requested, _stamp = resolved
            if str(root.resolve()) != session.get("syncRoot") or canonical_location(source, requested, within_root) != canonical or not within_root:
                raise MicrosoftBridgeError("The original location changed. Both copies have been kept.", 409, "original_unavailable")
            info = stat_location(root, within_root)
            if (info.st_mtime_ns, info.st_size) != (session.get("originalMtimeNs"), session.get("originalSize")):
                raise MicrosoftBridgeError("The FilePoint original changed separately. Both copies have been kept; review them before resuming.", 409, "local_conflict")
            access_token, account = microsoft_access_token(username, config, account)
            etag = microsoft_item_etag(access_token, str(session["remoteId"]))
            if etag != session.get("syncRemoteETag"):
                written, saved_etag = microsoft_copy_to_local(username, scopes, source, relative, root, within_root, session, config, access_token)
                refreshed = stat_location(root, within_root)
                session.update(originalMtimeNs=int(refreshed.st_mtime_ns), originalSize=int(refreshed.st_size),
                               remoteSize=written, syncRemoteETag=saved_etag, savedRemoteETag=saved_etag,
                               savedBackAt=time.time())
                microsoft_save_receipt(account, canonical, session, False)
            session.update(syncState="synced", syncError="", syncAttempts=0, syncCheckedAt=time.time(), syncNextAttemptAt=now + 15)
        except (MicrosoftBridgeError, OSError, ValueError, TypeError, KeyError) as error:
            code = getattr(error, "code", "sync_failed")
            pause = code in ("local_conflict", "original_unavailable", "backup_failed") or isinstance(error, (FileNotFoundError, PermissionError))
            attempts = int(session.get("syncAttempts", 0)) + 1
            session.update(autoSync=not pause, syncState="paused" if pause else "retrying",
                           syncError=str(error), syncAttempts=attempts,
                           syncNextAttemptAt=now + min(300, 15 * (2 ** min(attempts, 5))))
        save_microsoft_account(username, account)


def microsoft_cleanup_worker(stop: threading.Event) -> None:
    while not stop.wait(15):
        for path in MICROSOFT_DATA_DIR.glob("*.json"):
            if stop.is_set():
                return
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                username = value.get("username") if isinstance(value, dict) else None
                # Old sessions are deliberately not enrolled in automatic deletion.
                if isinstance(username, str) and path.name == microsoft_account_path(username).name:
                    microsoft_sync_account(username)
                    microsoft_retry_cleanup(username)
            except (OSError, ValueError, TypeError, MicrosoftBridgeError):
                # Isolate one damaged account or temporary outage from other users.
                continue


def microsoft_error_message(value: dict[str, object], fallback: str) -> str:
    error = value.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    if isinstance(error, str) and error.strip():
        description = value.get("error_description")
        if isinstance(description, str) and description.strip():
            return description.strip().split("\r\n", 1)[0]
        return error.strip()
    return fallback


def microsoft_remote_name(canonical: str, name: str) -> str:
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    cleaned = re.sub(r'[\\/*<>?:|#%"]', "_", name).strip(" .") or "Office document"
    suffix = Path(cleaned).suffix
    stem = Path(cleaned).stem[: max(1, 145 - len(suffix))].rstrip(" .")
    return f"{digest} - {stem}{suffix}"


def microsoft_other_editors(username: str, canonical: str, file_identity: str) -> int:
    count = 0
    own_path = microsoft_account_path(username)
    for path in MICROSOFT_DATA_DIR.glob("*.json"):
        if path == own_path:
            continue
        try:
            account = json.loads(path.read_text(encoding="utf-8"))
            for key, session in account.get("sessions", {}).items():
                if isinstance(session, dict) and session.get("remoteId") and (
                    key == canonical or session.get("fileIdentity") == file_identity
                ):
                    count += 1
                    break
        except (OSError, ValueError, AttributeError):
            continue
    return count


def microsoft_edit_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query["action"] = "edit"
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )


def read_regular_file(root: Path, components: tuple[str, ...], maximum: int) -> tuple[bytes, os.stat_result]:
    file_fd = open_location(root, components)
    try:
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise MicrosoftBridgeError("Only files can be opened in Microsoft 365.", 400, "not_a_file")
        if info.st_size > maximum:
            raise MicrosoftBridgeError(
                f"This file is larger than the temporary Microsoft limit of {maximum // (1024 * 1024)} MB.",
                413,
                "file_too_large",
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(1024 * 1024, maximum - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise MicrosoftBridgeError("The file grew beyond the temporary Microsoft limit.", 413, "file_too_large")
            chunks.append(chunk)
        return b"".join(chunks), info
    finally:
        os.close(file_fd)


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PlexPointFolderIcons/1.0"
    sys_version = ""

    def log_message(self, _format: str, *_args: object) -> None:
        # Paths and cookies stay out of the journal.
        return

    def _send(self, status_code: int, body: bytes = b"", content_type: str = "text/plain; charset=utf-8", extra: dict[str, str] | None = None) -> None:
        headers = dict(extra or {})
        response_body = body
        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "").lower()
        compressible = content_type.lower().startswith(
            ("application/javascript", "application/json", "text/")
        )
        if (
            status_code not in (204, 304)
            and len(body) >= 1024
            and accepts_gzip
            and compressible
            and "Content-Encoding" not in headers
        ):
            response_body = gzip.compress(body, compresslevel=6)
            headers["Content-Encoding"] = "gzip"
            vary = headers.get("Vary", "")
            if "accept-encoding" not in vary.lower():
                headers["Vary"] = f"{vary}, Accept-Encoding".strip(", ")
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(response_body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD" and response_body:
            self.wfile.write(response_body)

    def _auth_headers(self) -> dict[str, str]:
        result: dict[str, str] = {"Accept": "application/json", "Accept-Encoding": "identity"}
        for name in ("Cookie", "Authorization", "X-Auth"):
            value = self.headers.get(name)
            if value:
                result[name] = value
        return result

    def _authorize(self) -> tuple[str, dict[str, str], str] | None:
        forwarded = self._auth_headers()
        secret_material = "\n".join(forwarded.get(name, "") for name in ("Cookie", "Authorization", "X-Auth"))
        if not secret_material.strip():
            return None
        key = hashlib.sha256(secret_material.encode("utf-8")).hexdigest()
        now = time.monotonic()
        with _cache_lock:
            cached = _auth_cache.get(key)
            if cached and cached[0] > now:
                return key, cached[1], cached[2]
        connection = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=10)
        try:
            connection.request("GET", "/api/users?id=self", headers=forwarded)
            response = connection.getresponse()
            payload = response.read(1024 * 1024)
            if response.status != 200:
                return None
            user = json.loads(payload.decode("utf-8"))
            scopes = {
                str(item.get("name", "")): str(item.get("scope", "/"))
                for item in user.get("scopes", [])
                if isinstance(item, dict) and item.get("name")
            }
            if not scopes:
                return None
            username = str(user.get("username") or user.get("id") or "authenticated-user")
            with _cache_lock:
                _auth_cache[key] = (now + AUTH_TTL_SECONDS, scopes, username)
            return key, scopes, username
        except (OSError, ValueError, json.JSONDecodeError, http.client.HTTPException):
            return None
        finally:
            connection.close()

    def _manifest(self, query: dict[str, list[str]]) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        auth_key, scopes, username = authorized
        source = query.get("source", [""])[0]
        relative = query.get("path", [""])[0]
        if source == "Home" and relative == "" and source in scopes and scope_allows(scopes[source], ()):
            map_stamp, mapping = load_storage_map()
            root = Path("/")  # Unused for the virtual aggregate root.
            within_root: tuple[str, ...] = ()
            requested_parts: tuple[str, ...] = ()
        else:
            resolved = resolve_location(source, relative, scopes)
            if resolved is None:
                self._send(403, json_bytes({"error": "folder is outside your access"}), "application/json")
                return
            root, within_root, requested_parts, map_stamp = resolved
        cache_key = (auth_key, source, "/".join(requested_parts), map_stamp)
        now = time.monotonic()
        with _cache_lock:
            cached = _manifest_cache.get(cache_key)
            if cached and cached[0] > now:
                self._send(200, cached[1], "application/json", {"Cache-Control": "private, no-store"})
                return
        icons: dict[str, dict[str, str]] = {}
        storage: dict[str, dict[str, int | str]] = {}
        material_icons = load_folder_icons(username)
        hidden_names: list[str] = []
        try:
            if source == "Home" and not requested_parts:
                candidates: list[tuple[str, Path, tuple[str, ...]]] = [
                    (name, candidate_root, ()) for name, candidate_root in mapping.items()
                ]
                for name, candidate_root in mapping.items():
                    if filesystem_hidden(candidate_root, (), username, name):
                        hidden_names.append(name)
                    category = "folder" if name in HOME_FOLDER_NAMES else "drive"
                    entry: dict[str, int | str] = {"category": category}
                    if category == "drive":
                        try:
                            usage = os.statvfs(candidate_root)
                            entry["total"] = usage.f_blocks * usage.f_frsize
                            entry["free"] = usage.f_bavail * usage.f_frsize
                        except OSError:
                            pass
                    storage[name] = entry
            else:
                candidates = []
                parent_fd = open_directory(root, within_root)
                try:
                    with os.scandir(parent_fd) as entries:
                        for entry in entries:
                            if entry.name in (RECYCLE_DIRECTORY_NAME, HISTORY_DIRECTORY_NAME):
                                continue
                            canonical = canonical_location(source, requested_parts, (*within_root, entry.name))
                            if canonical and filesystem_hidden(root, (*within_root, entry.name), username, canonical):
                                hidden_names.append(entry.name)
                            if entry.is_dir(follow_symlinks=False):
                                candidates.append((entry.name, root, (*within_root, entry.name)))
                finally:
                    os.close(parent_fd)
            for name, candidate_root, candidate_parts in candidates:
                folder_fd: int | None = None
                icon_fd: int | None = None
                try:
                    canonical = name if source == "Home" and not requested_parts else canonical_location(source, requested_parts, candidate_parts)
                    material_icon = material_icons.get(canonical or "")
                    if material_icon:
                        icons[name] = {"material": material_icon}
                        continue
                    folder_fd = open_directory(candidate_root, candidate_parts)
                    opened = open_valid_icon(folder_fd)
                    if opened is None:
                        continue
                    icon_fd, info, _content_type = opened
                    folder_relative = "/".join((*requested_parts, name))
                    icon_url = "/__foldericons/icon?" + urllib.parse.urlencode(
                        {"source": source, "path": folder_relative, "v": icon_version(info)}
                    )
                    icons[name] = {"url": icon_url}
                except OSError:
                    continue
                finally:
                    if icon_fd is not None:
                        os.close(icon_fd)
                    if folder_fd is not None:
                        os.close(folder_fd)
        except (OSError, ValueError):
            self._send(404, json_bytes({"error": "folder unavailable"}), "application/json")
            return
        if source == "Home" and requested_parts == ("Connected devices",):
            for device in connected_devices(scopes):
                icons.setdefault(device["name"], {"url":device["iconUrl"]})
        if source == "Home" and not requested_parts:
            storage.get("Connected devices", {}).update(category="folder")
        body = json_bytes({
            "source": source,
            "path": relative,
            "icons": icons,
            "storage": storage,
            "hidden": sorted(set(hidden_names)),
        })
        with _cache_lock:
            _manifest_cache[cache_key] = (now + MANIFEST_TTL_SECONDS, body)
        self._send(200, body, "application/json", {"Cache-Control": "private, no-store"})

    def _icon(self, query: dict[str, list[str]]) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, b"authentication required")
            return
        _auth_key, scopes, _username = authorized
        source = query.get("source", [""])[0]
        relative = query.get("path", [""])[0]
        resolved = resolve_location(source, relative, scopes)
        if resolved is None:
            self._send(403, b"folder is outside your access")
            return
        root, within_root, _parts, _map_stamp = resolved
        folder_fd: int | None = None
        icon_fd: int | None = None
        try:
            folder_fd = open_directory(root, within_root)
            opened = open_valid_icon(folder_fd)
        except OSError:
            opened = None
        if opened is None:
            if folder_fd is not None:
                os.close(folder_fd)
            self._send(404, b"icon unavailable")
            return
        icon_fd, info, content_type = opened
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(info.st_size))
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("ETag", '"' + icon_version(info) + '"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command == "HEAD":
            os.close(icon_fd)
            os.close(folder_fd)
            return
        try:
            while chunk := os.read(icon_fd, 128 * 1024):
                self.wfile.write(chunk)
        except (OSError, BrokenPipeError, ConnectionResetError):
            return
        finally:
            os.close(icon_fd)
            os.close(folder_fd)

    def _client(self) -> None:
        try:
            info = CLIENT_JS.stat()
            body = CLIENT_JS.read_bytes()
        except OSError:
            self._send(503, b"folder icon client unavailable")
            return
        etag = f'W/"{info.st_mtime_ns:x}-{info.st_size:x}"'
        headers = {
            "Cache-Control": "private, max-age=0, must-revalidate",
            "ETag": etag,
            "X-Robots-Tag": "noindex",
        }
        if self.headers.get("If-None-Match", "") == etag:
            self._send(304, b"", "application/javascript; charset=utf-8", headers)
            return
        self._send(
            200,
            body,
            "application/javascript; charset=utf-8",
            headers,
        )

    def _recycle_bin_icon(self, query: dict[str, list[str]]) -> None:
        if self._authorize() is None:
            self._send(401, b"authentication required")
            return
        state = query.get("state", ["empty"])[0]
        path = RECYCLE_ICON_FILES.get(state, RECYCLE_ICON_FILES["empty"])
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > 256 * 1024:
                raise OSError("invalid recycle bin icon")
            body = path.read_bytes()
        except OSError:
            self._send(503, b"recycle bin icon unavailable")
            return
        etag = f'W/"{info.st_mtime_ns:x}-{info.st_size:x}"'
        headers = {
            "Cache-Control": "private, max-age=86400",
            "ETag": etag,
            "X-Robots-Tag": "noindex",
        }
        if self.headers.get("If-None-Match", "") == etag:
            self._send(304, b"", "image/png", headers)
            return
        self._send(200, body, "image/png", headers)

    def _home_layout(self) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        _auth_key, _scopes, username = authorized
        identity = hashlib.sha256(username.encode("utf-8")).hexdigest()
        layout_path = HOME_LAYOUT_DIR / f"{identity}.json"
        _stamp, mapping = load_storage_map()
        drive_names = set(mapping).difference(HOME_FOLDER_NAMES)
        if self.command in ("GET", "HEAD"):
            try:
                value = json.loads(layout_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                value = {}
            layout = {
                "drives": normalize_order(value.get("drives"), drive_names) if isinstance(value, dict) else [],
                "folders": normalize_order(value.get("folders")) if isinstance(value, dict) else [],
            }
            self._send(200, json_bytes(layout), "application/json", {"Cache-Control": "private, no-store"})
            return
        length_header = self.headers.get("Content-Length", "")
        try:
            length = int(length_header)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_LAYOUT_BYTES:
            self._send(400, json_bytes({"error": "invalid layout request"}), "application/json")
            return
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            self._send(400, json_bytes({"error": "invalid layout"}), "application/json")
            return
        if not isinstance(value, dict):
            self._send(400, json_bytes({"error": "invalid layout"}), "application/json")
            return
        layout = {
            "drives": normalize_order(value.get("drives"), drive_names),
            "folders": normalize_order(value.get("folders")),
        }
        try:
            HOME_LAYOUT_DIR.mkdir(parents=True, exist_ok=True, mode=0o750)
            temporary = HOME_LAYOUT_DIR / f".{identity}.{os.getpid()}.{threading.get_ident()}.tmp"
            temporary.write_bytes(json_bytes(layout))
            os.chmod(temporary, 0o600)
            os.replace(temporary, layout_path)
        except OSError:
            self._send(500, json_bytes({"error": "layout could not be saved"}), "application/json")
            return
        self._send(200, json_bytes(layout), "application/json", {"Cache-Control": "private, no-store"})

    def _json_body(self, maximum: int) -> object | None:
        length_header = self.headers.get("Content-Length", "")
        try:
            length = int(length_header)
        except ValueError:
            return None
        if length < 0 or length > maximum:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return None

    def _resolved_item(
        self, source: str, relative: str, scopes: dict[str, str]
    ) -> tuple[Path, tuple[str, ...], tuple[str, ...], int, str] | None:
        normalized = relative.strip("/")
        resolved = resolve_location(source, normalized, scopes)
        if resolved is None:
            return None
        root, within_root, requested_parts, map_stamp = resolved
        canonical = canonical_location(source, requested_parts, within_root)
        if canonical is None:
            return None
        try:
            stat_location(root, within_root)
        except OSError:
            return None
        return root, within_root, requested_parts, map_stamp, canonical

    def _hidden_item(self, query: dict[str, list[str]]) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        _auth_key, scopes, username = authorized
        if self.command in ("GET", "HEAD"):
            source = query.get("source", [""])[0]
            relative = query.get("path", [""])[0]
            requested_hidden: bool | None = None
        else:
            value = self._json_body(MAX_LAYOUT_BYTES)
            if not isinstance(value, dict) or not isinstance(value.get("hidden"), bool):
                self._send(400, json_bytes({"error": "invalid hidden item request"}), "application/json")
                return
            source = str(value.get("source", ""))
            relative = str(value.get("path", ""))
            requested_hidden = value["hidden"]
        resolved = self._resolved_item(source, relative, scopes)
        if resolved is None:
            self._send(404, json_bytes({"error": "item unavailable"}), "application/json")
            return
        root, within_root, _requested_parts, _map_stamp, canonical = resolved
        if requested_hidden is None:
            hidden = filesystem_hidden(root, within_root, username, canonical)
        else:
            try:
                hidden = set_dos_hidden_location(root, within_root, requested_hidden)
                with _hidden_lock:
                    items = load_hidden_items(username)
                    items.discard(canonical)
                    save_hidden_items(username, items)
                with _cache_lock:
                    _manifest_cache.clear()
            except OSError:
                self._send(500, json_bytes({"error": "Windows Hidden attribute could not be saved"}), "application/json")
                return
        self._send(200, json_bytes({"source": source, "path": relative, "hidden": hidden}), "application/json", {"Cache-Control": "private, no-store"})

    def _material_icons(self) -> None:
        if self._authorize() is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        try:
            body = MATERIAL_ICONS_FILE.read_bytes()
            if len(body) > MAX_HIDDEN_BYTES:
                raise OSError("icon list too large")
        except OSError:
            self._send(503, json_bytes({"error": "icon list unavailable"}), "application/json")
            return
        self._send(200, body, "application/json", {"Cache-Control": "private, max-age=86400"})

    def _folder_icon(self, query: dict[str, list[str]]) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        _auth_key, scopes, username = authorized
        if self.command in ("GET", "HEAD"):
            source = query.get("source", [""])[0]
            relative = query.get("path", [""])[0]
            requested_icon: str | None = None
        else:
            value = self._json_body(MAX_LAYOUT_BYTES)
            if not isinstance(value, dict) or not isinstance(value.get("icon"), str):
                self._send(400, json_bytes({"error": "invalid folder icon request"}), "application/json")
                return
            source = str(value.get("source", ""))
            relative = str(value.get("path", ""))
            requested_icon = value["icon"].strip()
            if requested_icon and not re.fullmatch(r"[a-z0-9_]{1,128}", requested_icon):
                self._send(400, json_bytes({"error": "invalid material icon name"}), "application/json")
                return
        resolved = self._resolved_item(source, relative, scopes)
        if resolved is None:
            self._send(404, json_bytes({"error": "folder unavailable"}), "application/json")
            return
        root, within_root, _requested_parts, _map_stamp, canonical = resolved
        try:
            if not stat.S_ISDIR(stat_location(root, within_root).st_mode):
                raise OSError("not a directory")
        except OSError:
            self._send(400, json_bytes({"error": "only folders can use folder icons"}), "application/json")
            return
        if requested_icon is None:
            icon = load_folder_icons(username).get(canonical, "")
        else:
            try:
                with _folder_icons_lock:
                    icons = load_folder_icons(username)
                    if requested_icon:
                        icons[canonical] = requested_icon
                    else:
                        icons.pop(canonical, None)
                    save_folder_icons(username, icons)
                icon = requested_icon
                with _cache_lock:
                    _manifest_cache.clear()
            except OSError:
                self._send(500, json_bytes({"error": "folder icon could not be saved"}), "application/json")
                return
        self._send(200, json_bytes({"source": source, "path": relative, "icon": icon}), "application/json", {"Cache-Control": "private, no-store"})

    def _item_info(self, query: dict[str, list[str]]) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        auth_key, scopes, username = authorized
        source = query.get("source", [""])[0]
        relative = query.get("path", [""])[0]
        resolved = self._resolved_item(source, relative, scopes)
        if resolved is None:
            self._send(404, json_bytes({"error": "item unavailable"}), "application/json")
            return
        root, within_root, requested_parts, _map_stamp, canonical = resolved
        storage_name = requested_parts[0] if source == "Home" else source
        is_drive = not within_root and storage_name not in HOME_FOLDER_NAMES
        job_key = (auth_key, canonical)
        now = time.monotonic()
        with _cache_lock:
            job = _info_jobs.get(job_key)
            if job and job.get("status") == "ready" and float(job.get("expires", 0)) <= now:
                _info_jobs.pop(job_key, None)
                job = None
        if job and job.get("status") == "ready":
            result = dict(job.get("result", {}))
            result["hidden"] = filesystem_hidden(root, within_root, username, canonical)
            result["folderIcon"] = load_folder_icons(username).get(canonical, "")
            result["status"] = "ready"
            self._send(200, json_bytes(result), "application/json", {"Cache-Control": "private, no-store"})
            return
        if job and job.get("status") == "error":
            self._send(404, json_bytes({"error": "size could not be calculated"}), "application/json")
            return
        if job and job.get("status") == "calculating":
            self._send(202, json_bytes({"status": "calculating", "retryAfterMs": 700}), "application/json", {"Cache-Control": "private, no-store"})
            return

        try:
            item_stat = stat_location(root, within_root)
        except OSError:
            self._send(404, json_bytes({"error": "item unavailable"}), "application/json")
            return
        quick = is_drive or not stat.S_ISDIR(item_stat.st_mode)
        if quick:
            try:
                result = calculate_item_info(root, within_root, is_drive)
            except OSError:
                self._send(404, json_bytes({"error": "size could not be calculated"}), "application/json")
                return
            with _cache_lock:
                _info_jobs[job_key] = {"status": "ready", "result": result, "expires": now + INFO_CACHE_SECONDS}
            result = dict(result)
            result["hidden"] = filesystem_hidden(root, within_root, username, canonical)
            result["folderIcon"] = load_folder_icons(username).get(canonical, "")
            result["status"] = "ready"
            self._send(200, json_bytes(result), "application/json", {"Cache-Control": "private, no-store"})
            return

        with _cache_lock:
            _info_jobs[job_key] = {"status": "calculating", "expires": now + INFO_CACHE_SECONDS}

        def calculate() -> None:
            try:
                result = calculate_item_info(root, within_root, False)
                value: dict[str, object] = {
                    "status": "ready",
                    "result": result,
                    "expires": time.monotonic() + INFO_CACHE_SECONDS,
                }
            except OSError:
                value = {"status": "error", "expires": time.monotonic() + 10}
            with _cache_lock:
                _info_jobs[job_key] = value

        threading.Thread(target=calculate, name="folder-size", daemon=True).start()
        self._send(202, json_bytes({"status": "calculating", "retryAfterMs": 700}), "application/json", {"Cache-Control": "private, no-store"})

    def _search(self, query: dict[str, list[str]]) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        auth_key, scopes, username = authorized
        source = query.get("source", [""])[0]
        relative = query.get("path", [""])[0]
        search_query = query.get("q", [""])[0].strip()[:1024]
        recursive = query.get("recursive", ["1"])[0] != "0"
        show_hidden = query.get("showHidden", ["0"])[0] == "1"
        if not search_query:
            self._send(
                200,
                json_bytes({
                    "status": "ready", "items": [], "count": 0,
                    "scanned": 0, "truncated": False, "elapsedMs": 0,
                }),
                "application/json",
                {"Cache-Control": "private, no-store"},
            )
            return

        roots: list[tuple[str, Path, tuple[str, ...], tuple[str, ...]]] = []
        if source == "Home" and relative == "":
            if source not in scopes:
                self._send(403, json_bytes({"error": "folder is outside your access"}), "application/json")
                return
            _stamp, mapping = load_storage_map()
            for storage_name, root in mapping.items():
                requested = (storage_name,)
                if scope_allows(scopes[source], requested):
                    roots.append((source, root, (), requested))
        else:
            resolved = resolve_location(source, relative, scopes)
            if resolved is None:
                self._send(403, json_bytes({"error": "folder is outside your access"}), "application/json")
                return
            root, within_root, requested_parts, _stamp = resolved
            try:
                if not stat.S_ISDIR(stat_location(root, within_root).st_mode):
                    raise OSError("not a directory")
            except OSError:
                self._send(404, json_bytes({"error": "folder unavailable"}), "application/json")
                return
            roots.append((source, root, within_root, requested_parts))

        job_key = (auth_key, source, relative, search_query, recursive, show_hidden)
        now = time.monotonic()
        with _cache_lock:
            for old_key, old_job in list(_search_jobs.items()):
                if float(old_job.get("expires", 0)) <= now:
                    _search_jobs.pop(old_key, None)
            job = _search_jobs.get(job_key)

        if job and job.get("status") == "ready":
            self._send(
                200,
                json_bytes(job.get("result", {})),
                "application/json",
                {"Cache-Control": "private, no-store"},
            )
            return
        if job and job.get("status") == "error":
            self._send(500, json_bytes({"error": "search could not be completed"}), "application/json")
            return
        if job and job.get("status") == "searching":
            self._send(
                202,
                json_bytes({"status": "searching", "retryAfterMs": 220}),
                "application/json",
                {"Cache-Control": "private, no-store"},
            )
            return

        with _cache_lock:
            _search_jobs[job_key] = {
                "status": "searching",
                "expires": now + SEARCH_MAX_SECONDS + SEARCH_CACHE_SECONDS,
            }

        def calculate() -> None:
            try:
                result = search_tree(roots, search_query, recursive, show_hidden, username)
                value: dict[str, object] = {
                    "status": "ready",
                    "result": result,
                    "expires": time.monotonic() + SEARCH_CACHE_SECONDS,
                }
            except (OSError, ValueError):
                value = {"status": "error", "expires": time.monotonic() + 10}
            with _cache_lock:
                _search_jobs[job_key] = value

        threading.Thread(target=calculate, name="file-search", daemon=True).start()
        self._send(
            202,
            json_bytes({"status": "searching", "retryAfterMs": 220}),
            "application/json",
            {"Cache-Control": "private, no-store"},
        )

    def _has_permission(self, permission: str) -> bool:
        forwarded = self._auth_headers()
        connection = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=10)
        try:
            connection.request("GET", "/api/users?id=self", headers=forwarded)
            response = connection.getresponse()
            payload = response.read(1024 * 1024)
            if response.status != 200:
                return False
            user = json.loads(payload.decode("utf-8"))
            permissions = user.get("permissions", {})
            return bool(
                user.get("admin") is True
                or (isinstance(permissions, dict) and permissions.get(permission) is True)
            )
        except (OSError, ValueError, json.JSONDecodeError, http.client.HTTPException):
            return False
        finally:
            connection.close()

    def _operation_history(self) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        _auth_key, scopes, username = authorized
        if self.command in ("GET", "HEAD"):
            with _operation_lock:
                result = history_summary(load_operation_history(username))
            self._send(200, json_bytes(result), "application/json", {"Cache-Control": "private, no-store"})
            return
        if self.command != "POST":
            self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD, POST"})
            return
        if not self._has_permission("modify"):
            self._send(403, json_bytes({"error": "file modification is not permitted"}), "application/json")
            return
        value = self._json_body(MAX_LAYOUT_BYTES)
        action = str(value.get("action", "")) if isinstance(value, dict) else ""
        if action not in ("undo", "redo"):
            self._send(400, json_bytes({"error": "action must be undo or redo"}), "application/json")
            return
        try:
            result = change_operation_history(username, scopes, action)
        except FileExistsError:
            self._send(409, json_bytes({"error": "The original location already contains an item with that name."}), "application/json")
            return
        except FileNotFoundError:
            self._send(409, json_bytes({"error": "A file needed for this change is no longer available."}), "application/json")
            return
        except (OSError, ValueError, PermissionError) as error:
            self._send(409, json_bytes({"error": str(error) or "The change could not be applied."}), "application/json")
            return
        self._send(200, json_bytes(result), "application/json", {"Cache-Control": "private, no-store"})

    def _recycle_bin(self) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        _auth_key, scopes, username = authorized
        if self.command in ("GET", "HEAD"):
            items = list_recycle_items(username, scopes)
            self._send(
                200,
                json_bytes({"items": items, "count": len(items)}),
                "application/json",
                {"Cache-Control": "private, no-store"},
            )
            return
        if self.command not in ("POST", "DELETE"):
            self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD, POST, DELETE"})
            return
        if not self._has_permission("delete" if self.command == "DELETE" else "modify"):
            self._send(403, json_bytes({"error": "this file operation is not permitted"}), "application/json")
            return
        value = self._json_body(MAX_LAYOUT_BYTES)
        if not isinstance(value, dict):
            self._send(400, json_bytes({"error": "invalid recycle bin request"}), "application/json")
            return
        requested_ids = value.get("ids", [])
        if value.get("all") is True:
            wanted: set[str] | None = None
        elif isinstance(requested_ids, list):
            wanted = {str(item) for item in requested_ids if str(item)}
        else:
            wanted = set()
        available = list_recycle_items(username, scopes)
        selected = [item for item in available if wanted is None or str(item.get("id", "")) in wanted]
        if not selected:
            self._send(404, json_bytes({"error": "no matching recycled items"}), "application/json")
            return
        try:
            if self.command == "POST" and value.get("action") == "restore":
                for item in selected:
                    restore_recycle_item(username, scopes, item)
                record_operation(username, {
                    "kind": "restore",
                    "label": "restore " + (
                        str(selected[0].get("name", "item"))
                        if len(selected) == 1
                        else f"{len(selected)} items"
                    ),
                    "items": selected,
                })
                message = f"Restored {len(selected)} item{'s' if len(selected) != 1 else ''}."
            elif self.command == "DELETE":
                for item in selected:
                    permanently_delete_recycle_item(username, scopes, item)
                remove_recycle_items_from_history(
                    username,
                    {str(item.get("id", "")) for item in selected},
                )
                message = f"Permanently deleted {len(selected)} item{'s' if len(selected) != 1 else ''}."
            else:
                self._send(400, json_bytes({"error": "unsupported recycle bin action"}), "application/json")
                return
        except FileExistsError:
            self._send(409, json_bytes({"error": "The original location already contains an item with that name."}), "application/json")
            return
        except (OSError, ValueError, PermissionError) as error:
            self._send(409, json_bytes({"error": str(error) or "The recycle bin operation failed."}), "application/json")
            return
        self._send(200, json_bytes({"changed": True, "message": message}), "application/json", {"Cache-Control": "private, no-store"})

    def _resource_delete_to_recycle(self, parsed: urllib.parse.SplitResult) -> bool:
        resource_path = parsed.path.rstrip("/")
        if self.command != "DELETE" or resource_path not in ("/api/resources", "/api/resources/bulk"):
            return False
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return True
        if not self._has_permission("delete"):
            self._send(403, json_bytes({"error": "delete is not permitted"}), "application/json")
            return True
        _auth_key, scopes, username = authorized
        if resource_path == "/api/resources/bulk":
            value = self._json_body(MAX_OPERATION_HISTORY_BYTES)
            raw_items = value.get("items", []) if isinstance(value, dict) else value
            if not isinstance(raw_items, list) or not raw_items:
                self._send(400, json_bytes({"error": "bulk delete requires a list of items"}), "application/json")
                return True
            requests = [
                (str(item.get("source", "")), str(item.get("path", "")))
                for item in raw_items[:256]
                if isinstance(item, dict)
            ]
        else:
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            requests = [(query.get("source", [""])[0], query.get("path", [""])[0])]

        if not requests or any(not source or not str(relative).strip("/") for source, relative in requests):
            self._send(400, json_bytes({"error": "source and path are required for a recoverable delete"}), "application/json")
            return True
        recycled: list[dict[str, object]] = []
        failed: list[dict[str, object]] = []
        try:
            for source, relative in requests:
                try:
                    recycled.append(move_item_to_recycle(username, scopes, source, relative))
                except (OSError, ValueError, PermissionError) as error:
                    failed.append({
                        "source": source,
                        "path": relative,
                        "message": str(error) or "item could not be recycled",
                    })
            if recycled:
                label = (
                    f"delete {recycled[0].get('name', 'item')}"
                    if len(recycled) == 1
                    else f"delete {len(recycled)} items"
                )
                record_operation(username, {"kind": "delete", "label": label, "items": recycled})
        except (OSError, ValueError) as error:
            self._send(409, json_bytes({"error": str(error) or "items could not be recycled"}), "application/json")
            return True
        if not recycled:
            self._send(404, json_bytes({"succeeded": [], "failed": failed, "error": "No items could be recycled."}), "application/json")
            return True
        if resource_path == "/api/resources/bulk":
            succeeded = [
                {"source": item.get("source", ""), "path": item.get("path", "")}
                for item in recycled
            ]
            self._send(
                207 if failed else 200,
                json_bytes({"succeeded": succeeded, "failed": failed}),
                "application/json",
                {"Cache-Control": "private, no-store"},
            )
            return True
        item = recycled[0]
        self._send(
            200,
            json_bytes({"status": 200, "message": "Moved to Recycle Bin", "recycled": [item]}),
            "application/json",
            {"Cache-Control": "private, no-store"},
        )
        return True

    def _sidebar_link(self, query: dict[str, list[str]]) -> None:
        if self.command not in ("GET", "HEAD", "POST", "DELETE"):
            self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD, POST, DELETE"})
            return
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        _auth_key, scopes, _username = authorized
        if self.command in ("GET", "HEAD"):
            source = query.get("source", [""])[0]
            relative = query.get("path", [""])[0].strip("/")
            name = query.get("name", [""])[0].strip()[:256]
            icon = query.get("icon", ["folder"])[0].strip()[:128] or "folder"
        else:
            value = self._json_body(MAX_LAYOUT_BYTES)
            if not isinstance(value, dict):
                self._send(400, json_bytes({"error": "invalid Home shortcut request"}), "application/json")
                return
            source = str(value.get("source", ""))
            relative = str(value.get("path", "")).strip("/")
            name = str(value.get("name", "")).strip()[:256]
            icon = str(value.get("icon", "folder")).strip()[:128] or "folder"
        resolved = self._resolved_item(source, relative, scopes)
        if resolved is None or (self.command == "POST" and not name):
            self._send(404, json_bytes({"error": "folder unavailable"}), "application/json")
            return
        root, within_root, requested_parts, _map_stamp, _canonical = resolved
        try:
            if not stat.S_ISDIR(stat_location(root, within_root).st_mode):
                raise OSError("not a directory")
        except OSError:
            self._send(400, json_bytes({"error": "only folders can be added to Home"}), "application/json")
            return
        forwarded = self._auth_headers()
        connection = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=15)
        try:
            connection.request("GET", "/api/users?id=self", headers=forwarded)
            response = connection.getresponse()
            user_payload = response.read(2 * 1024 * 1024)
            if response.status != 200:
                self._send(response.status, json_bytes({"error": "user settings unavailable"}), "application/json")
                return
            user = json.loads(user_payload.decode("utf-8"))
            links = list(user.get("sidebarLinks", [])) if isinstance(user.get("sidebarLinks"), list) else []
            link_source = requested_parts[0] if source == "Home" and requested_parts and requested_parts[0] in scopes else source
            link_relative = "/".join(within_root) if link_source != source else relative.strip("/")
            target = "/" + link_relative.strip("/")
            if target != "/":
                target += "/"
            def matches(item: object) -> bool:
                return isinstance(item, dict) and item.get("sourceName") == link_source and str(item.get("target", "")).rstrip("/") == target.rstrip("/")

            linked = any(matches(item) for item in links)
            changed = False
            if self.command == "POST" and not linked:
                links.append({
                    "name": name,
                    "category": "source-minimal",
                    "target": target,
                    "icon": icon,
                    "sourceName": link_source,
                })
                linked = True
                changed = True
            elif self.command == "DELETE" and linked:
                links = [item for item in links if not matches(item)]
                linked = False
                changed = True
            if changed:
                user_id = urllib.parse.quote(str(user.get("id", "self")), safe="")
                body = json_bytes({"which": ["sidebarLinks"], "data": {"sidebarLinks": links}})
                headers = {**forwarded, "Content-Type": "application/json", "Content-Length": str(len(body))}
                connection.close()
                connection = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=15)
                connection.request("PUT", f"/api/users?id={user_id}", body=body, headers=headers)
                response = connection.getresponse()
                response.read(1024 * 1024)
                if response.status not in (200, 204):
                    self._send(response.status, json_bytes({"error": "sidebar link could not be saved"}), "application/json")
                    return
            self._send(200, json_bytes({"saved": True, "linked": linked, "changed": changed, "target": target}), "application/json", {"Cache-Control": "private, no-store"})
        except (OSError, ValueError, json.JSONDecodeError, http.client.HTTPException):
            self._send(502, json_bytes({"error": "sidebar link could not be saved"}), "application/json")
        finally:
            connection.close()

    def _microsoft_error(self, error: MicrosoftBridgeError) -> None:
        self._send(
            error.status,
            json_bytes({"error": str(error), "code": error.code}),
            "application/json",
            {"Cache-Control": "private, no-store"},
        )

    def _microsoft_status(self, query: dict[str, list[str]]) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        _auth_key, scopes, username = authorized
        config = load_microsoft_config()
        if config is None:
            self._send(
                200,
                json_bytes({"configured": False, "connected": False, "active": False}),
                "application/json",
                {"Cache-Control": "private, no-store"},
            )
            return

        account = load_microsoft_account(username)
        connected = bool(account.get("refreshToken"))
        if config.get("mode") == "rclone":
            try:
                microsoft_rclone_token(config, refresh=False)
                connected = True
            except MicrosoftBridgeError:
                connected = False
        sessions = account.get("sessions", {})
        active: dict[str, object] | None = None
        last_save = None
        source = query.get("source", [""])[0]
        relative = query.get("path", [""])[0]
        if source and relative:
            resolved = self._resolved_item(source, relative, scopes)
            if resolved is not None:
                canonical = resolved[4]
                last_save = account.get("lastSaves", {}).get(canonical)
                candidate = sessions.get(canonical) if isinstance(sessions, dict) else None
                if isinstance(candidate, dict):
                    active = {
                        "name": str(candidate.get("name", "")),
                        "app": str(candidate.get("app", "Microsoft 365")),
                        "webUrl": str(candidate.get("webUrl", "")),
                        "openedAt": candidate.get("openedAt", 0),
                        "savedBackAt": candidate.get("savedBackAt", 0),
                        "cleanupPending": bool(candidate.get("savedRemoteETag")),
                        "cleanupError": str(candidate.get("cleanupError", "")),
                        "autoCleanup": candidate.get("autoCleanup") is True,
                        "cleanupNextAttemptAt": candidate.get("cleanupNextAttemptAt", 0),
                        "autoSync": candidate.get("autoSync") is True,
                        "syncState": candidate.get("syncState", ""),
                        "syncError": candidate.get("syncError", ""),
                        "desktopUrl": candidate.get("desktopUrl", ""),
                    }
                    if candidate.get("syncState"):
                        active["cleanupPending"] = False
        self._send(
            200,
            json_bytes({
                "configured": True,
                "connected": connected,
                "connectionMode": config.get("mode", "entra"),
                "desktopAutoSync": True,
                "active": active or False,
                "lastSave": last_save,
            }),
            "application/json",
            {"Cache-Control": "private, no-store"},
        )

    def _microsoft_sessions(self) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        _key, scopes, username = authorized
        account = load_microsoft_account(username)
        sessions = account.get("sessions", {})
        receipts = account.get("lastSaves", {})
        items = []
        for canonical in set(sessions) | set(receipts):
            active = sessions.get(canonical)
            item = active or receipts.get(canonical)
            if not isinstance(item, dict):
                continue
            resolved = self._resolved_item(str(item.get("source", "")), str(item.get("path", "")), scopes)
            if resolved is None or resolved[4] != canonical:
                continue
            public = {key: item.get(key) for key in (
                "source", "path", "name", "app", "openedAt", "savedBackAt", "cleanupError", "autoCleanup", "cloudRemoved",
                "autoSync", "syncState", "syncError", "desktopUrl",
            )}
            public.update(active=bool(active), cleanupPending=bool(item.get("savedRemoteETag")) and not item.get("syncState"))
            if active:
                public["webUrl"] = item.get("webUrl", "")
            items.append(public)
        items.sort(key=lambda item: (not item["active"], -float(item.get("savedBackAt") or item.get("openedAt") or 0)))
        self._send(200, json_bytes({"items": items, "canModify": self._has_permission("modify")}), "application/json", {"Cache-Control": "private, no-store"})

    @microsoft_serialized
    def _microsoft_versions(self) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        _key, scopes, username = authorized
        if self.command == "POST" and not self._has_permission("modify"):
            self._send(403, json_bytes({"error": "Editing permission is required to restore a version."}), "application/json")
            return
        if self.command == "POST":
            value = self._json_body(MAX_LAYOUT_BYTES)
        else:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            value = {key: values[0] for key, values in query.items()}
        if not isinstance(value, dict):
            self._send(400, json_bytes({"error": "invalid version request"}), "application/json")
            return
        source, relative = str(value.get("source", "")), str(value.get("path", ""))
        resolved = self._resolved_item(source, relative, scopes)
        if resolved is None:
            self._send(404, json_bytes({"error": "file unavailable"}), "application/json")
            return
        root, parts, _requested, _stamp, canonical = resolved
        try:
            if self.command == "POST":
                account = load_microsoft_account(username)
                identity = hashlib.sha256(str(root.joinpath(*parts).resolve()).encode("utf-8")).hexdigest()
                if account.get("sessions", {}).get(canonical) or microsoft_other_editors(username, canonical, identity):
                    raise MicrosoftBridgeError("Save back the active Microsoft copies before restoring a local version.", 409, "active_copy")
                microsoft_restore_version(username, scopes, source, relative, str(value.get("id", "")), str(value.get("revision", "")))
                self._send(200, json_bytes({"restored": True, "message": "Version restored. The previous file is also available in version history."}), "application/json", {"Cache-Control": "private, no-store"})
                return
            info = stat_location(root, parts)
            versions = microsoft_file_versions(username, scopes, source, relative)
            self._send(200, json_bytes({"items": [{k: v for k, v in item.items() if k != "payload"} for item in versions],
                "revision": f"{info.st_mtime_ns}:{info.st_size}", "canModify": self._has_permission("modify")}), "application/json", {"Cache-Control": "private, no-store"})
        except MicrosoftBridgeError as error:
            self._microsoft_error(error)
        except OSError:
            self._send(500, json_bytes({"error": "Version history could not be accessed safely."}), "application/json")

    def _microsoft_device_start(self) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        _auth_key, _scopes, username = authorized
        config = load_microsoft_config()
        if config is None:
            self._send(
                503,
                json_bytes({
                    "error": "Microsoft integration still needs its application ID.",
                    "code": "not_configured",
                }),
                "application/json",
                {"Cache-Control": "private, no-store"},
            )
            return

        if config.get("mode") == "rclone":
            self._microsoft_error(MicrosoftBridgeError(
                "Microsoft is connected through the server. An administrator must reconnect the server's OneDrive connection; browser device sign-in is not available in this mode.",
                409, "server_reconnect_required",
            ))
            return

        tenant = urllib.parse.quote(str(config["tenant"]), safe="")
        body = urllib.parse.urlencode({
            "client_id": str(config["clientId"]),
            "scope": MICROSOFT_SCOPES,
        }).encode("utf-8")
        try:
            status, value = microsoft_http_json(
                "POST",
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode",
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                body=body,
            )
        except MicrosoftBridgeError as error:
            self._microsoft_error(error)
            return
        if status != 200 or not value.get("device_code") or not value.get("user_code"):
            self._send(
                502,
                json_bytes({
                    "error": microsoft_error_message(value, "Microsoft sign-in could not be started."),
                    "code": "device_start_failed",
                }),
                "application/json",
                {"Cache-Control": "private, no-store"},
            )
            return

        expires_in = max(60, int(value.get("expires_in", 900)))
        interval = max(2, int(value.get("interval", 5)))
        pending_key = microsoft_identity(username)
        with _microsoft_lock:
            _microsoft_pending[pending_key] = {
                "deviceCode": str(value["device_code"]),
                "expiresAt": time.time() + expires_in,
                "interval": interval,
                "nextPoll": 0.0,
            }
        self._send(
            200,
            json_bytes({
                "userCode": str(value["user_code"]),
                "verificationUri": str(
                    value.get("verification_uri") or
                    value.get("verification_url") or
                    "https://microsoft.com/devicelogin"
                ),
                "message": str(value.get("message") or "Enter this code to connect Microsoft 365."),
                "expiresIn": expires_in,
                "interval": interval,
            }),
            "application/json",
            {"Cache-Control": "private, no-store"},
        )

    @microsoft_serialized
    def _microsoft_device_poll(self) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        _auth_key, _scopes, username = authorized
        config = load_microsoft_config()
        if config is None:
            self._send(503, json_bytes({"error": "Microsoft integration is not configured.", "code": "not_configured"}), "application/json")
            return

        if config.get("mode") == "rclone":
            self._microsoft_error(MicrosoftBridgeError(
                "An administrator must reconnect the server's OneDrive connection.",
                409, "server_reconnect_required",
            ))
            return

        pending_key = microsoft_identity(username)
        with _microsoft_lock:
            pending = dict(_microsoft_pending.get(pending_key, {}))
        if not pending:
            self._send(409, json_bytes({"error": "Start Microsoft sign-in again.", "code": "no_pending_sign_in"}), "application/json")
            return
        now = time.time()
        if float(pending.get("expiresAt", 0)) <= now:
            with _microsoft_lock:
                _microsoft_pending.pop(pending_key, None)
            self._send(410, json_bytes({"error": "The Microsoft sign-in code expired.", "code": "expired"}), "application/json")
            return
        if float(pending.get("nextPoll", 0)) > now:
            retry = max(1, int(float(pending["nextPoll"]) - now + 0.5))
            self._send(202, json_bytes({"status": "pending", "retryAfter": retry}), "application/json", {"Cache-Control": "private, no-store"})
            return

        interval = max(2, int(pending.get("interval", 5)))
        with _microsoft_lock:
            current = _microsoft_pending.get(pending_key)
            if isinstance(current, dict):
                current["nextPoll"] = now + interval
        try:
            status, value = microsoft_token_request(
                config,
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": str(config["clientId"]),
                    "device_code": str(pending.get("deviceCode", "")),
                },
            )
        except MicrosoftBridgeError as error:
            self._microsoft_error(error)
            return

        oauth_error = str(value.get("error", ""))
        if status == 400 and oauth_error in ("authorization_pending", "slow_down"):
            if oauth_error == "slow_down":
                interval += 5
                with _microsoft_lock:
                    current = _microsoft_pending.get(pending_key)
                    if isinstance(current, dict):
                        current["interval"] = interval
                        current["nextPoll"] = now + interval
            self._send(202, json_bytes({"status": "pending", "retryAfter": interval}), "application/json", {"Cache-Control": "private, no-store"})
            return
        if status != 200 or not value.get("access_token") or not value.get("refresh_token"):
            if oauth_error in ("authorization_declined", "expired_token", "bad_verification_code"):
                with _microsoft_lock:
                    _microsoft_pending.pop(pending_key, None)
            self._send(
                400,
                json_bytes({
                    "error": microsoft_error_message(value, "Microsoft sign-in was not completed."),
                    "code": oauth_error or "sign_in_failed",
                }),
                "application/json",
                {"Cache-Control": "private, no-store"},
            )
            return

        account = load_microsoft_account(username)
        account["accessToken"] = str(value["access_token"])
        account["refreshToken"] = str(value["refresh_token"])
        account["expiresAt"] = time.time() + max(60, int(value.get("expires_in", 3600)))
        account["scope"] = str(value.get("scope") or "")
        with _microsoft_lock:
            save_microsoft_account(username, account)
            _microsoft_pending.pop(pending_key, None)
        self._send(200, json_bytes({"status": "connected", "connected": True}), "application/json", {"Cache-Control": "private, no-store"})

    @microsoft_serialized
    def _microsoft_open(self) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        _auth_key, scopes, username = authorized
        if not self._has_permission("modify"):
            self._send(403, json_bytes({"error": "Editing permission is required to use Microsoft web editing.", "code": "permission_denied"}), "application/json")
            return
        config = load_microsoft_config()
        if config is None:
            self._send(503, json_bytes({"error": "Microsoft integration is not configured.", "code": "not_configured"}), "application/json")
            return
        value = self._json_body(MAX_LAYOUT_BYTES)
        if not isinstance(value, dict):
            self._send(400, json_bytes({"error": "invalid Microsoft open request"}), "application/json")
            return
        source = str(value.get("source", ""))
        relative = str(value.get("path", ""))
        resolved = self._resolved_item(source, relative, scopes)
        if resolved is None:
            self._send(404, json_bytes({"error": "file unavailable"}), "application/json")
            return
        root, within_root, _requested_parts, _map_stamp, canonical = resolved
        name = within_root[-1] if within_root else Path(root).name
        extension = Path(name).suffix.lower()
        desktop = value.get("desktop") is True
        if desktop and extension not in MICROSOFT_DESKTOP_EXTENSIONS:
            self._microsoft_error(MicrosoftBridgeError("Desktop AutoSave is available for DOCX, XLSX, XLSM, XLSB and PPTX files. Other formats cannot use this automatic workflow.", 400, "unsupported_type"))
            return
        if extension in MICROSOFT_CONVERSION_EXTENSIONS:
            self._microsoft_error(MicrosoftBridgeError(
                f"Save a separate {MICROSOFT_CONVERSION_EXTENSIONS[extension]} copy in the desktop app, upload it to FilePoint, then open that copy. Conversion in Microsoft can create a different cloud file which this bridge cannot safely save back. Keep the original, especially if it contains macros.",
                409, "conversion_required"))
            return
        if extension not in MICROSOFT_OFFICE_EXTENSIONS:
            self._send(400, json_bytes({"error": "This file type is not supported by Microsoft 365 for the web.", "code": "unsupported_type"}), "application/json")
            return

        account = load_microsoft_account(username)
        sessions = account.setdefault("sessions", {})
        if not isinstance(sessions, dict):
            sessions = {}
            account["sessions"] = sessions
        existing = sessions.get(canonical)
        if isinstance(existing, dict) and existing.get("webUrl"):
            if desktop:
                try:
                    access_token, account = microsoft_access_token(username, config, account)
                    existing["desktopUrl"] = microsoft_desktop_url(access_token, str(existing["remoteId"]), str(existing["app"]))
                    microsoft_enable_autosync(existing, scopes, root, within_root)
                except (MicrosoftBridgeError, OSError) as error:
                    self._microsoft_error(error if isinstance(error, MicrosoftBridgeError) else MicrosoftBridgeError(str(error)))
                    return
            # Reopening is a new editing intent: cancel background deletion.
            existing["autoCleanup"] = False
            existing["cleanupNextAttemptAt"] = 0
            save_microsoft_account(username, account)
            self._send(
                200,
                json_bytes({
                    "active": True,
                    "webUrl": str(existing["webUrl"]),
                    "name": name,
                    "app": str(existing.get("app", "Microsoft 365")),
                    "cleanupPending": bool(existing.get("savedRemoteETag")),
                    "cleanupError": str(existing.get("cleanupError", "")),
                    "desktopUrl": existing.get("desktopUrl", ""),
                    "autoSync": existing.get("autoSync") is True,
                    "syncState": existing.get("syncState", ""),
                    "syncError": existing.get("syncError", ""),
                    "savedBackAt": existing.get("savedBackAt", 0),
                }),
                "application/json",
                {"Cache-Control": "private, no-store"},
            )
            return

        file_identity = hashlib.sha256(str(root.joinpath(*within_root).resolve()).encode("utf-8")).hexdigest()
        if value.get("allowConcurrent") is not True and microsoft_other_editors(username, canonical, file_identity):
            self._microsoft_error(MicrosoftBridgeError(
                "Another FilePoint account has a Microsoft copy of this file open. Separate copies can conflict when saved back. Open your own copy anyway?",
                409, "other_editor",
            ))
            return

        try:
            access_token, account = microsoft_access_token(username, config, account)
            maximum = int(config["maxFileBytes"])
            content, info = read_regular_file(root, within_root, maximum)
            active_bytes = sum(
                int(item.get("remoteSize", 0) or 0)
                for item in sessions.values()
                if isinstance(item, dict)
            )
            if active_bytes + len(content) > int(config["maxTotalBytes"]):
                raise MicrosoftBridgeError(
                    "The FilePoint temporary OneDrive area reached its storage limit. Save back an open file first.",
                    409,
                    "temporary_limit",
                )

            status, app_root = microsoft_graph_json(access_token, "GET", "/me/drive/special/approot")
            if status != 200 or not app_root.get("id"):
                raise MicrosoftBridgeError(microsoft_error_message(app_root, "The temporary OneDrive folder could not be opened."))

            # A shared server connection must not reuse another user's copy,
            # or overwrite an orphan left by a previous interrupted upload.
            remote_name = microsoft_remote_name(f"{username}\n{canonical}\n{secrets.token_hex(12)}", name)
            parent_id = urllib.parse.quote(str(app_root["id"]), safe="")
            encoded_name = urllib.parse.quote(remote_name, safe="")
            status, uploaded = microsoft_graph_json(
                access_token,
                "PUT",
                f"/me/drive/items/{parent_id}:/{encoded_name}:/content",
                body=content,
                content_type="application/octet-stream",
                timeout=180,
            )
            if status not in (200, 201) or not uploaded.get("id") or not uploaded.get("webUrl"):
                raise MicrosoftBridgeError(microsoft_error_message(uploaded, "The file could not be copied to Microsoft 365."))
        except MicrosoftBridgeError as error:
            self._microsoft_error(error)
            return

        app_name = MICROSOFT_OFFICE_APPS[extension]
        web_url = microsoft_edit_url(str(uploaded["webUrl"]))
        sessions[canonical] = {
            "source": source,
            "path": relative,
            "name": name,
            "app": app_name,
            "remoteId": str(uploaded["id"]),
            "remoteName": remote_name,
            "remoteSize": int(uploaded.get("size", len(content)) or len(content)),
            "webUrl": web_url,
            "openedAt": time.time(),
            "originalMtimeNs": int(info.st_mtime_ns),
            "originalSize": int(info.st_size),
            "fileIdentity": file_identity,
        }
        with _microsoft_lock:
            save_microsoft_account(username, account)
        if desktop:
            try:
                session = sessions[canonical]
                session["desktopUrl"] = microsoft_desktop_url(access_token, str(session["remoteId"]), app_name)
                session["syncRemoteETag"] = str(uploaded.get("eTag") or "")
                microsoft_enable_autosync(session, scopes, root, within_root)
                save_microsoft_account(username, account)
            except (MicrosoftBridgeError, OSError) as error:
                self._microsoft_error(error if isinstance(error, MicrosoftBridgeError) else MicrosoftBridgeError(str(error)))
                return
        self._send(
            200,
            json_bytes({"active": True, "webUrl": web_url, "name": name, "app": app_name,
                        "desktopUrl": sessions[canonical].get("desktopUrl", ""),
                        "autoSync": sessions[canonical].get("autoSync") is True,
                        "syncState": sessions[canonical].get("syncState", "")}),
            "application/json",
            {"Cache-Control": "private, no-store"},
        )

    @microsoft_serialized
    def _microsoft_save_back(self) -> None:
        authorized = self._authorize()
        if authorized is None:
            self._send(401, json_bytes({"error": "authentication required"}), "application/json")
            return
        _auth_key, scopes, username = authorized
        if not self._has_permission("modify"):
            self._send(403, json_bytes({"error": "Editing permission is required to save back or clean up a Microsoft copy.", "code": "permission_denied"}), "application/json")
            return
        config = load_microsoft_config()
        if config is None:
            self._send(503, json_bytes({"error": "Microsoft integration is not configured.", "code": "not_configured"}), "application/json")
            return
        value = self._json_body(MAX_LAYOUT_BYTES)
        if not isinstance(value, dict):
            self._send(400, json_bytes({"error": "invalid save-back request"}), "application/json")
            return
        source = str(value.get("source", ""))
        relative = str(value.get("path", ""))
        force = value.get("force") is True
        cleanup_only = value.get("cleanupOnly") is True
        resolved = self._resolved_item(source, relative, scopes)
        if resolved is None:
            self._send(404, json_bytes({"error": "original file unavailable"}), "application/json")
            return
        root, within_root, _requested_parts, _map_stamp, canonical = resolved
        account = load_microsoft_account(username)
        sessions = account.get("sessions", {})
        session = sessions.get(canonical) if isinstance(sessions, dict) else None
        if not isinstance(session, dict) or not session.get("remoteId"):
            self._send(404, json_bytes({"error": "There is no temporary Microsoft copy for this file.", "code": "no_active_copy"}), "application/json")
            return
        if session.get("syncState") and value.get("finishSync") is not True:
            self._microsoft_error(MicrosoftBridgeError("This document syncs automatically. Close the desktop editor and use Finish syncing before removing its cloud copy.", 409, "autosync_active"))
            return

        if not cleanup_only and Path(within_root[-1]).suffix.lower() in MICROSOFT_CONVERSION_EXTENSIONS:
            self._microsoft_error(MicrosoftBridgeError("This format may have been converted to a separate Microsoft file. Download the edited modern-format copy from Microsoft and upload it to FilePoint. Automatic save-back and cleanup have been stopped to protect your changes.", 409, "conversion_required"))
            return

        edit_history_record: dict[str, object] | None = None
        edit_history_committed = False
        try:
            if cleanup_only:
                # Cleanup never downloads or rewrites the local document. Old
                # sessions without a verified version must be saved back first.
                saved_etag = str(session.get("savedRemoteETag", ""))
                if not saved_etag:
                    raise MicrosoftBridgeError("Save the latest Microsoft copy back before retrying cleanup.", 409, "save_required")
                access_token, account = microsoft_access_token(username, config, account)
                cloud_removed, delete_result = microsoft_remove_temporary_copy(access_token, str(session["remoteId"]), saved_etag)
                if cloud_removed:
                    sessions.pop(canonical, None)
                else:
                    session["cleanupAttempts"] = 0
                    microsoft_schedule_cleanup(session, delete_result)
                microsoft_save_receipt(account, canonical, session, cloud_removed)
                with _microsoft_lock:
                    save_microsoft_account(username, account)
                self._send(200, json_bytes({
                    "saved": True, "cloudRemoved": cloud_removed,
                    "savedBackAt": session.get("savedBackAt", 0),
                    "cleanupPending": not cloud_removed,
                    "autoCleanup": not cloud_removed and session.get("autoCleanup") is True,
                    "cleanupError": session.get("cleanupError", "") if not cloud_removed else "",
                    "webUrl": session.get("webUrl", ""), "app": session.get("app", "Microsoft 365"),
                    "message": "Temporary OneDrive copy removed. The FilePoint file was not changed." if cloud_removed else "The OneDrive copy is still safe in Microsoft. " + str(session["cleanupError"]),
                }), "application/json", {"Cache-Control": "private, no-store"})
                return
            access_token, account = microsoft_access_token(username, config, account)
            written, saved_etag = microsoft_copy_to_local(
                username, scopes, source, relative, root, within_root, session, config, access_token, force)

            # Persist the successful local save before trying cloud cleanup.
            # Even a timeout/restart must leave a version-bound retry available.
            refreshed = stat_location(root, within_root)
            session["originalMtimeNs"] = int(refreshed.st_mtime_ns)
            session["originalSize"] = int(refreshed.st_size)
            session["remoteSize"] = written
            session["savedRemoteETag"] = saved_etag
            session["savedBackAt"] = time.time()
            session["autoSync"] = False
            session.pop("syncState", None)
            session.pop("syncScopes", None)
            session["cleanupAttempts"] = 0
            session["autoCleanup"] = True
            session["cleanupNextAttemptAt"] = time.time() + 30
            session["cleanupError"] = "Saved locally; temporary OneDrive copy is awaiting cleanup."
            microsoft_save_receipt(account, canonical, session, False)
            with _microsoft_lock:
                save_microsoft_account(username, account)
            cloud_removed, delete_result = microsoft_remove_temporary_copy(
                access_token,
                str(session["remoteId"]),
                saved_etag,
            )
            if cloud_removed:
                sessions.pop(canonical, None)
            else:
                microsoft_schedule_cleanup(session, delete_result)
            microsoft_save_receipt(account, canonical, session, cloud_removed)
            with _microsoft_lock:
                save_microsoft_account(username, account)
        except MicrosoftBridgeError as error:
            if edit_history_record is not None and not edit_history_committed:
                discard_operation_artifacts(username, edit_history_record)
            self._microsoft_error(error)
            return
        except OSError:
            if edit_history_record is not None and not edit_history_committed:
                discard_operation_artifacts(username, edit_history_record)
            self._send(500, json_bytes({"error": "The edited file could not be saved safely.", "code": "save_failed"}), "application/json")
            return

        self._send(
            200,
            json_bytes({
                "saved": True,
                "savedBackAt": session.get("savedBackAt", 0),
                "cloudRemoved": cloud_removed,
                "cleanupPending": not cloud_removed,
                "autoCleanup": not cloud_removed and session.get("autoCleanup") is True,
                "cleanupError": session.get("cleanupError", "") if not cloud_removed else "",
                "webUrl": session.get("webUrl", ""),
                "app": session.get("app", "Microsoft 365"),
                "bytes": written,
                "message": "Saved back to FilePoint and removed from OneDrive." if cloud_removed else "Saved back to FilePoint, but the temporary OneDrive copy still needs cleanup.",
            }),
            "application/json",
            {"Cache-Control": "private, no-store"},
        )

    def _native_files(self, query: dict[str, list[str]]) -> None:
        def value(name):
            return query.get(name, [""])[0]

        def integer(name, minimum, maximum):
            raw = value(name)
            if not re.fullmatch(r"[0-9]{1,16}", raw) or not minimum <= int(raw) <= maximum:
                raise WriteError(400, f"Invalid {name}.")
            return int(raw)

        def request(method, path, headers):
            connection = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=10)
            try:
                connection.request(method, path, headers=headers)
                response = connection.getresponse()
                return response.status, response.getheader("DAV"), response.read(1024 * 1024)
            finally:
                connection.close()

        def account():
            status, _dav, body = request("GET", "/api/users?id=self", {"Authorization": bearer})
            if status != 200:
                raise WriteError(401 if status in (401, 403) else 502, "Could not verify the FilePoint account.")
            user = json.loads(body)
            scopes = {item["name"]: item.get("scope", "/") for item in user.get("scopes", [])}
            return scopes, user.get("permissions", {})

        def authorized_parent(source, path, mode):
            scopes, permissions = account()
            if source not in enabled or source not in scopes or permissions.get("modify" if mode == "edit" else "create") is not True:
                raise WriteError(403, "Your FilePoint account cannot write to this source.")
            relative = safe_components(path[1:]) if path.startswith("/") else None
            scope = safe_components(scopes[source].strip("/"))
            if not relative or scope is None or any(
                part.casefold() in (RECYCLE_DIRECTORY_NAME, HISTORY_DIRECTORY_NAME, "desktop.ini")
                or part.casefold().startswith((".filepoint-icon-", ".filepoint-commit-"))
                or len(part.encode("utf-8")) > 255 for part in (*scope, *relative)
            ):
                raise WriteError(400, "Invalid destination.")
            _stamp, mapping = load_storage_map()
            root = mapping.get(source)
            if root is None:
                raise WriteError(404, "The storage source is unavailable.")

            # Quantum's WebDAV handler checks the exact scope-relative path even on OPTIONS.
            # This enforces upstream file-access rules for new as well as existing targets.
            dav_url = "/dav/" + "/".join(urllib.parse.quote(part, safe="") for part in (source, *relative))
            basic = base64.b64encode(("FilePoint:" + bearer.removeprefix("Bearer ")).encode("ascii")).decode("ascii")
            status, dav, _body = request("OPTIONS", dav_url, {"Authorization": "Basic " + basic})
            if status != 200 or not dav:
                raise WriteError(403, "The server denied access to this path.")
            return open_directory(root, (*scope, *relative[:-1]))

        def reply(status, body):
            self._send(status, json_bytes(body), "application/json", {"Cache-Control": "private, no-store"})

        try:
            if self.command != "PUT" and (self.headers.get("Content-Length", "0") != "0" or self.headers.get("Transfer-Encoding")):
                raise WriteError(400, "This write operation does not accept a request body.")
            try:
                configured = json.loads(NATIVE_WRITE_CONFIG.read_text(encoding="utf-8"))
                enabled = {source for source in configured if isinstance(source, str) and source != "Home"} if isinstance(configured, list) else set()
            except (OSError, ValueError):
                enabled = set()
            if not enabled:
                raise WriteError(404, "Native file writes are disabled on this server.")
            bearer = self.headers.get("Authorization", "")
            if not re.fullmatch(r"Bearer [A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", bearer):
                raise WriteError(401, "A FilePoint sign-in is required.")
            owner = hashlib.sha256(bearer.encode("ascii")).hexdigest()
            if self.command in ("GET", "HEAD"):
                scopes, permissions = account()
                sources = sorted(enabled.intersection(scopes)) if permissions.get("create") is True or permissions.get("modify") is True else []
                reply(200, {"protocol": 1, "sources": sources})
                return
            if self.command == "POST":
                source, path, mode = value("source"), value("path"), value("mode")
                if mode not in ("create", "edit", "directory", "rename"):
                    raise WriteError(400, "Invalid write mode.")
                parent = authorized_parent(source, path, "edit" if mode == "rename" else mode)
                try:
                    name = path.rsplit("/", 1)[-1]
                    if mode == "directory":
                        os.mkdir(name, mode=0o775, dir_fd=parent)
                        reply(201, {"created": True})
                    elif mode == "rename":
                        destination = value("destination")
                        replace = value("replace") == "true"
                        destination_parent = authorized_parent(source, destination, "edit" if replace else "create")
                        try:
                            reply(200, native_writes.rename(parent, name, destination_parent,
                                destination.rsplit("/", 1)[-1], replace))
                        finally:
                            os.close(destination_parent)
                    else:
                        upload = native_writes.begin(owner, source, path, parent, name, mode, value("revision"))
                        parent = None  # The upload now owns the directory handle.
                        reply(201, upload)
                finally:
                    if parent is not None:
                        os.close(parent)
                return
            identifier = value("upload")
            if not re.fullmatch(r"[a-f0-9]{48}", identifier):
                raise WriteError(400, "Invalid upload identifier.")
            if self.command == "PUT":
                raw_length = self.headers.get("Content-Length", "")
                if not re.fullmatch(r"[0-9]{1,8}", raw_length) or not 0 < int(raw_length) <= MAX_CHUNK:
                    raise WriteError(413, "Invalid upload chunk length.")
                length = int(raw_length)
                offset = integer("offset", 0, 64 * 1024**3)
                data = self.rfile.read(length)
                if len(data) != length:
                    raise WriteError(400, "The upload chunk was interrupted.")
                reply(200, native_writes.append(identifier, owner, offset, data))
            elif self.command == "PATCH":
                reply(200, native_writes.commit(identifier, owner, integer("length", 0, 64 * 1024**3), authorized_parent))
            elif self.command == "DELETE":
                native_writes.cancel(identifier, owner)
                reply(200, {"cancelled": True})
            else:
                raise WriteError(405, "Method not allowed.")
        except WriteError as error:
            self.close_connection = True
            reply(error.status, {"error": str(error)})
        except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException) as error:
            self.close_connection = True
            status = 409 if isinstance(error, FileExistsError) else 404 if isinstance(error, FileNotFoundError) else 507 if getattr(error, "errno", None) == errno.ENOSPC else 502
            reply(status, {"error": "The server could not complete the file operation."})

    def _handle_foldericons(self) -> bool:
        parsed = urllib.parse.urlsplit(self.path)
        if not parsed.path.startswith("/__foldericons/"):
            return False
        if parsed.path == "/__foldericons/native-files":
            self._native_files(urllib.parse.parse_qs(parsed.query, keep_blank_values=True))
            return True
        if parsed.path == "/__foldericons/health":
            self._send(200, b"ok\n", extra={"Cache-Control": "no-store"})
            return True
        if parsed.path == "/__foldericons/client.js":
            self._client()
            return True
        if parsed.path == "/__foldericons/connected-storage.js":
            if self.command not in ("GET", "HEAD"):
                self._send(405, b"method not allowed", extra={"Allow":"GET, HEAD"})
            else:
                self._send(200, (CLIENT_JS.parent / "connected_storage_client.js").read_bytes(), "application/javascript", {"Cache-Control":"no-cache"})
            return True
        if parsed.path == "/__foldericons/device-icon":
            kind = urllib.parse.parse_qs(parsed.query).get('kind',['device'])[0]
            if self.command not in ("GET", "HEAD"):
                self._send(405, b"method not allowed", extra={"Allow":"GET, HEAD"})
            elif kind not in DEVICE_ICON_KINDS:
                self._send(404,b"not found")
            else:
                self._send(200,(CLIENT_JS.parent / 'assets' / 'devices' / (kind+'.ico')).read_bytes(), 'image/x-icon', {'Cache-Control':'public, max-age=86400'})
            return True
        if parsed.path == "/__foldericons/recycle-bin-icon":
            if self.command not in ("GET", "HEAD"):
                self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD"})
            else:
                self._recycle_bin_icon(
                    urllib.parse.parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)
                )
            return True
        if parsed.path == "/__foldericons/home-layout":
            if self.command not in ("GET", "HEAD", "PUT"):
                self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD, PUT"})
            else:
                self._home_layout()
            return True
        if parsed.path == "/__foldericons/hidden":
            if self.command not in ("GET", "HEAD", "PUT"):
                self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD, PUT"})
            else:
                self._hidden_item(urllib.parse.parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False))
            return True
        if parsed.path == "/__foldericons/folder-icon":
            if self.command not in ("GET", "HEAD", "PUT"):
                self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD, PUT"})
            else:
                self._folder_icon(urllib.parse.parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False))
            return True
        if parsed.path == "/__foldericons/material-icons":
            if self.command not in ("GET", "HEAD"):
                self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD"})
            else:
                self._material_icons()
            return True
        if parsed.path == "/__foldericons/devices":
            if self.command not in ("GET", "HEAD"):
                self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD"})
            else:
                authorized = self._authorize()
                if authorized is None:
                    self._send(401, json_bytes({"error":"authentication required"}), "application/json")
                else:
                    self._send(200, json_bytes({"devices":connected_devices(authorized[1])}), "application/json", {"Cache-Control":"private, no-store"})
            return True
        if parsed.path == "/__foldericons/info":
            if self.command not in ("GET", "HEAD"):
                self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD"})
            else:
                self._item_info(urllib.parse.parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False))
            return True
        if parsed.path == "/__foldericons/search":
            if self.command not in ("GET", "HEAD"):
                self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD"})
            else:
                self._search(urllib.parse.parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False))
            return True
        if parsed.path == "/__foldericons/history":
            self._operation_history()
            return True
        if parsed.path == "/__foldericons/recycle-bin":
            self._recycle_bin()
            return True
        if parsed.path == "/__foldericons/sidebar-link":
            self._sidebar_link(urllib.parse.parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False))
            return True
        if parsed.path == "/__foldericons/microsoft/status":
            if self.command not in ("GET", "HEAD"):
                self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD"})
            else:
                self._microsoft_status(
                    urllib.parse.parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)
                )
            return True
        if parsed.path == "/__foldericons/microsoft/device/start":
            if self.command != "POST":
                self._send(405, b"method not allowed", extra={"Allow": "POST"})
            else:
                self._microsoft_device_start()
            return True
        if parsed.path == "/__foldericons/microsoft/sessions":
            if self.command not in ("GET", "HEAD"):
                self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD"})
            else:
                self._microsoft_sessions()
            return True
        if parsed.path == "/__foldericons/microsoft/versions":
            if self.command not in ("GET", "HEAD", "POST"):
                self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD, POST"})
            else:
                self._microsoft_versions()
            return True
        if parsed.path == "/__foldericons/microsoft/device/poll":
            if self.command != "POST":
                self._send(405, b"method not allowed", extra={"Allow": "POST"})
            else:
                self._microsoft_device_poll()
            return True
        if parsed.path == "/__foldericons/microsoft/open":
            if self.command != "POST":
                self._send(405, b"method not allowed", extra={"Allow": "POST"})
            else:
                self._microsoft_open()
            return True
        if parsed.path == "/__foldericons/microsoft/save-back":
            if self.command != "POST":
                self._send(405, b"method not allowed", extra={"Allow": "POST"})
            else:
                self._microsoft_save_back()
            return True
        if self.command not in ("GET", "HEAD"):
            self._send(405, b"method not allowed", extra={"Allow": "GET, HEAD"})
            return True
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)
        if parsed.path == "/__foldericons/icons":
            self._manifest(query)
        elif parsed.path == "/__foldericons/icon":
            self._icon(query)
        else:
            self._send(404, b"not found")
        return True

    def _upgrade(self) -> None:
        upstream = socket.create_connection((UPSTREAM_HOST, UPSTREAM_PORT), timeout=15)
        try:
            request = [f"{self.command} {self.path} {self.request_version}\r\n"]
            for name, value in self.headers.items():
                if name.lower() == "host":
                    value = f"{UPSTREAM_HOST}:{UPSTREAM_PORT}"
                request.append(f"{name}: {value}\r\n")
            request.append("\r\n")
            upstream.sendall("".join(request).encode("iso-8859-1"))
            sockets = [self.connection, upstream]
            while True:
                readable, _, _ = select.select(sockets, [], [], 90)
                if not readable:
                    continue
                for current in readable:
                    data = current.recv(128 * 1024)
                    if not data:
                        return
                    (upstream if current is self.connection else self.connection).sendall(data)
        except (OSError, ConnectionResetError):
            return
        finally:
            upstream.close()
            self.close_connection = True

    def _proxy(self) -> None:
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self._upgrade()
            return
        parsed = urllib.parse.urlsplit(self.path)
        if self._resource_delete_to_recycle(parsed):
            return
        content_length = self.headers.get("Content-Length")
        buffered_request: bytes | None = None
        operation_record: dict[str, object] | None = None
        operation_user = ""
        operation_scopes: dict[str, str] = {}
        operation_finalized = False

        if (
            self.command == "PATCH"
            and parsed.path.rstrip("/") == "/api/resources"
            and content_length
        ):
            try:
                body_size = int(content_length)
                if 0 <= body_size <= MAX_OPERATION_HISTORY_BYTES:
                    buffered_request = self.rfile.read(body_size)
            except (OSError, ValueError):
                buffered_request = None

        if self.command in ("POST", "PUT", "PATCH") and parsed.path.rstrip("/") == "/api/resources":
            authorized = self._authorize()
            if authorized is not None:
                _auth_key, operation_scopes, operation_user = authorized
                try:
                    operation_record = prepare_resource_proxy_operation(
                        operation_user,
                        operation_scopes,
                        self.command,
                        parsed,
                        buffered_request,
                    )
                except (OSError, ValueError, PermissionError):
                    operation_record = None
        connection = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=90)
        try:
            connection.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            accepts_html = "text/html" in self.headers.get("Accept", "").lower()
            upstream_encoding = (
                "identity"
                if self.command in ("GET", "HEAD") and accepts_html
                else self.headers.get("Accept-Encoding", "identity")
            )
            for name, value in self.headers.items():
                lowered = name.lower()
                if lowered in HOP_BY_HOP or lowered in (
                    "host",
                    "accept-encoding",
                    "expect",
                    "x-forwarded-host",
                    "x-forwarded-proto",
                ):
                    continue
                connection.putheader(name, value)
            connection.putheader("Host", f"{UPSTREAM_HOST}:{UPSTREAM_PORT}")
            connection.putheader("Accept-Encoding", upstream_encoding)
            connection.putheader("X-Forwarded-Host", self.headers.get("Host", f"{LISTEN_HOST}:{LISTEN_PORT}"))
            forwarded_proto = self.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
            if forwarded_proto not in ("http", "https"):
                forwarded_proto = "http"
            connection.putheader("X-Forwarded-Proto", forwarded_proto)
            connection.endheaders()
            if buffered_request is not None:
                connection.send(buffered_request)
            elif content_length:
                remaining = int(content_length)
                while remaining:
                    chunk = self.rfile.read(min(128 * 1024, remaining))
                    if not chunk:
                        break
                    connection.send(chunk)
                    remaining -= len(chunk)
            response = connection.getresponse()
            finalize_resource_proxy_operation(
                operation_user,
                operation_scopes,
                operation_record,
                response.status in (200, 201, 204, 207),
            )
            operation_finalized = True
            content_type = response.getheader("Content-Type", "")
            inject = response.status == 200 and "text/html" in content_type.lower() and self.command != "HEAD"
            upstream_length = response.getheader("Content-Length")
            try:
                upstream_size = int(upstream_length or "0")
            except ValueError:
                upstream_size = 0
            accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "").lower()
            compressible = content_type.lower().startswith(
                ("application/javascript", "application/json", "application/xml", "text/")
            )
            compress_upstream = (
                self.command != "HEAD"
                and response.status not in (204, 304)
                and not response.getheader("Content-Encoding")
                and accepts_gzip
                and compressible
                and (
                    1024 <= upstream_size <= 16 * 1024 * 1024
                    or (upstream_size == 0 and self.path.startswith("/public/static/"))
                )
            )
            if inject or compress_upstream:
                body = response.read()
                if inject:
                    marker = b"</head>"
                    script = b'<script defer src="/__foldericons/client.js"></script><script defer src="/__foldericons/connected-storage.js"></script>'
                    if marker in body and script not in body:
                        body = body.replace(marker, CRITICAL_CANVAS_STYLE + script + marker, 1)
                use_gzip = accepts_gzip and compressible and len(body) >= 1024
                if use_gzip:
                    body = gzip.compress(body, compresslevel=6)
                self.send_response(response.status, response.reason)
                vary = ""
                for name, value in response.getheaders():
                    lowered = name.lower()
                    if lowered in HOP_BY_HOP or lowered in ("content-length", "content-encoding", "vary"):
                        continue
                    if inject and lowered == "etag":
                        continue
                    self.send_header(name, value)
                vary = response.getheader("Vary", "")
                if use_gzip:
                    self.send_header("Content-Encoding", "gzip")
                    if "accept-encoding" not in vary.lower():
                        vary = f"{vary}, Accept-Encoding".strip(", ")
                if vary:
                    self.send_header("Vary", vary)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(response.status, response.reason)
            for name, value in response.getheaders():
                if name.lower() not in HOP_BY_HOP:
                    self.send_header(name, value)
            if not upstream_length:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            if self.command != "HEAD":
                while chunk := response.read(128 * 1024):
                    self.wfile.write(chunk)
        except (OSError, ValueError, http.client.HTTPException, BrokenPipeError, ConnectionResetError):
            if operation_record is not None and not operation_finalized:
                finalize_resource_proxy_operation(
                    operation_user,
                    operation_scopes,
                    operation_record,
                    False,
                )
            if not self.wfile.closed:
                try:
                    self._send(502, b"Files service temporarily unavailable")
                except (OSError, BrokenPipeError):
                    pass
        finally:
            connection.close()

    def do_GET(self) -> None:
        if not self._handle_foldericons():
            self._proxy()

    def do_HEAD(self) -> None:
        if not self._handle_foldericons():
            self._proxy()

    def do_POST(self) -> None:
        if not self._handle_foldericons():
            self._proxy()

    def do_PUT(self) -> None:
        if not self._handle_foldericons():
            self._proxy()

    def do_PATCH(self) -> None:
        if not self._handle_foldericons():
            self._proxy()

    def do_DELETE(self) -> None:
        if not self._handle_foldericons():
            self._proxy()

    def do_OPTIONS(self) -> None:
        if not self._handle_foldericons():
            self._proxy()


if __name__ == "__main__":
    with ProxyServer((LISTEN_HOST, LISTEN_PORT), Handler) as server:
        print(f"Folder icons proxy listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
        cleanup_stop = threading.Event()
        threading.Thread(target=microsoft_cleanup_worker, args=(cleanup_stop,), name="microsoft-cleanup", daemon=True).start()
        threading.Thread(target=native_upload_cleanup, args=(cleanup_stop,), name="native-upload-cleanup", daemon=True).start()
        try:
            server.serve_forever(poll_interval=0.5)
        finally:
            cleanup_stop.set()
