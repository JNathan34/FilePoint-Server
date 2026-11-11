"""Migrate the previously fixed USB source into the portable-storage service."""
import json
from pathlib import Path
import re
import shutil
import subprocess
from datetime import datetime

base=Path(__file__).resolve().parent.parent
backup=base/'backups'/('usb-source-migration-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir()
for filename in ['storage-map.json','docker-compose.yml','filebrowser/config.yaml']:
    p=base/filename
    target=backup/filename; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,target)
    if filename == 'storage-map.json':
        data=json.loads(p.read_text()); data.pop('Sandisk USB',None)
        p.write_text(json.dumps(data,indent=2)+'\n')
    elif filename.endswith('config.yaml'):
        text=p.read_text()
        text,count=re.subn(r'    - name: "Sandisk USB"\n(?:(?!    - name:|http:).*(?:\n|$))*', '',text,count=1)
        if count != 1: raise RuntimeError('Old USB source block not found')
        p.write_text(text)
    else:
        text=p.read_text()
        text=text.replace('      - /media/sde1-usb-SanDisk_SanDisk:/storage/Sandisk USB\n','')
        p.write_text(text)
info=json.loads(subprocess.check_output(['docker','inspect','plexpoint-files'],text=True))[0]
labels=info['Config']['Labels']; managed=Path(labels['com.docker.compose.project.config_files'].split(',')[0])
shutil.copy2(managed,backup/'casaos-compose.yml')
text=managed.read_text()
pattern=r'            - type: bind\n              source: /media/sde1-usb-SanDisk_SanDisk\n              target: /storage/Sandisk USB\n'
text,count=re.subn(pattern,'',text,count=1)
if count != 1: raise RuntimeError('Old managed USB mount not found')
managed.write_text(text)
subprocess.run(['systemctl','restart','filepoint-storage'],check=True)
subprocess.run(['docker','compose','-p',labels['com.docker.compose.project'],'-f',str(managed),'config','-q'],check=True)
subprocess.run(['docker','compose','-p',labels['com.docker.compose.project'],'-f',str(managed),'up','-d','--no-deps','files'],check=True)
subprocess.run(['systemctl','restart','plexpoint-foldericons'],check=True)
print('USB migration complete')
