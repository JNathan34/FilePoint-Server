"""Replace only FilePoint-created staging mounts with independent mount roots."""
import subprocess
from pathlib import Path
from storage_devices import parse_mountinfo
from storage_broker import ensure_root

def run(args, check=True):
    return subprocess.run(args,check=check,capture_output=True,text=True,timeout=45)

run(['systemctl','stop','filepoint-storage'])
run(['docker','stop','filepoint-android'],False)
roots = [prefix + '/' + name for prefix in ['/media','/DATA/.media','/var/lib/casaos_data/.media']
         for name in ['FilePoint-Devices','FilePoint-Phones']]
# Explicit paths only, no filesystem data deletion. Original USB mounts are
# outside these roots and are never unmounted by this repair.
for root in roots:
    for attempt in range(40):
        current = [m for m in parse_mountinfo(Path('/proc/self/mountinfo').read_text())
                   if m['path'] == root or m['path'].startswith(root + '/')]
        if not current:
            break
        run(['mount','--make-rprivate',root],False)
        run(['umount','--recursive','--lazy',root],False)
    else:
        raise RuntimeError('Could not remove staging mounts at ' + root)
ensure_root()
run(['systemctl','start','filepoint-storage'])
run(['docker','compose','-p','compose-642808ab626ea60e','-f',
     '/var/lib/casaos/apps/compose-642808ab626ea60e/docker-compose.yml',
     'up','-d','--no-deps','--force-recreate','files'])
run(['systemctl','restart','plexpoint-foldericons'])
run(['docker','compose','-f',str(Path(__file__).parent/'android/compose.yml'),
     'up','-d','--force-recreate'])
print('Isolated storage mounts ready')
