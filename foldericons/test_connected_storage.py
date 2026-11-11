import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import server


class ConnectedStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'devices.json'
        self.state = {'updatedAt':time.time(),'devices':[
            {'id':'one','name':'USB','label':'USB','kind':'usb','icon':'usb',
             'source':'Home','path':'Connected devices/USB','status':'ready',
             'mountPath':'/private/host/path'}]}
        self.path.write_text(json.dumps(self.state))
        self.patcher = patch.object(server,'CONNECTED_STORAGE',self.path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop(); self.tmp.cleanup()

    def test_home_scope_can_list_devices_without_host_paths(self):
        result=server.connected_devices({'Home':'/'})
        self.assertEqual(len(result),1)
        self.assertNotIn('mountPath',result[0])

    def test_other_source_cannot_list_devices(self):
        self.assertEqual(server.connected_devices({'Documents':'/'}),[])

    def test_scoped_home_cannot_escape_its_folder(self):
        self.assertEqual(server.connected_devices({'Home':'/Documents'}),[])
        self.assertEqual(len(server.connected_devices({'Home':'/Connected devices/USB'})),1)

    def test_stopped_broker_does_not_claim_drives_are_ready(self):
        self.state['updatedAt']=time.time()-60
        self.path.write_text(json.dumps(self.state))
        self.assertEqual(server.connected_devices({'Home':'/'})[0]['status'],'unavailable')

    def test_invalid_device_path_is_omitted(self):
        self.state['devices'][0]['path']='Connected devices/../Documents'
        self.path.write_text(json.dumps(self.state))
        self.assertEqual(server.connected_devices({'Home':'/'}),[])

    def test_missing_registry_is_empty(self):
        self.path.unlink()
        self.assertEqual(server.connected_devices({'Home':'/'}),[])

    def test_locked_device_uses_supplied_lock_icon(self):
        self.state['devices'][0]['status'] = 'locked'
        self.path.write_text(json.dumps(self.state))
        result = server.connected_devices({'Home':'/'})[0]
        self.assertEqual(result['iconUrl'], '/__foldericons/device-icon?kind=lock')

    def test_phone_and_unknown_device_icons(self):
        for kind, expected in [('phone','phone'), ('unrecognized','device')]:
            self.state['devices'][0]['kind'] = kind
            self.path.write_text(json.dumps(self.state))
            result = server.connected_devices({'Home':'/'})[0]
            self.assertEqual(result['iconUrl'], '/__foldericons/device-icon?kind=' + expected)