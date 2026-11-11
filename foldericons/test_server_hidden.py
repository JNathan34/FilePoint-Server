import base64
from pathlib import Path
import stat
import struct
import unittest
from unittest import mock

from foldericons import server


class SambaHiddenAttributeTests(unittest.TestCase):
    def setUp(self) -> None:
        # These fixtures assert the raw fallback parser's representation, not
        # Samba's optional native DOSATTRIB object (installed on ZimaOS).
        patcher = mock.patch.object(server, "samba_xattr", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_decodes_real_version_three_samba_blob(self) -> None:
        payload = base64.b64decode(
            "MHgxMAAAAwADAAAAEQAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIYImavz7NgBAAAAAAAAAAA="
        )

        attributes, raw = server.decode_dos_attributes(payload)

        self.assertEqual(attributes, server.DOS_ATTRIBUTE_DIRECTORY)
        self.assertIsInstance(raw, server.RawDosAttributes)

    def test_toggling_hidden_preserves_the_rest_of_a_samba_blob(self) -> None:
        payload = base64.b64decode(
            "MHgxMAAAAwADAAAAEQAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIYImavz7NgBAAAAAAAAAAA="
        )
        attributes, raw = server.decode_dos_attributes(payload)
        before = bytes(raw.payload)

        updated = raw.update(attributes | server.DOS_ATTRIBUTE_HIDDEN)

        decoded, _raw = server.decode_dos_attributes(updated)
        self.assertEqual(decoded, server.DOS_ATTRIBUTE_DIRECTORY | server.DOS_ATTRIBUTE_HIDDEN)
        self.assertEqual(updated[:4], b"0x12")
        changed = {index for index, pair in enumerate(zip(before, updated)) if pair[0] != pair[1]}
        self.assertEqual(changed, {3, 16})

    def test_decodes_and_updates_current_version_five_blob(self) -> None:
        payload = bytearray(24)
        struct.pack_into("<H", payload, 2, 5)
        struct.pack_into("<I", payload, 4, 5)
        struct.pack_into("<I", payload, 8, 0x11)
        struct.pack_into("<I", payload, 12, server.DOS_ATTRIBUTE_ARCHIVE)

        attributes, raw = server.decode_dos_attributes(bytes(payload))
        updated = raw.update(attributes | server.DOS_ATTRIBUTE_HIDDEN)
        decoded, _raw = server.decode_dos_attributes(updated)

        self.assertEqual(decoded, server.DOS_ATTRIBUTE_ARCHIVE | server.DOS_ATTRIBUTE_HIDDEN)
        self.assertEqual(struct.unpack_from("<I", updated, 8)[0], 0x11)

    def test_marks_attribute_field_valid_when_setting_hidden(self) -> None:
        payload = bytearray(24)
        struct.pack_into("<H", payload, 2, 5)
        struct.pack_into("<I", payload, 4, 5)
        struct.pack_into("<I", payload, 8, 0x10)
        struct.pack_into("<I", payload, 12, server.DOS_ATTRIBUTE_ARCHIVE)

        attributes, raw = server.decode_dos_attributes(bytes(payload))
        self.assertEqual(attributes, 0)
        updated = raw.update(server.DOS_ATTRIBUTE_HIDDEN)

        self.assertEqual(struct.unpack_from("<I", updated, 8)[0], 0x11)
        self.assertEqual(server.decode_dos_attributes(updated)[0], server.DOS_ATTRIBUTE_HIDDEN)

    def test_still_accepts_legacy_hex_storage(self) -> None:
        attributes, raw = server.decode_dos_attributes(b"0x22")

        self.assertEqual(attributes, server.DOS_ATTRIBUTE_ARCHIVE | server.DOS_ATTRIBUTE_HIDDEN)
        self.assertIsNone(raw)

    def test_setting_hidden_on_a_fresh_file_creates_windows_attributes(self) -> None:
        written: list[tuple[int, str, bytes]] = []

        with (
            mock.patch.object(server, "open_location", return_value=41),
            mock.patch.object(server, "read_dos_attributes", return_value=(0, None, "none")),
            mock.patch.object(server.os, "fstat", return_value=mock.Mock(st_mode=stat.S_IFREG)),
            mock.patch.object(
                server.os,
                "setxattr",
                side_effect=lambda fd, name, payload: written.append((fd, name, payload)),
                create=True,
            ),
            mock.patch.object(server.os, "close"),
        ):
            hidden = server.set_dos_hidden_location(mock.Mock(), ("example.txt",), True)

        self.assertTrue(hidden)
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0][:2], (41, server.DOS_ATTRIBUTE_NAME))
        attributes, _raw = server.decode_dos_attributes(written[0][2])
        self.assertEqual(attributes, server.DOS_ATTRIBUTE_ARCHIVE | server.DOS_ATTRIBUTE_HIDDEN)

    def test_setting_hidden_on_a_fresh_folder_keeps_directory_type(self) -> None:
        payloads: list[bytes] = []

        with (
            mock.patch.object(server, "open_location", return_value=42),
            mock.patch.object(server, "read_dos_attributes", return_value=(0, None, "none")),
            mock.patch.object(server.os, "fstat", return_value=mock.Mock(st_mode=stat.S_IFDIR)),
            mock.patch.object(
                server.os,
                "setxattr",
                side_effect=lambda _fd, _name, payload: payloads.append(payload),
                create=True,
            ),
            mock.patch.object(server.os, "close"),
        ):
            hidden = server.set_dos_hidden_location(mock.Mock(), ("folder",), True)

        self.assertTrue(hidden)
        attributes, _raw = server.decode_dos_attributes(payloads[0])
        self.assertEqual(attributes, server.DOS_ATTRIBUTE_DIRECTORY | server.DOS_ATTRIBUTE_HIDDEN)

    def test_clearing_hidden_preserves_other_samba_metadata(self) -> None:
        payload = bytearray(24)
        struct.pack_into("<H", payload, 2, 5)
        struct.pack_into("<I", payload, 4, 5)
        struct.pack_into("<I", payload, 8, 0x11)
        original_attributes = server.DOS_ATTRIBUTE_ARCHIVE | server.DOS_ATTRIBUTE_HIDDEN
        struct.pack_into("<I", payload, 12, original_attributes)
        struct.pack_into("<Q", payload, 16, 0x0123456789ABCDEF)
        attributes, raw = server.decode_dos_attributes(bytes(payload))
        written: list[bytes] = []

        with (
            mock.patch.object(server, "open_location", return_value=43),
            mock.patch.object(server, "read_dos_attributes", return_value=(attributes, raw, "xattr")),
            mock.patch.object(
                server.os,
                "setxattr",
                side_effect=lambda _fd, _name, value: written.append(value),
                create=True,
            ),
            mock.patch.object(server.os, "close"),
        ):
            hidden = server.set_dos_hidden_location(mock.Mock(), ("example.txt",), False)

        self.assertFalse(hidden)
        decoded, _raw = server.decode_dos_attributes(written[0])
        self.assertEqual(decoded, server.DOS_ATTRIBUTE_ARCHIVE)
        self.assertEqual(struct.unpack_from("<Q", written[0], 16)[0], 0x0123456789ABCDEF)


