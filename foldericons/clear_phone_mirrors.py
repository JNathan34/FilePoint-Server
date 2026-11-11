from pathlib import Path
import subprocess,json,time,shutil
from storage_devices import parse_mountinfo
base=Path(__file__).resolve().parent.parent
for name in ['connected-storage.json','connected-storage-aliases.json']:
    shutil.copy2(base/name,base/'backups'/(name+'.recovery-'+str(int(time.time()))))
state=json.loads((base/'connected-storage.json').read_text())
keep={d['id'] for d in state.get('devices',[]) if d.get('kind')!='phone'}
aliases=json.loads((base/'connected-storage-aliases.json').read_text())
(base/'connected-storage-aliases.json').write_text(json.dumps({k:v for k,v in aliases.items() if k in keep}))
(base/'connected-storage.json').write_text(json.dumps({'updatedAt':time.time(),'devices':[]}))
roots=[prefix+'/'+name for prefix in ['/media','/DATA/.media','/var/lib/casaos_data/.media'] for name in ['FilePoint-Devices','FilePoint-Phones']]
for root in roots:
    current=[m for m in parse_mountinfo(Path('/proc/self/mountinfo').read_text()) if m['path']==root or m['path'].startswith(root+'/')]
    print(root,len(current),flush=True)
    if current:
        subprocess.run(['mount','--make-rprivate',root],timeout=120)
        subprocess.run(['umount','--recursive','--lazy',root],timeout=120)
print('Generated mounts cleared; original device mounts untouched',flush=True)