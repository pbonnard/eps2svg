import tempfile
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
class SplitWindowTests(unittest.TestCase):
    def _prepared_window(self, output_dir=None):
        import eps2svg_grid
        from eps2svg_gui.split_window import SplitWindow
        win = SplitWindow(FIXTURES / "grid_3x3.eps", output_dir=output_dir,
                          autostart=False)
        doc = eps2svg_grid.prepare_split(FIXTURES / "grid_3x3.eps")
        win._on_ready(doc)
        return win

    def test_ready_builds_grid_and_counts_content(self):
        win = self._prepared_window()
        self.assertIsNotNone(win.overlay)
        text = win.count_label.text()
        self.assertIn("content", text.lower())
        self.assertGreater(win.doc.content_cell_count(win._current_cells()), 0)

    def test_extract_writes_cell_svgs(self):
        with tempfile.TemporaryDirectory() as d:
            win = self._prepared_window(output_dir=d)
            win.rows_spin.setValue(3)
            win.cols_spin.setValue(3)
            win._on_extract()
            written = list(Path(d).glob("*.svg"))
            self.assertEqual(len(written), 9)

    def test_auto_detect_seeds_three_by_three(self):
        win = self._prepared_window()
        win._on_auto_detect()
        self.assertEqual(win.rows_spin.value(), 3)
        self.assertEqual(win.cols_spin.value(), 3)

    def test_failed_capture_shows_status(self):
        from eps2svg_gui.split_window import SplitWindow
        win = SplitWindow(Path("nope.eps"), autostart=False)
        win._on_failed("boom")
        self.assertIn("boom", win.status_label.text())
