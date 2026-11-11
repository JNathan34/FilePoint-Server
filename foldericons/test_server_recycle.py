from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.parse

from foldericons import server


class RecycleBinAndHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.storage = self.base / "storage"
        self.history = self.base / "operation-history"
        self.storage.mkdir()
        self.scopes = {"Documents": "/"}
        self.patches = (
            mock.patch.object(server, "OPERATION_HISTORY_DIR", self.history),
            mock.patch.object(
                server,
                "load_storage_map",
                return_value=(1, {"Documents": self.storage}),
            ),
        )
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temporary.cleanup()

    def test_windows_recycle_bin_icons_are_packaged(self) -> None:
        assets = Path(server.__file__).with_name("assets")
        for name in ("recycle-bin-empty.png", "recycle-bin-full.png"):
            payload = (assets / name).read_bytes()
            self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertGreater(len(payload), 1024)

    def test_delete_moves_to_recycle_bin_and_can_be_undone_and_redone(self) -> None:
        original = self.storage / "Report.txt"
        original.write_text("important", encoding="utf-8")

        item = server.move_item_to_recycle(
            "jacob", self.scopes, "Documents", "/Report.txt"
        )
        server.record_operation(
            "jacob",
            {"kind": "delete", "label": "delete Report.txt", "items": [item]},
        )

        self.assertFalse(original.exists())
        self.assertEqual(server.list_recycle_items("jacob", self.scopes)[0]["name"], "Report.txt")

        undone = server.change_operation_history("jacob", self.scopes, "undo")
        self.assertTrue(undone["changed"])
        self.assertEqual(original.read_text(encoding="utf-8"), "important")
        self.assertEqual(server.list_recycle_items("jacob", self.scopes), [])

        redone = server.change_operation_history("jacob", self.scopes, "redo")
        self.assertTrue(redone["changed"])
        self.assertFalse(original.exists())
        self.assertEqual(len(server.list_recycle_items("jacob", self.scopes)), 1)

    def test_created_item_undo_stashes_exact_content_for_redo(self) -> None:
        created = self.storage / "New file.txt"
        created.write_text("version one", encoding="utf-8")
        record = {
            "id": "create-record",
            "kind": "create",
            "label": "create New file.txt",
            "items": [{"toSource": "Documents", "toPath": "/New file.txt"}],
        }
        server.record_operation("jacob", record)

        server.change_operation_history("jacob", self.scopes, "undo")
        self.assertFalse(created.exists())
        server.change_operation_history("jacob", self.scopes, "redo")
        self.assertEqual(created.read_text(encoding="utf-8"), "version one")

    def test_edit_history_swaps_the_old_and_new_versions(self) -> None:
        document = self.storage / "Notes.txt"
        document.write_text("before", encoding="utf-8")
        record = server.create_edit_history_plan(
            "jacob", self.scopes, "Documents", "/Notes.txt"
        )
        self.assertIsNotNone(record)
        document.write_text("after", encoding="utf-8")
        server.record_operation("jacob", record)

        server.change_operation_history("jacob", self.scopes, "undo")
        self.assertEqual(document.read_text(encoding="utf-8"), "before")
        server.change_operation_history("jacob", self.scopes, "redo")
        self.assertEqual(document.read_text(encoding="utf-8"), "after")

    def test_patch_move_is_prepared_for_proxy_journaling(self) -> None:
        source = self.storage / "Old.txt"
        source.write_text("move me", encoding="utf-8")
        body = server.json_bytes({
            "action": "rename",
            "overwrite": False,
            "rename": False,
            "items": [{
                "fromSource": "Documents",
                "fromPath": "/Old.txt",
                "toSource": "Documents",
                "toPath": "/New.txt",
            }],
        })
        parsed = urllib.parse.urlsplit("/api/resources")

        record = server.prepare_resource_proxy_operation(
            "jacob", self.scopes, "PATCH", parsed, body
        )

        self.assertIsNotNone(record)
        self.assertEqual(record["kind"], "move")
        self.assertEqual(record["items"][0]["toPath"], "/New.txt")

    def test_auto_renamed_same_folder_copy_can_be_undone(self) -> None:
        source = self.storage / "Report.txt"
        duplicate = self.storage / "Report (1).txt"
        source.write_text("copy me", encoding="utf-8")
        body = server.json_bytes({
            "action": "copy",
            "overwrite": False,
            "rename": True,
            "items": [{
                "fromSource": "Documents",
                "fromPath": "/Report.txt",
                "toSource": "Documents",
                "toPath": "/Report.txt",
            }],
        })
        record = server.prepare_resource_proxy_operation(
            "jacob", self.scopes, "PATCH", urllib.parse.urlsplit("/api/resources"), body
        )
        self.assertIsNotNone(record)
        duplicate.write_text("copy me", encoding="utf-8")

        server.finalize_resource_proxy_operation(
            "jacob", self.scopes, record, True
        )
        saved = server.load_operation_history("jacob")
        self.assertEqual(saved["undo"][-1]["items"][0]["toPath"], "/Report (1).txt")

        server.change_operation_history("jacob", self.scopes, "undo")
        self.assertTrue(source.exists())
        self.assertFalse(duplicate.exists())


if __name__ == "__main__":
    unittest.main()
