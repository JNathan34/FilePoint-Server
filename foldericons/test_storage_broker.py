import unittest
from storage_broker import validate_plan

class MountGuardTests(unittest.TestCase):
    def test_phone_mirror_is_rejected_as_a_source(self):
        with self.assertRaises(RuntimeError):
            validate_plan([{'id':'one','kind':'phone','mountPath':'/DATA/.media/FilePoint-Devices/Phone'}],[])

    def test_runaway_plan_stops_before_mounting(self):
        with self.assertRaises(RuntimeError):
            validate_plan([{'id':str(i),'kind':'usb'} for i in range(65)],[])
        with self.assertRaises(RuntimeError):
            validate_plan([], [{'path':'/media/FilePoint-Devices/'+str(i)} for i in range(65)])

    def test_duplicate_identity_and_excess_phones_are_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_plan([{'id':'one','kind':'usb'}]*2,[])
        with self.assertRaises(RuntimeError):
            validate_plan([{'id':str(i),'kind':'phone','mountPath':'/media/FilePoint-Phones/'+str(i)} for i in range(5)],[])

    def test_usb_and_canonical_phone_can_coexist(self):
        validate_plan([{'id':'usb','kind':'usb'},{'id':'phone','kind':'phone','mountPath':'/media/FilePoint-Phones/Android'}],[])