@unittest.skipUnless(server.samba_xattr is not None, "native Samba library is not installed")
class NativeSambaHiddenAttributeTests(unittest.TestCase):
    def test_native_parser_decodes_real_blob_and_legacy_attributes(self) -> None:
        payload = base64.b64decode("MHgxMAAAAwADAAAAEQAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIYImavz7NgBAAAAAAAAAAA=")
        attributes, value = server.decode_dos_attributes(payload)
        self.assertEqual(attributes, server.DOS_ATTRIBUTE_DIRECTORY)
        self.assertIsInstance(value, server.samba_xattr.DOSATTRIB)
        self.assertEqual(server.decode_dos_attributes(b"0x22")[0], server.DOS_ATTRIBUTE_ARCHIVE | server.DOS_ATTRIBUTE_HIDDEN)

    def test_native_hidden_update_round_trips_without_losing_metadata(self) -> None:
        value = server.samba_xattr.DOSATTRIB()
        value.version = 5
        value.info.valid_flags = server.samba_xattr.XATTR_DOSINFO_ATTRIB
        value.info.attrib = server.DOS_ATTRIBUTE_ARCHIVE
        value.info.create_time = 0x0123456789ABCDEF
        written = []
        with mock.patch.object(server, "open_location", return_value=43), \
             mock.patch.object(server, "read_dos_attributes", return_value=(server.DOS_ATTRIBUTE_ARCHIVE, value, "xattr")), \
             mock.patch.object(server.os, "setxattr", side_effect=lambda _fd, _name, data: written.append(data), create=True), \
             mock.patch.object(server.os, "close"):
            self.assertTrue(server.set_dos_hidden_location(mock.Mock(), ("test.txt",), True))
        attributes, decoded = server.decode_dos_attributes(written[0])
        self.assertEqual(attributes, server.DOS_ATTRIBUTE_ARCHIVE | server.DOS_ATTRIBUTE_HIDDEN)
        self.assertEqual(decoded.info.create_time, 0x0123456789ABCDEF)


class ClientHiddenRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = Path(server.__file__).with_name("client.js").read_text(encoding="utf-8")

    def test_hidden_renderer_targets_files_and_folders(self) -> None:
        self.assertIn(
            '".listing-view-root :is(.folder-items, .file-items) > .listing-item[data-name]"',
            self.client,
        )
        self.assertIn('container?.matches(".folder-items, .file-items")', self.client)

    def test_hidden_renderer_matches_windows_visibility(self) -> None:
        self.assertIn(".listing-item.plexpoint-hidden-item", self.client)
        self.assertIn("display: none !important", self.client)
        self.assertIn(".listing-item.plexpoint-hidden-revealed", self.client)
        self.assertIn(
            'row.classList.add(state.showHidden ? "plexpoint-hidden-revealed" : "plexpoint-hidden-item")',
            self.client,
        )
        self.assertNotIn('content: "Hidden"', self.client)


if __name__ == "__main__":
    unittest.main()
