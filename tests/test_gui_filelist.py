import unittest
from pathlib import Path


class RowStatusTests(unittest.TestCase):
    def test_has_four_states(self):
        from eps2svg_gui.file_list import RowStatus
        names = {s.name for s in RowStatus}
        self.assertEqual(names, {"QUEUED", "CONVERTING", "DONE", "ERROR"})


class FileRowTests(unittest.TestCase):
    def test_defaults(self):
        from eps2svg_gui.file_list import FileRow, RowStatus
        row = FileRow(src=Path("a.eps"))
        self.assertEqual(row.status, RowStatus.QUEUED)
        self.assertEqual(row.out_path, "")
        self.assertEqual(row.message, "")


class RowLabelTests(unittest.TestCase):
    def test_label_includes_name_and_status_word(self):
        from eps2svg_gui.file_list import FileRow, RowStatus, row_label
        row = FileRow(src=Path("/x/logo.eps"), status=RowStatus.DONE)
        label = row_label(row)
        self.assertIn("logo.eps", label)
        self.assertIn("Done", label)
