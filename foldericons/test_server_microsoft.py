import unittest
import copy
import io
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from foldericons import server


class MicrosoftTemporaryCopyCleanupTests(unittest.TestCase):
    def test_supported_formats_and_app_labels_match_client(self):
        self.assertEqual(server.MICROSOFT_OFFICE_APPS[".xlsb"], "Excel")
        client = Path(__file__).with_name("client.js").read_text(encoding="utf-8")
        supported = client.split("const SUPPORTED = new Map([", 1)[1].split("]);", 1)[0]
        for extension, app in server.MICROSOFT_OFFICE_APPS.items():
            self.assertIn(f'["{extension[1:]}", "{app}"]', supported)
        for extension in server.MICROSOFT_CONVERSION_EXTENSIONS:
            self.assertNotIn(f'["{extension[1:]}",', supported)

    def test_cleanup_bypasses_word_for_web_coauthoring_lock(self) -> None:
        with mock.patch.object(
            server,
            "microsoft_graph_json",
            return_value=(204, {}),
        ) as graph:
            removed, result = server.microsoft_remove_temporary_copy(
                "access-token",
                "remote/id",
                '"saved-version"',
            )

        self.assertTrue(removed)
        self.assertEqual(result, {})
        graph.assert_called_once_with(
            "access-token",
            "DELETE",
            "/me/drive/items/remote%2Fid",
            extra_headers={"Prefer": "bypass-shared-lock, bypass-checked-out", "If-Match": '"saved-version"'},
        )

    def test_cleanup_treats_an_already_missing_copy_as_complete(self) -> None:
        with mock.patch.object(
            server,
            "microsoft_graph_json",
            return_value=(404, {"error": {"code": "itemNotFound"}}),
        ):
            removed, _result = server.microsoft_remove_temporary_copy(
                "access-token",
                "remote-id",
                '"saved-version"',
            )

        self.assertTrue(removed)

    def test_cleanup_preserves_a_session_after_an_actual_failure(self) -> None:
        with mock.patch.object(
            server,
            "microsoft_graph_json",
            return_value=(403, {"error": {"message": "Access denied"}}),
        ):
            removed, result = server.microsoft_remove_temporary_copy(
                "access-token",
                "remote-id",
                '"saved-version"',
            )

        self.assertFalse(removed)
        self.assertEqual(server.microsoft_error_message(result, "fallback"), "Access denied")

    def test_cleanup_refuses_unverified_versions(self):
        for etag in ("", "*"):
            with self.subTest(etag=etag), mock.patch.object(server, "microsoft_graph_json") as graph:
                removed, _ = server.microsoft_remove_temporary_copy("token", "id", etag)
                self.assertFalse(removed)
                graph.assert_not_called()

    def test_cleanup_preserves_newer_word_changes(self):
        with mock.patch.object(server, "microsoft_graph_json", return_value=(412, {})):
            removed, result = server.microsoft_remove_temporary_copy("token", "id", '"v1"')
        self.assertFalse(removed)
        self.assertEqual(result["error"]["code"], "remote_conflict")

    def test_cleanup_network_error_is_retryable(self):
        with mock.patch.object(server, "microsoft_graph_json", side_effect=server.MicrosoftBridgeError("timeout")):
            removed, result = server.microsoft_remove_temporary_copy("token", "id", '"v1"')
        self.assertFalse(removed)
        self.assertIn("timeout", result["error"]["message"])

    def test_async_delete_is_not_claimed_complete(self):
        with mock.patch.object(server, "microsoft_graph_json", return_value=(202, {})):
            removed, _ = server.microsoft_remove_temporary_copy("token", "id", '"v1"')
        self.assertFalse(removed)

    def test_missing_etag_fails_closed(self):
        with mock.patch.object(server, "microsoft_graph_json", return_value=(200, {"id": "id"})):
            with self.assertRaises(server.MicrosoftBridgeError):
                server.microsoft_item_etag("token", "id")


