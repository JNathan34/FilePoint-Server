from pathlib import Path
import subprocess
from storage_devices import parse_mountinfo
mounts=parse_mountinfo(Path('/proc/self/mountinfo').read_text())
connections={m['device'].split(':')[1] for m in mounts if m['filesystem'] in {'fuse.jmtpfs','fuse.simple-mtpfs','fuse.go-mtpfs'}}
for connection in connections:
    path=Path('/sys/fs/fuse/connections')/connection/'abort'
    if path.exists():
        path.write_text('1\n')
        print('Released phone FUSE connection',connection,flush=True)
subprocess.run(['systemctl','stop','--no-block','filepoint-storage'])
subprocess.run(['systemctl','kill','-s','KILL','filepoint-storage'])
print('Discovery stopped',flush=True)