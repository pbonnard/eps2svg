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

    def test_zoom_controls_present_and_change_transform(self):
        win = self._prepared_window()
        # Icon-only buttons (labels live on the tooltip).
        self.assertFalse(win.fit_btn.icon().isNull())
        self.assertFalse(win.one_to_one_btn.icon().isNull())
        self.assertEqual(win.fit_btn.text(), "")
        self.assertEqual(win.one_to_one_btn.text(), "")
        # 1:1 resets to identity; zoom scales relative to current.
        win._actual_size()
        self.assertAlmostEqual(win.view.transform().m11(), 1.0)
        win._zoom(1.25)
        self.assertAlmostEqual(win.view.transform().m11(), 1.25)
        win._zoom(0.8)
        self.assertAlmostEqual(win.view.transform().m11(), 1.0)
        # Fit must not raise.
        win.fit_btn.click()

    def test_format_selector_defaults_to_svg_and_toggles_name_edit(self):
        win = self._prepared_window()
        self.assertEqual(win.output_format, "svg")
        self.assertTrue(win.name_edit.isEnabled())
        win.fmt_combo.setCurrentText("PPTX")
        self.assertEqual(win.output_format, "pptx")
        self.assertFalse(win.name_edit.isEnabled())

    def test_extract_pptx_writes_single_deck(self):
        import io
        import zipfile
        with tempfile.TemporaryDirectory() as d:
            win = self._prepared_window(output_dir=d)
            win.rows_spin.setValue(3)
            win.cols_spin.setValue(3)
            win.fmt_combo.setCurrentText("PPTX")
            win._on_extract()
            decks = list(Path(d).glob("*.pptx"))
            self.assertEqual(len(decks), 1)
            self.assertFalse(list(Path(d).glob("*.svg")))
            zf = zipfile.ZipFile(io.BytesIO(decks[0].read_bytes()))
            slides = [n for n in zf.namelist()
                      if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
            self.assertEqual(len(slides), 9)

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

    def test_extract_into_nonempty_dir_declined_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "keep.txt").write_text("x")
            win = self._prepared_window(output_dir=d)
            win.rows_spin.setValue(3)
            win.cols_spin.setValue(3)
            win._ask_overwrite = lambda out_dir: False  # user declines
            win._on_extract()
            self.assertEqual(list(Path(d).glob("*.svg")), [])
            self.assertIn("cancelled", win.status_label.text())

    def test_extract_into_nonempty_dir_confirmed_forces_write(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "keep.txt").write_text("x")
            win = self._prepared_window(output_dir=d)
            win.rows_spin.setValue(3)
            win.cols_spin.setValue(3)
            win._ask_overwrite = lambda out_dir: True  # user confirms
            win._on_extract()
            self.assertEqual(len(list(Path(d).glob("*.svg"))), 9)
