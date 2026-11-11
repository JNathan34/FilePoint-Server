import os
import tempfile
import unittest
from pathlib import Path

from native_writes import NativeWrites, WriteError


class NativeWriteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.writes = NativeWrites()

    def tearDown(self):
        for identifier, upload in list(self.writes.uploads.items()):
            self.writes.cancel(identifier, upload.owner)
        self.temporary.cleanup()

    def parent(self, *_args):
        return os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)

    def begin(self, mode="create", owner="one", expected=None):
        fd = self.parent()
        try:
            return self.writes.begin(owner, "Documents", "/file.bin", fd, "file.bin", mode, expected)
        except BaseException:
            os.close(fd)
            raise

    def test_new_file_appears_only_after_complete_commit(self):
        identifier = self.begin()["upload"]
        self.writes.append(identifier, "one", 0, b"first")
        self.assertEqual(list(self.root.iterdir()), [])
        with self.assertRaises(WriteError):
            self.writes.commit(identifier, "one", 9, self.parent)
        self.writes.append(identifier, "one", 5, b"last")
        result = self.writes.commit(identifier, "one", 9, self.parent)
        self.assertEqual(result["length"], 9)
        self.assertEqual((self.root / "file.bin").read_bytes(), b"firstlast")

    def test_two_uploads_never_share_temporary_data_or_overwrite(self):
        one = self.begin()["upload"]
        two = self.begin(owner="two")["upload"]
        self.writes.append(one, "one", 0, b"first")
        self.writes.append(two, "two", 0, b"second")
        self.writes.commit(one, "one", 5, self.parent)
        with self.assertRaises(WriteError) as failure:
            self.writes.commit(two, "two", 6, self.parent)
        self.assertEqual(failure.exception.status, 409)
        self.assertEqual((self.root / "file.bin").read_bytes(), b"first")

    def test_edits_are_atomic_and_check_the_revision(self):
        target = self.root / "file.bin"
        target.write_bytes(b"original")
        pending = self.begin("edit")
        self.writes.append(pending["upload"], "one", 0, b"edited")
        self.assertEqual(target.read_bytes(), b"original")
        target.write_bytes(b"other editor")
        with self.assertRaises(WriteError):
            self.writes.commit(pending["upload"], "one", 6, self.parent)
        self.assertEqual(target.read_bytes(), b"other editor")
        self.writes.cancel(pending["upload"], "one")
        pending = self.begin("edit")
        self.writes.append(pending["upload"], "one", 0, b"edited")
        result = self.writes.commit(pending["upload"], "one", 6, self.parent)
        self.assertEqual(target.read_bytes(), b"edited")
        subsequent = self.begin("edit", expected=result["revision"])
        self.writes.cancel(subsequent["upload"], "one")

    def test_unauthorized_session_and_symlink_are_denied(self):
        identifier = self.begin()["upload"]
        with self.assertRaises(WriteError):
            self.writes.append(identifier, "two", 0, b"wrong owner")
        self.writes.cancel(identifier, "one")
        (self.root / "file.bin").symlink_to(self.root / "outside")
        with self.assertRaises(WriteError):
            self.begin("edit")


if __name__ == "__main__":
    unittest.main()
