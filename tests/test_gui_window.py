import tempfile
import time
import unittest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

HAVE_QT = True
try:
    from tests.qt_app import ensure_qapp
except Exception:
    HAVE_QT = False


def setUpModule():
    if HAVE_QT:
        ensure_qapp()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class MainWindowModelTests(unittest.TestCase):
    def test_on_finished_marks_done_and_stores_path(self):
        from eps2svg_gui.main_window import MainWindow
        from eps2svg_gui.file_list import FileRow, RowStatus
        w = MainWindow()
        rid = w._append_row(FileRow(src=Path("logo.eps")))
        w._on_finished(rid, True, "logo.svg", "Pure Python")
        self.assertEqual(w.rows[rid].status, RowStatus.DONE)
        self.assertEqual(w.rows[rid].out_path, "logo.svg")
        self.assertEqual(w.list_widget.item(rid).text(), "logo.eps    ✓ Done")

    def test_on_finished_marks_error(self):
        from eps2svg_gui.main_window import MainWindow
        from eps2svg_gui.file_list import FileRow, RowStatus
        w = MainWindow()
        rid = w._append_row(FileRow(src=Path("bad.eps")))
        w._on_finished(rid, False, "", "boom")
        self.assertEqual(w.rows[rid].status, RowStatus.ERROR)
        self.assertEqual(w.list_widget.item(rid).toolTip(), "boom")

    def test_set_output_dir_updates_label(self):
        from eps2svg_gui.main_window import MainWindow
        w = MainWindow()
        w.set_output_dir("/out/here")
        self.assertIn("here", w.output_label.text())
        w.set_output_dir(None)
        self.assertIn("Next to source", w.output_label.text())


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class MainWindowEndToEndTests(unittest.TestCase):
    def test_add_paths_converts_to_done(self):
        from eps2svg_gui.main_window import MainWindow
        from eps2svg_gui.file_list import RowStatus
        app = ensure_qapp()
        with tempfile.TemporaryDirectory() as d:
            w = MainWindow()
            w.set_output_dir(d)
            w.add_paths([str(FIXTURES / "grid_3x3.eps")])
            self.assertEqual(len(w.rows), 1)
            waited = 0.0
            while waited < 5.0 and w.rows[0].status not in (
                RowStatus.DONE,
                RowStatus.ERROR,
            ):
                app.processEvents()
                time.sleep(0.02)
                waited += 0.02
            self.assertEqual(w.rows[0].status, RowStatus.DONE, msg=w.rows[0].message)
            self.assertTrue(Path(w.rows[0].out_path).exists())

    def test_add_paths_filters_unsupported(self):
        from eps2svg_gui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as d:
            junk = Path(d) / "note.txt"
            junk.write_text("x")
            w = MainWindow()
            w.add_paths([str(junk)])
            self.assertEqual(len(w.rows), 0)
