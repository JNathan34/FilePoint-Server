"""One-time host installation; run with sudo on the ZimaOS server."""
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess

BASE = Path(__file__).resolve().parent.parent
FOLDER = BASE / 'foldericons'


def run(*args):
    print('Running:', ' '.join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], check=True)


if __name__ == '__main__':
    backup = BASE / 'backups' / ('connected-storage-host-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir()
    # CasaOS owns the running project's name and long-form volume mapping.
    info = json.loads(subprocess.check_output(['docker','inspect','plexpoint-files'],text=True))[0]
    labels = info['Config']['Labels']
    managed = Path(labels['com.docker.compose.project.config_files'].split(',')[0])
    project = labels['com.docker.compose.project']
    text = managed.read_text()
    if '/media/FilePoint-Devices' not in text:
        marker = '              target: /home/filebrowser/data'
        if marker not in text:
            raise RuntimeError('Unrecognized managed compose layout')
        shutil.copy2(managed,backup/'casaos-compose.yml')
        text = text.replace(marker, marker + "\n            - type: bind\n              source: /media/FilePoint-Devices\n              target: /storage/Connected devices\n              bind:\n                propagation: rslave",1)
        managed.write_text(text)
    for name in ['filepoint-storage.service','plexpoint-foldericons.service']:
        target = Path('/etc/systemd/system')/name
        if target.exists(): shutil.copy2(target,backup/name)
        shutil.copy2(FOLDER/name,target)
    run('systemctl','daemon-reload')
    run('systemctl','enable','--now','filepoint-storage.service')
    run('python3','-B',FOLDER/'storage_broker.py','--prepare')
    run('docker','compose','-p',project,'-f',managed,'config','-q')
    run('docker','compose','-p',project,'-f',managed,'up','-d','--no-deps','files')
    run('systemctl','restart','plexpoint-foldericons.service')
    run('systemctl','is-active','filepoint-storage.service','plexpoint-foldericons.service')
    print('CONNECTED_STORAGE_INSTALLED',flush=True)
