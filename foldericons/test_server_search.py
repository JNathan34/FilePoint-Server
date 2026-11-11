from datetime import datetime
from pathlib import Path
import unittest

from foldericons import server


class SearchQueryTests(unittest.TestCase):
    def test_plain_words_and_quoted_name_filter_are_combined(self) -> None:
        criteria = server.parse_search_query('budget name:"final report"')

        self.assertEqual(criteria["terms"], ["budget"])
        self.assertEqual(criteria["names"], ["final report"])
        self.assertTrue(server.search_item_matches(
            "Budget Final Report.docx",
            "Accounts/Budget Final Report.docx",
            False,
            1200,
            1_700_000_000,
            criteria,
        ))
        self.assertFalse(server.search_item_matches(
            "Budget draft.docx",
            "Accounts/Budget draft.docx",
            False,
            1200,
            1_700_000_000,
            criteria,
        ))

    def test_kind_extension_size_and_wildcard_filters(self) -> None:
        criteria = server.parse_search_query("name:report* kind:document ext:pdf size:>1MB")

        self.assertTrue(server.search_item_matches(
            "Report 2026.pdf",
            "Finance/Report 2026.pdf",
            False,
            2 * 1024 * 1024,
            1_700_000_000,
            criteria,
        ))
        self.assertFalse(server.search_item_matches(
            "Report 2026.pdf",
            "Finance/Report 2026.pdf",
            False,
            500 * 1024,
            1_700_000_000,
            criteria,
        ))
        self.assertFalse(server.search_item_matches(
            "Report 2026.docx",
            "Finance/Report 2026.docx",
            False,
            2 * 1024 * 1024,
            1_700_000_000,
            criteria,
        ))

    def test_folder_kind_excludes_files(self) -> None:
        criteria = server.parse_search_query("kind:folder project")

        self.assertTrue(server.search_item_matches(
            "Project Alpha", "Work/Project Alpha", True, 0, 1_700_000_000, criteria
        ))
        self.assertFalse(server.search_item_matches(
            "Project Alpha.txt", "Work/Project Alpha.txt", False, 10, 1_700_000_000, criteria
        ))

    def test_date_presets_produce_bounded_ranges(self) -> None:
        now = datetime(2026, 9, 16, 12, 0).astimezone()

        today = server._search_date_range("today", now)
        last_week = server._search_date_range("last week", now)

        self.assertIsNotNone(today)
        self.assertEqual(today[1] - today[0], 24 * 60 * 60)
        self.assertIsNotNone(last_week)
        self.assertEqual(last_week[1] - last_week[0], 7 * 24 * 60 * 60)

    def test_type_labels_match_explorer_wording(self) -> None:
        self.assertEqual(server.search_type_label("Photos", True), "File folder")
        self.assertEqual(server.search_type_label("invoice.pdf", False), "PDF File")
        self.assertEqual(server.search_type_label("README", False), "File")


class SearchImplementationSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = Path(server.__file__).read_text(encoding="utf-8")

    def test_recursive_search_does_not_follow_symlinks(self) -> None:
        self.assertIn("entry.stat(follow_symlinks=False)", self.source)
        self.assertIn("os.O_NOFOLLOW", self.source)

    def test_search_has_result_scan_and_time_limits(self) -> None:
        self.assertIn("SEARCH_MAX_RESULTS = 500", self.source)
        self.assertIn("SEARCH_MAX_SCANNED = 100_000", self.source)
        self.assertIn("SEARCH_MAX_SECONDS = 12.0", self.source)


if __name__ == "__main__":
    unittest.main()
