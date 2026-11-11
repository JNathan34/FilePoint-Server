#!/usr/bin/env python3
"""Mirror OS-mounted portable volumes into FilePoint's shared mount root."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

from storage_devices import portable_devices, parse_mountinfo, clean_label

BASE = Path(__file__).resolve().parent.parent
ROOT = Path('/media/FilePoint-Devices')
STATE = BASE / 'connected-storage.json'
ALIASES = BASE / 'connected-storage-aliases.json'
log = logging.getLogger('filepoint-storage')


def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=15).stdout


def atomic_json(path, value):
    content = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists() and path.read_text() == content:
        return
    temporary = path.with_suffix('.tmp')
    temporary.write_text(content)
    os.chmod(temporary, 0o644)
    temporary.replace(path)


def ensure_root():
    mounts = {m['path']:m for m in parse_mountinfo(Path('/proc/self/mountinfo').read_text())}
    for path in [ROOT, Path('/media/FilePoint-Phones')]:
        path.mkdir(mode=0o755, exist_ok=True)
        if str(path) not in mounts:
            command(['mount', '-t', 'tmpfs', '-o', 'size=1m,mode=0755,nosuid,nodev', 'filepoint-storage', str(path)])
        elif mounts[str(path)]['filesystem'] != 'tmpfs':
            raise RuntimeError('Storage staging root must be an isolated tmpfs mount')
        command(['mount', '--make-rshared', str(path)])


def alias_for(device, aliases):
    if device['id'] in aliases:
        return aliases[device['id']]
    name = clean_label(device['label'], 'Portable storage').strip('. ')
    if not name:
        name = 'Portable storage'
    if name in aliases.values():
        name += ' ' + device['id'][-6:]
    aliases[device['id']] = name
    return name


def validate_plan(devices, mounts):
    # Fail closed before mounting anything, even if discovery regresses.
    mirrors = [m for m in mounts if Path(m['path']).parent == ROOT]
    phones = [d for d in devices if d['kind'] == 'phone']
    if len(devices) > 64 or len(mirrors) > 64 or len(phones) > 4:
        raise RuntimeError('Connected storage mount limit reached; refusing new mounts')
    if len({d['id'] for d in devices}) != len(devices):
        raise RuntimeError('Duplicate device identities; refusing new mounts')
    for device in phones:
        source = device.get('mountPath')
        if not source or Path(source).parent != Path('/media/FilePoint-Phones'):
            raise RuntimeError('Phone source is not a canonical phone mount')


def reconcile():
    blocks = json.loads(command(['lsblk', '-J', '-b', '-o',
        'NAME,TYPE,TRAN,RM,HOTPLUG,MODEL,SERIAL,FSTYPE,UUID,PARTUUID,PARTTYPE,MAJ:MIN,LABEL,SIZE,RO']))
    mount_text = Path('/proc/self/mountinfo').read_text()
    mapping = json.loads((BASE / 'storage-map.json').read_text())
    devices = portable_devices(blocks, mount_text, mapping.values())
    validate_plan(devices, parse_mountinfo(mount_text))
    aliases = json.loads(ALIASES.read_text()) if ALIASES.exists() else {}
    mounts = {m['path']:m for m in parse_mountinfo(mount_text)}
    desired = set()
    published = []
    for device in devices:
        name = alias_for(device, aliases)
        target = ROOT / name
        # Only direct children with server-generated names can become mirrors.
        if target.parent != ROOT or (str(target) not in mounts and target.is_symlink()):
            continue
        desired.add(str(target))
        source = device.pop('mountPath')
        if not source and str(target) in mounts:
            command(['umount', '-l', str(target)])
            try:
                target.rmdir()
            except OSError:
                pass
        if source and source in mounts:
            existing = mounts.get(str(target))
            if existing and (existing['device'], existing['source']) != (mounts[source]['device'], mounts[source]['source']):
                command(['umount', '-l', str(target)])
                existing = None
            try:
                if not existing:
                    target.mkdir(mode=0o555, exist_ok=True)
                    command(['mount', '--bind', source, str(target)])
                    # Prevent mirrors propagating back into the original volume.
                    command(['mount', '--make-private', str(target)])
                # Inspect kernel mount metadata, never synchronous FUSE getattr.
                actual = next((m for m in parse_mountinfo(Path('/proc/self/mountinfo').read_text()) if m['path'] == str(target)), None)
                if not actual or actual['device'] != mounts[source]['device']:
                    raise OSError('Mirror does not reference the connected volume')
                if device['kind'] != 'phone':
                    usage = os.statvfs(target)
                    device.update(total=usage.f_blocks * usage.f_frsize, free=usage.f_bavail * usage.f_frsize)
                else:
                    try:
                        stats = subprocess.run(['stat','-f','-c','%b %a %S',str(target)],
                                               capture_output=True,text=True,timeout=5,check=True)
                        total, free, unit = map(int,stats.stdout.split())
                        device.update(total=total*unit,free=free*unit)
                    except (ValueError, OSError, subprocess.SubprocessError):
                        pass
                device['status'] = 'ready'
            except (OSError, subprocess.SubprocessError) as exc:
                log.warning('Could not expose %s: %s', device['id'], exc)
                device['status'] = 'unavailable'
        device.update(path='Connected devices/' + name, source='Home', name=name)
        published.append(device)
    # Only unmount our direct mirror entries. Never delete anything on a volume.
    for path in list(mounts):
        p = Path(path)
        if p.parent == ROOT and path not in desired:
            command(['umount', '-l', path])
    for child in ROOT.iterdir():
        if str(child) not in desired and not child.is_symlink() and not os.path.ismount(child):
            try:
                child.rmdir()  # Empty mountpoint only; deliberately not recursive.
            except OSError:
                pass
    atomic_json(ALIASES, aliases)
    previous = json.loads(STATE.read_text()).get('devices',[]) if STATE.exists() else []
    before = {(d['id'],d['status']) for d in previous}
    after = {(d['id'],d['status']) for d in published}
    if before != after:
        log.info('Device changes: removed=%s added=%s', sorted(before-after), sorted(after-before))
    atomic_json(STATE, {'updatedAt':time.time(), 'devices':published})


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    ensure_root()
    if '--prepare' in sys.argv:
        sys.exit(0)
    while True:
        try:
            reconcile()
        except Exception:
            log.exception('Storage discovery failed; retrying')
        time.sleep(3)
