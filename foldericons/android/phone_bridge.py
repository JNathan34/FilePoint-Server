"""Mount attached, unlocked MTP devices; never change the phone's USB mode."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import time
import signal
import threading

ROOT = Path('/phones')
active = {}
retry = {}
stopping = threading.Event()
signal.signal(signal.SIGTERM, lambda *_: stopping.set())
signal.signal(signal.SIGINT, lambda *_: stopping.set())


def scan():
    found = subprocess.run(['jmtpfs','-l'],capture_output=True,text=True,timeout=12)
    if found.returncode != 0:
        raise RuntimeError('MTP discovery failed; retain existing devices until retry')
    result = {}
    for line in found.stdout.splitlines():
        match = re.match(r'^\s*(\d+),\s*(\d+),\s*(0x[0-9a-fA-F]+),\s*(0x[0-9a-fA-F]+),\s*(.*)',line)
        if not match:
            continue
        bus, number = int(match[1]), int(match[2])
        label = match[5].split(',')[0].strip() or 'Android phone'
        serial = ''
        for usb in Path('/sys/bus/usb/devices').glob('*'):
            try:
                if int((usb/'busnum').read_text()) == bus and int((usb/'devnum').read_text()) == number:
                    serial = (usb/'serial').read_text().strip() if (usb/'serial').exists() else ''
                    label = (usb/'product').read_text().strip() if (usb/'product').exists() else label
                    break
            except (OSError, ValueError):
                continue
        label = re.sub(r'[^\w .()-]', ' ', label).strip('. ')[:70] or 'Android phone'
        key = hashlib.sha256((serial or f'{bus}:{number}:{label}').encode()).hexdigest()[:8]
        result[key] = (bus,number,label + ' ' + key)
    return result


def detach(key):
    process, path, _ = active.pop(key)
    subprocess.run(['fusermount','-uz',str(path)],capture_output=True,timeout=5)
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
    try:
        path.rmdir()
    except OSError:
        pass


while not stopping.is_set():
    try:
        found = scan()
        for key, (process,path,identity) in list(active.items()):
            if key not in found or process.poll() is not None or found[key][:2] != identity:
                detach(key)
        if len(found) > 4:
            raise RuntimeError('Phone limit reached; refusing additional mounts')
        for key,(bus,number,name) in found.items():
            if key in active or time.monotonic() < retry.get(key,0):
                continue
            path = ROOT/name
            # Mount-table lookup cannot block on an unresponsive FUSE device.
            mounted = any(line.split()[4] == str(path).replace(' ', r'\040') for line in Path('/proc/self/mountinfo').read_text().splitlines())
            if mounted:
                subprocess.run(['fusermount','-uz',str(path)],capture_output=True,timeout=5)
            path.mkdir(exist_ok=True)
            process = subprocess.Popen(['jmtpfs',f'-device={bus},{number}','-f','-o','allow_other',str(path)])
            active[key] = (process,path,(bus,number))
            retry[key] = time.monotonic() + 20
    except Exception as exc:
        print('Android scan retry:',type(exc).__name__,flush=True)
    stopping.wait(5)

for key in list(active):
    try:
        detach(key)
    except Exception as exc:
        print('Phone detach:',type(exc).__name__,flush=True)
