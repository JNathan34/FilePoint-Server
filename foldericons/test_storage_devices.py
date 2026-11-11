import unittest
from storage_devices import portable_devices, parse_mountinfo


def mount(device="8:17", path="/media/USB", filesystem="exfat", options="rw", source="/dev/sdb1"):
    return f"25 1 {device} / {path} {options} - {filesystem} {source} {options}"


def disk(**changes):
    part = {"type":"part", "fstype":"exfat", "maj:min":"8:17", "uuid":"volume-1", "label":"My USB", "size":2048}
    part.update(changes)
    return {"blockdevices":[{"type":"disk", "tran":"usb", "model":"SanDisk", "serial":"serial-1", "children":[part]}]}


class PortableStorageTests(unittest.TestCase):
    def test_usb_inherits_parent_transport(self):
        d = portable_devices(disk(), mount())[0]
        self.assertEqual((d["kind"], d["icon"], d["mountPath"], d["status"]), ("usb", "usb", "/media/USB", "ready"))

    def test_known_drive_is_not_duplicated(self):
        self.assertEqual(portable_devices(disk(), mount(), ["/media/USB"]), [])

    def test_internal_disks_are_not_portable(self):
        value = disk(); value["blockdevices"][0]["tran"] = "sata"
        self.assertEqual(portable_devices(value, mount()), [])

    def test_system_volume_is_never_exposed(self):
        for path in ["/", "/boot", "/boot/efi", "/DATA", "/var/lib/docker"]:
            self.assertEqual(portable_devices(disk(), mount(path=path)), [])

    def test_zimaos_mirror_is_not_a_system_volume(self):
        mounts = mount() + '\n' + mount(path='/var/lib/casaos_data/.media/USB')
        self.assertEqual(portable_devices(disk(),mounts)[0]['status'],'ready')

    def test_uuid_survives_linux_device_renaming(self):
        a = portable_devices(disk(), mount())[0]
        b = portable_devices(disk(**{"maj:min":"8:33"}), mount(device="8:33", source="/dev/sdc1"))[0]
        self.assertEqual(a["id"], b["id"])

    def test_mount_paths_with_spaces_decode(self):
        self.assertEqual(parse_mountinfo(mount(path=r"/media/My\040USB"))[0]["path"], "/media/My USB")

    def test_unmounted_volume_is_status_only(self):
        d = portable_devices(disk(), "")[0]
        self.assertIsNone(d["mountPath"])
        self.assertEqual(d["status"], "waiting-for-mount")

    def test_read_only_is_preserved(self):
        self.assertTrue(portable_devices(disk(), mount(options="ro"))[0]["readOnly"])

    def test_unsupported_container_volumes_not_shown(self):
        for fs in ["swap", "LVM2_member", "linux_raid_member"]:
            self.assertEqual(portable_devices(disk(fstype=fs), ""), [])

    def test_encrypted_portable_volume_uses_lock_icon(self):
        for fs in ['BitLocker','crypto_LUKS']:
            d=portable_devices(disk(fstype=fs),'')[0]
            self.assertEqual((d['status'],d['icon']),('locked','lock'))

    def test_small_boot_partition_is_hidden_beside_data_partition(self):
        value=disk(fstype='vfat',size=64*1024**2)
        value['blockdevices'][0]['children'].append({'type':'part','fstype':'vfat','maj:min':'8:18','uuid':'data-volume','size':15*1024**3})
        result=portable_devices(value,mount()+'\n'+mount(device='8:18',path='/media/Data'))
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['size'],15*1024**3)

    def test_single_small_usb_is_not_hidden(self):
        self.assertEqual(len(portable_devices(disk(fstype='vfat',size=64*1024**2),mount())),1)

    def test_duplicate_binds_do_not_duplicate_devices(self):
        mounts = mount() + "\n" + mount(path="/media/FilePoint-Devices/device-1")
        self.assertEqual(len(portable_devices(disk(), mounts)), 1)

    def test_cloned_uuid_is_not_merged(self):
        value = disk()
        second = disk(**{"maj:min":"8:33"})["blockdevices"][0]
        value["blockdevices"].append(second)
        self.assertEqual(len(portable_devices(value, mount()+"\n"+mount(device="8:33",path="/media/USB2"))),2)

    def test_sd_card_icon(self):
        value = disk(); value["blockdevices"][0]["tran"] = "mmc"
        self.assertEqual(portable_devices(value, mount())[0]["icon"], "sd_card")

    def test_phone_mount_icon(self):
        for fs in ["fuse.jmtpfs", "fuse.simple-mtpfs", "fuse.ifuse"]:
            d = portable_devices({}, mount(device="0:42",filesystem=fs,path="/media/FilePoint-Phones/Phone",source="phone"))[0]
            self.assertEqual((d["kind"],d["icon"]),("phone","smartphone"))

    def test_phone_propagated_mirrors_never_become_new_devices(self):
        original = mount(device='0:42',filesystem='fuse.jmtpfs',path='/media/FilePoint-Phones/Phone',source='jmtpfs')
        aliases = [mount(device='0:42',filesystem='fuse.jmtpfs',path=p,source='jmtpfs') for p in [
            '/DATA/.media/FilePoint-Phones/Phone', '/var/lib/casaos_data/.media/FilePoint-Phones/Phone',
            '/media/FilePoint-Devices/Phone', '/DATA/.media/FilePoint-Devices/Phone',
            '/var/lib/casaos_data/.media/FilePoint-Devices/Phone']]
        baseline = portable_devices({}, original)
        for generation in range(10):
            self.assertEqual(portable_devices({}, original+'\n'+'\n'.join(aliases * (generation+1))),baseline)
        self.assertEqual(len(baseline),1)
        self.assertEqual(portable_devices({}, '\n'.join(aliases)),[])

    def test_label_cannot_be_path_or_multiline(self):
        d = portable_devices(disk(label="../bad\nname"), mount())[0]
        self.assertNotIn("/",d["label"])
        self.assertNotIn("\n",d["label"])


if __name__ == "__main__":
    unittest.main()
