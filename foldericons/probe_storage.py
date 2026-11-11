import json, subprocess, shutil
from pathlib import Path
base=Path(__file__).resolve().parent
out={}
def run(args):
    p=subprocess.run(args,capture_output=True,text=True,timeout=20)
    return {"code":p.returncode,"stdout":p.stdout,"stderr":p.stderr}
out["lsblk"]=run(["lsblk","-J","-b","-o","NAME,PATH,TYPE,TRAN,RM,HOTPLUG,MODEL,SERIAL,FSTYPE,UUID,PARTUUID,MAJ:MIN,LABEL,SIZE,RO,MOUNTPOINTS"])
out["mountinfo"]=Path("/proc/self/mountinfo").read_text()
out["tools"]={x:shutil.which(x) for x in ["jmtpfs","simple-mtpfs","go-mtpfs","gvfs-mount","gio","ifuse","udevadm","fusermount","fusermount3","apt-get","docker","findmnt","mount"]}
out["os"]=Path("/etc/os-release").read_text()
out["container_mounts"]=run(["docker","inspect","plexpoint-files","--format","{{json .Mounts}}"])
out["media_propagation"]=run(["findmnt","-T","/media","-o","TARGET,PROPAGATION"])
out["usb"]=run(["lsusb"])
out["fuse"]=Path("/dev/fuse").exists()
(base/"storage-probe.json").write_text(json.dumps(out,indent=2))
print("Storage probe saved.")
