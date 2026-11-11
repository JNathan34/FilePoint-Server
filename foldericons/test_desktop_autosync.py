import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from foldericons import server


class DesktopAutoSyncTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.scopes = {"Documents": "/"}
        self.session = dict(source="Documents", path="Example.docx", name="Example.docx", app="Word",
                            remoteId="remote-id", originalMtimeNs=10, originalSize=20,
                            autoSync=True, syncScopes=self.scopes, syncRoot=str(self.root.resolve()),
                            syncRemoteETag='"original"', syncState="waiting")
        self.key = server.canonical_location("Documents", ("Example.docx",), ("Example.docx",))
        self.account = {"sessions": {self.key: self.session}}
        self.patches = [
            mock.patch.object(server, "load_microsoft_account", return_value=self.account),
            mock.patch.object(server, "save_microsoft_account"),
            mock.patch.object(server, "load_microsoft_config", return_value={"maxFileBytes": 1024}),
            mock.patch.object(server, "resolve_location", return_value=(self.root, ("Example.docx",), ("Example.docx",), 1)),
            mock.patch.object(server, "stat_location", return_value=SimpleNamespace(st_mtime_ns=10, st_size=20)),
            mock.patch.object(server, "microsoft_access_token", return_value=("test-token", self.account)),
            mock.patch.object(server, "microsoft_item_etag", return_value='"original"'),
            mock.patch.object(server, "microsoft_copy_to_local", return_value=(30, '"edited"')),
            mock.patch.object(server, "microsoft_remove_temporary_copy"),
        ]
        (self.load, self.save, self.config, self.resolve, self.stat,
         self.token, self.etag, self.copy, self.remove) = [p.start() for p in self.patches]
        for patch in self.patches:
            self.addCleanup(patch.stop)

    def test_unchanged_cloud_is_not_downloaded(self):
        server.microsoft_sync_account("tester", now=100)
        self.copy.assert_not_called()
        self.remove.assert_not_called()
        self.assertEqual(self.session["syncState"], "synced")

    def test_changed_cloud_is_saved_without_deleting_editing_copy(self):
        self.etag.return_value = '"edited"'
        self.stat.side_effect = [SimpleNamespace(st_mtime_ns=10, st_size=20), SimpleNamespace(st_mtime_ns=11, st_size=30)]
        server.microsoft_sync_account("tester", now=100)
        self.copy.assert_called_once()
        self.assertEqual(self.session["originalMtimeNs"], 11)
        self.assertEqual(self.session["syncRemoteETag"], '"edited"')
        self.assertTrue(self.session["autoSync"])
        self.assertIn(self.key, self.account["lastSaves"])
        self.remove.assert_not_called()

    def test_local_changes_pause_instead_of_overwrite(self):
        self.stat.return_value = SimpleNamespace(st_mtime_ns=99, st_size=20)
        server.microsoft_sync_account("tester", now=100)
        self.assertFalse(self.session["autoSync"])
        self.assertEqual(self.session["syncState"], "paused")
        self.copy.assert_not_called()
        self.remove.assert_not_called()

    def test_changed_source_mapping_pauses(self):
        self.session["syncRoot"] = str(self.root / "different")
        server.microsoft_sync_account("tester", now=100)
        self.assertFalse(self.session["autoSync"])
        self.copy.assert_not_called()

    def test_missing_original_is_not_recreated(self):
        self.stat.side_effect = FileNotFoundError("Original moved or deleted")
        server.microsoft_sync_account("tester", now=100)
        self.assertFalse(self.session["autoSync"])
        self.copy.assert_not_called()

    def test_cloud_edit_during_download_retries_without_cleanup(self):
        self.etag.return_value = '"edited"'
        self.copy.side_effect = server.MicrosoftBridgeError("Still saving", 409, "remote_conflict")
        server.microsoft_sync_account("tester", now=100)
        self.assertTrue(self.session["autoSync"])
        self.assertEqual(self.session["syncState"], "retrying")
        self.assertGreater(self.session["syncNextAttemptAt"], 100)
        self.assertEqual(self.session["syncRemoteETag"], '"original"')
        self.remove.assert_not_called()

    def test_legacy_sessions_are_not_enrolled(self):
        self.session.pop("autoSync")
        server.microsoft_sync_account("tester", now=100)
        self.token.assert_not_called()
        self.copy.assert_not_called()

    def test_persisted_grant_resumes_without_browser_session(self):
        self.load.return_value = copy.deepcopy(self.account)
        self.token.return_value = ("test-token", self.load.return_value)
        server.microsoft_sync_account("tester", now=100)
        self.assertEqual(self.load.return_value["sessions"][self.key]["syncState"], "synced")
        self.save.assert_called_once_with("tester", self.load.return_value)

    def test_enrollment_refuses_changed_original(self):
        self.stat.return_value = SimpleNamespace(st_mtime_ns=12, st_size=20)
        with self.assertRaises(server.MicrosoftBridgeError):
            server.microsoft_enable_autosync(self.session, self.scopes, self.root, ("Example.docx",))

    def test_desktop_uri_uses_editable_cloud_url(self):
        url = "https://d.docs.live.net/abc/Apps/Example.docx"
        with mock.patch.object(server, "microsoft_graph_json", return_value=(200, {"webDavUrl": url})):
            self.assertEqual(server.microsoft_desktop_url("test", "id", "Word"), "ms-word:ofe|u|" + url)

    def test_desktop_uri_rejects_unsafe_and_download_urls(self):
        for url in ("file:///C:/example.docx", "https://evil.example/file.docx", "https://d.docs.live.net/x|u|evil", "https://user:password@d.docs.live.net/file.docx"):
            with self.subTest(url=url), mock.patch.object(server, "microsoft_graph_json", return_value=(200, {"webDavUrl": url})):
                with self.assertRaises(server.MicrosoftBridgeError):
                    server.microsoft_desktop_url("test", "id", "Word")

    def test_cleanup_worker_cannot_delete_active_autosync_copy(self):
        self.session.update(autoCleanup=True, savedRemoteETag='"original"', cleanupNextAttemptAt=0)
        server.microsoft_retry_cleanup("tester", now=100)
        self.remove.assert_not_called()


if __name__ == "__main__":
    unittest.main()
