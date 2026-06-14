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

    def test_label_shows_actual_backend_without_marker(self):
        from eps2svg_gui.file_list import FileRow, RowStatus, row_label
        row = FileRow(src=Path("logo.eps"), status=RowStatus.DONE,
                      backend="Ghostscript", backend_predicted=False)
        label = row_label(row)
        self.assertIn("Ghostscript", label)
        self.assertNotIn("~", label)

    def test_label_marks_predicted_backend_with_tilde(self):
        from eps2svg_gui.file_list import FileRow, RowStatus, row_label
        row = FileRow(src=Path("logo.eps"), status=RowStatus.QUEUED,
                      backend="Pure Python", backend_predicted=True)
        self.assertIn("~Pure Python", row_label(row))
