import subprocess,json
from pathlib import Path
base=Path(__file__).resolve().parent
info=json.loads(subprocess.check_output(['docker','inspect','plexpoint-files'],text=True))[0]
labels=info['Config']['Labels']
p=Path(labels['com.docker.compose.project.config_files'].split(',')[0])
config=json.loads(subprocess.check_output(['docker','compose','-f',str(p),'config','--format','json'],text=True))
out={'project':labels.get('com.docker.compose.project'),'service':labels.get('com.docker.compose.service'),'compose':str(p),'services':{k:{'volumes':v.get('volumes',[]),'container_name':v.get('container_name')} for k,v in config['services'].items()},'journal':subprocess.run(['journalctl','-u','filepoint-storage','-n','25','--no-pager'],capture_output=True,text=True).stdout}
try: import yaml; out['yaml']=True
except ImportError: out['yaml']=False
(base/'storage-host-check.json').write_text(json.dumps(out,indent=2))
(base/'storage-managed-compose.backup.yml').write_bytes(p.read_bytes())

out['resolved_base']=str(base.resolve())
out['service']=subprocess.run(['systemctl','show','filepoint-storage','-p','MainPID','-p','ActiveState','-p','SubState'],capture_output=True,text=True).stdout
out['files']=subprocess.run(['find','/DATA/AppData/plexpoint-files-office','-maxdepth','1','-name','*storage*'],capture_output=True,text=True).stdout
pid=subprocess.check_output(['systemctl','show','filepoint-storage','-p','MainPID','--value'],text=True).strip()
out['process']=Path('/proc/'+pid+'/wchan').read_text()
(base/'storage-host-check.json').write_text(json.dumps(out,indent=2))

out['host_mounts']=[l for l in Path('/proc/self/mountinfo').read_text().splitlines() if 'FilePoint-' in l]
out['broker_mounts']=[l for l in Path('/proc/'+pid+'/mountinfo').read_text().splitlines() if 'FilePoint-' in l]
out['registry']=json.loads((base.parent/'connected-storage.json').read_text())
out['docker_paths']=subprocess.run(['docker','exec','plexpoint-files','ls','-la','/storage/Connected devices/NEW VOLUME'],capture_output=True,text=True).stdout
(base/'storage-host-check.json').write_text(json.dumps(out,indent=2))

out['android']=subprocess.run(['docker','logs','--tail','12','filepoint-android'],capture_output=True,text=True).stdout
out['phone_mounts']=[m for m in Path('/proc/self/mountinfo').read_text().splitlines() if 'FilePoint-Phones' in m]
(base/'storage-host-check.json').write_text(json.dumps(out,indent=2))