class MicrosoftAutomaticCleanupTests(unittest.TestCase):
    def run_retry(self, session, result=(True, {}), token_error=None):
        account = {"sessions": {"file": session}}
        snapshots = []
        with mock.patch.object(server, "load_microsoft_account", return_value=account), \
             mock.patch.object(server, "load_microsoft_config", return_value={"mode": "rclone"}), \
             mock.patch.object(server, "microsoft_access_token", return_value=("token", account), side_effect=token_error), \
             mock.patch.object(server, "microsoft_remove_temporary_copy", return_value=result) as remove, \
             mock.patch.object(server, "save_microsoft_account", side_effect=lambda _u, a: snapshots.append(copy.deepcopy(a))):
            server.microsoft_retry_cleanup("alice", now=100)
        return account, remove, snapshots

    def pending(self, **changes):
        return {"remoteId": "remote", "savedRemoteETag": '"saved-v1"', "autoCleanup": True,
                "cleanupAttempts": 0, "cleanupNextAttemptAt": 90, **changes}

    def test_retry_removes_only_the_saved_version(self):
        account, remove, snapshots = self.run_retry(self.pending())
        remove.assert_called_once_with("token", "remote", '"saved-v1"')
        self.assertEqual(account["sessions"], {})
        self.assertEqual(snapshots[-1]["sessions"], {})

    def test_locked_copy_is_retained_with_later_retry(self):
        account, _, _ = self.run_retry(self.pending(), (False, {"error": {"message": "locked"}}))
        session = account["sessions"]["file"]
        self.assertTrue(session["autoCleanup"])
        self.assertEqual(session["cleanupAttempts"], 1)
        self.assertGreater(session["cleanupNextAttemptAt"], 100)
        self.assertEqual(session["savedRemoteETag"], '"saved-v1"')

    def test_changed_cloud_version_stops_automatic_deletion(self):
        account, _, _ = self.run_retry(self.pending(), (False, {"error": {"code": "remote_conflict", "message": "new changes"}}))
        self.assertFalse(account["sessions"]["file"]["autoCleanup"])

    def test_legacy_reopened_not_due_and_exhausted_sessions_are_untouched(self):
        for changes in ({"savedRemoteETag": ""}, {"autoCleanup": False},
                        {"cleanupNextAttemptAt": 101}, {"cleanupAttempts": 6}):
            with self.subTest(changes=changes):
                _, remove, snapshots = self.run_retry(self.pending(**changes))
                remove.assert_not_called()
                self.assertEqual(snapshots, [])

    def test_sixth_failure_stops_retrying_but_retains_manual_recovery(self):
        account, _, _ = self.run_retry(self.pending(cleanupAttempts=5), (False, {"error": {"message": "locked"}}))
        self.assertFalse(account["sessions"]["file"]["autoCleanup"])
        self.assertEqual(account["sessions"]["file"]["cleanupAttempts"], 6)

    def test_expired_connection_preserves_copy_and_stops_retries(self):
        account, remove, _ = self.run_retry(self.pending(), token_error=server.MicrosoftBridgeError("expired"))
        remove.assert_not_called()
        self.assertFalse(account["sessions"]["file"]["autoCleanup"])
        self.assertIn("Reconnect", account["sessions"]["file"]["cleanupError"])


class MicrosoftHandlerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.handler = object.__new__(server.Handler)
        self.handler._authorize = mock.Mock(return_value=("auth", {}, "alice"))
        self.handler._has_permission = mock.Mock(return_value=True)
        self.handler._send = mock.Mock()
        self.handler._json_body = mock.Mock(return_value={"source": "disk", "path": "test.docx"})
        self.handler._resolved_item = mock.Mock(return_value=(Path("/test"), ("test.docx",), (), 0, "canonical"))
        self.session = {"remoteId": "remote-id", "originalMtimeNs": 1, "originalSize": 3,
                        "webUrl": "https://onedrive.live.com/test", "app": "Word"}
        self.account = {"sessions": {"canonical": self.session}}
        self.info = SimpleNamespace(st_mtime_ns=1, st_size=3, st_mode=0o100644)
        self.saved = []
        self.patch(server, "load_microsoft_config", return_value={"mode": "rclone", "maxFileBytes": 1024})
        self.patch(server, "load_microsoft_account", return_value=self.account)
        self.token = self.patch(server, "microsoft_access_token", return_value=("token", self.account))
        self.patch(server, "save_microsoft_account", side_effect=lambda _u, a: self.saved.append(copy.deepcopy(a)))
        self.stat = self.patch(server, "stat_location", return_value=self.info)
        self.cleanup = self.patch(server, "microsoft_remove_temporary_copy", return_value=(True, {}))
        self.other_editors = self.patch(server, "microsoft_other_editors", return_value=0)

    def patch(self, obj, name, **kwargs):
        patcher = mock.patch.object(obj, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def result(self):
        args = self.handler._send.call_args.args
        return args[0], json.loads(args[1])

    def prepare_download(self):
        response = io.BytesIO(b"new")
        response.headers = {"Content-Length": "3"}
        self.opener = self.patch(server.urllib.request, "build_opener")
        self.opener.return_value.open.return_value = response
        self.etags = self.patch(server, "microsoft_item_etag", return_value='"v1"')
        self.directory = self.patch(server, "open_directory", return_value=90)
        for attr in ("O_CLOEXEC", "O_NOFOLLOW"):
            self.patch(server.os, attr, create=True, new=0)
        self.patch(server.os, "open", return_value=91)
        self.patch(server.os, "write", side_effect=lambda _fd, value: len(value))
        self.patch(server.os, "fchmod", create=True)
        self.patch(server.os, "fsync")
        self.patch(server.os, "close")
        self.patch(server.os, "unlink")
        self.replace = self.patch(server.os, "replace")
        self.history = self.patch(server, "create_edit_history_plan", return_value={"kind": "edit", "id": "a" * 24})
        self.patch(server, "record_operation")

    def test_read_only_user_cannot_open_or_save_or_cleanup(self):
        self.handler._has_permission.return_value = False
        for method in ("_microsoft_open", "_microsoft_save_back"):
            with self.subTest(method=method):
                getattr(self.handler, method)()
                self.assertEqual(self.result()[0], 403)
        self.token.assert_not_called()
        self.cleanup.assert_not_called()
        self.handler._resolved_item.assert_not_called()

    def test_rclone_device_endpoints_return_actionable_error(self):
        for method in ("_microsoft_device_start", "_microsoft_device_poll"):
            with self.subTest(method=method), mock.patch.object(server, "microsoft_http_json") as http:
                getattr(self.handler, method)()
                status, value = self.result()
                self.assertEqual(status, 409)
                self.assertEqual(value["code"], "server_reconnect_required")
                http.assert_not_called()

    def test_cleanup_only_never_touches_local_file(self):
        self.handler._json_body.return_value["cleanupOnly"] = True
        self.session["savedRemoteETag"] = '"v1"'
        self.handler._microsoft_save_back()
        self.assertTrue(self.result()[1]["cloudRemoved"])
        self.stat.assert_not_called()
        self.cleanup.assert_called_once_with("token", "remote-id", '"v1"')
        self.assertNotIn("canonical", self.saved[-1]["sessions"])

    def test_legacy_session_requires_save_before_cleanup(self):
        self.handler._json_body.return_value["cleanupOnly"] = True
        self.handler._microsoft_save_back()
        self.assertEqual(self.result()[1]["code"], "save_required")
        self.cleanup.assert_not_called()

    def test_cleanup_failure_retains_version_and_session(self):
        self.handler._json_body.return_value["cleanupOnly"] = True
        self.session["savedRemoteETag"] = '"v1"'
        self.cleanup.return_value = (False, {"error": {"message": "locked"}})
        self.handler._microsoft_save_back()
        self.assertTrue(self.result()[1]["cleanupPending"])
        self.assertEqual(self.saved[-1]["sessions"]["canonical"]["savedRemoteETag"], '"v1"')
        self.stat.assert_not_called()

    def test_save_records_recovery_before_cleanup(self):
        self.prepare_download()
        def delete(*_args):
            self.assertEqual(self.saved[-1]["sessions"]["canonical"]["savedRemoteETag"], '"v1"')
            self.replace.assert_called_once()
            return True, {}
        self.cleanup.side_effect = delete
        self.handler._microsoft_save_back()
        self.assertTrue(self.result()[1]["cloudRemoved"])
        self.assertEqual(self.etags.call_count, 2)
        self.assertNotIn("canonical", self.saved[-1]["sessions"])

    def test_remote_change_during_download_never_replaces_or_deletes(self):
        self.prepare_download()
        self.etags.side_effect = ['"v1"', '"v2"']
        self.handler._microsoft_save_back()
        self.assertEqual(self.result()[1]["code"], "remote_conflict")
        self.replace.assert_not_called()
        self.cleanup.assert_not_called()

    def test_backup_failure_never_replaces_or_deletes(self):
        self.prepare_download()
        self.history.return_value = None
        self.handler._microsoft_save_back()
        self.assertEqual(self.result()[1]["code"], "backup_failed")
        self.replace.assert_not_called()
        self.cleanup.assert_not_called()

    def test_restore_requires_modify_permission(self):
        self.handler.command = "POST"
        self.handler._has_permission.return_value = False
        self.handler._microsoft_versions()
        self.assertEqual(self.result()[0], 403)
        self.handler._resolved_item.assert_not_called()

    def test_conversion_formats_never_upload_or_get_saved_back_as_original(self):
        for extension in server.MICROSOFT_CONVERSION_EXTENSIONS:
            with self.subTest(extension=extension):
                self.handler._resolved_item.return_value = (Path("/test"), ("test" + extension,), (), 0, "canonical")
                self.handler._microsoft_open()
                self.assertEqual(self.result()[1]["code"], "conversion_required")
                self.handler._microsoft_save_back()
                self.assertEqual(self.result()[1]["code"], "conversion_required")
        self.token.assert_not_called()
        self.cleanup.assert_not_called()

    def test_binary_workbooks_are_accepted_but_mail_and_notebooks_are_not_uploaded(self):
        self.account["sessions"].clear()
        self.token.side_effect = server.MicrosoftBridgeError("reached upload preparation")
        self.handler._resolved_item.return_value = (Path("/test"), ("test.xlsb",), (), 0, "canonical")
        self.handler._microsoft_open()
        self.token.assert_called_once()
        self.token.reset_mock()
        for extension in ("eml", "msg", "oft", "pst", "ost", "one", "onepkg"):
            self.handler._resolved_item.return_value = (Path("/test"), ("test." + extension,), (), 0, "canonical")
            self.handler._microsoft_open()
            self.assertEqual(self.result()[1]["code"], "unsupported_type")
        self.token.assert_not_called()

    def test_restore_refuses_active_cloud_copy(self):
        self.handler.command = "POST"
        self.handler._microsoft_versions()
        self.assertEqual(self.result()[1]["code"], "active_copy")

    def test_versions_obey_current_scope(self):
        self.handler.command = "GET"
        self.handler.path = "/__foldericons/microsoft/versions?source=disk&path=test.docx"
        self.handler._resolved_item.return_value = None
        self.handler._microsoft_versions()
        self.assertEqual(self.result()[0], 404)

    def test_local_change_during_download_never_overwrites_even_with_force(self):
        self.prepare_download()
        self.handler._json_body.return_value["force"] = True
        self.stat.side_effect = [self.info, SimpleNamespace(st_mtime_ns=2, st_size=3)]
        self.handler._microsoft_save_back()
        self.assertEqual(self.result()[1]["code"], "local_conflict")
        self.replace.assert_not_called()
        self.cleanup.assert_not_called()

    def test_lock_failure_after_save_is_reported_as_saved_and_retryable(self):
        self.prepare_download()
        self.cleanup.return_value = (False, {"error": {"message": "locked"}})
        self.handler._microsoft_save_back()
        status, value = self.result()
        self.assertEqual(status, 200)
        self.assertTrue(value["saved"])
        self.assertTrue(value["cleanupPending"])
        self.assertEqual(value["cleanupError"], "locked")
        self.assertIn("savedRemoteETag", self.saved[-1]["sessions"]["canonical"])

    def test_status_surfaces_pending_cleanup(self):
        self.session.update(savedRemoteETag='"v1"', cleanupError="locked")
        with mock.patch.object(server, "microsoft_rclone_token", return_value="token"):
            self.handler._microsoft_status({"source": ["disk"], "path": ["test.docx"]})
        self.assertTrue(self.result()[1]["active"]["cleanupPending"])
        self.assertEqual(self.result()[1]["active"]["cleanupError"], "locked")

    def test_reopening_cancels_pending_automatic_cleanup(self):
        self.session.update(autoCleanup=True, cleanupNextAttemptAt=90)
        self.handler._microsoft_open()
        self.assertEqual(self.result()[0], 200)
        self.assertFalse(self.saved[-1]["sessions"]["canonical"]["autoCleanup"])
        self.cleanup.assert_not_called()

    def test_session_centre_exposes_no_secrets_and_respects_current_scope(self):
        self.session.update(source="disk", path="test.docx", name="test.docx")
        self.account["accessToken"] = "secret"
        self.handler._microsoft_sessions()
        value = self.result()[1]
        self.assertEqual(len(value["items"]), 1)
        self.assertNotIn("secret", json.dumps(value))
        self.assertNotIn("remoteId", value["items"][0])
        self.handler._resolved_item.return_value = None
        self.handler._microsoft_sessions()
        self.assertEqual(self.result()[1]["items"], [])

    def test_session_centre_includes_completed_save_receipts(self):
        self.prepare_download()
        self.handler._microsoft_save_back()
        self.handler._microsoft_sessions()
        item = self.result()[1]["items"][0]
        self.assertFalse(item["active"])
        self.assertTrue(item["cloudRemoved"])
        self.assertGreater(item["savedBackAt"], 0)

    def test_other_editor_warning_precedes_cloud_upload(self):
        self.account["sessions"].clear()
        self.other_editors.return_value = 1
        self.handler._microsoft_open()
        self.assertEqual(self.result()[1]["code"], "other_editor")
        self.token.assert_not_called()

    def test_concurrent_open_requires_explicit_override(self):
        self.account["sessions"].clear()
        self.other_editors.return_value = 1
        self.handler._json_body.return_value["allowConcurrent"] = True
        self.token.side_effect = server.MicrosoftBridgeError("reached upload preparation")
        self.handler._microsoft_open()
        self.token.assert_called_once()


@unittest.skipUnless(os.name == "posix", "requires production POSIX dir_fd operations")
class MicrosoftVersionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / "test.docx"
        self.file.write_bytes(b"old version")
        patches = [mock.patch.object(server, "OPERATION_HISTORY_DIR", self.root / "records"),
                   mock.patch.object(server, "resolve_operation_target", side_effect=lambda source, path, scopes: (self.root, self.root / path.lstrip("/")) if source == "disk" and ".." not in path else None)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        plan = server.create_edit_history_plan("alice", {}, "disk", "test.docx")
        server.record_operation("alice", plan)
        self.file.write_bytes(b"current version")
        self.versions = server.microsoft_file_versions("alice", {}, "disk", "test.docx")
        info = self.file.stat()
        self.revision = f"{info.st_mtime_ns}:{info.st_size}"

    def test_restore_keeps_both_selected_snapshot_and_previous_file(self):
        server.microsoft_restore_version("alice", {}, "disk", "test.docx", self.versions[0]["id"], self.revision)
        self.assertEqual(self.file.read_bytes(), b"old version")
        versions = server.microsoft_file_versions("alice", {}, "disk", "test.docx")
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]["payload"].read_bytes(), b"current version")
        self.assertEqual(versions[1]["payload"].read_bytes(), b"old version")

    def test_changed_file_and_unknown_version_are_rejected(self):
        for version_id, revision in ((self.versions[0]["id"], "stale"), ("../wrong", self.revision)):
            with self.assertRaises(server.MicrosoftBridgeError):
                server.microsoft_restore_version("alice", {}, "disk", "test.docx", version_id, revision)
            self.assertEqual(self.file.read_bytes(), b"current version")

    def test_other_user_other_file_and_symlink_snapshot_are_not_listed(self):
        self.assertEqual(server.microsoft_file_versions("bob", {}, "disk", "test.docx"), [])
        self.assertEqual(server.microsoft_file_versions("alice", {}, "disk", "other.docx"), [])
        payload = self.versions[0]["payload"]
        payload.unlink()
        payload.symlink_to(self.file)
        self.assertEqual(server.microsoft_file_versions("alice", {}, "disk", "test.docx"), [])


if __name__ == "__main__":
    unittest.main()
