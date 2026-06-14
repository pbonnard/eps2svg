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

    def test_previewing_non_done_row_clears_stale_svg(self):
        from eps2svg_gui.main_window import MainWindow
        from eps2svg_gui.convert_worker import ConvertTask
        from eps2svg_gui.file_list import FileRow
        with tempfile.TemporaryDirectory() as d:
            w = MainWindow()
            results = []
            task = ConvertTask(0, FIXTURES / "grid_3x3.eps", output_dir=d)
            task.signals.finished.connect(lambda *a: results.append(a))
            task.run()
            done = w._append_row(FileRow(src=FIXTURES / "grid_3x3.eps"))
            w._on_finished(done, True, results[0][2], "Pure Python")
            w._preview_row(done)
            self.assertIsNotNone(w.preview._item)
            err = w._append_row(FileRow(src=Path("bad.eps")))
            w._on_finished(err, False, "", "boom")
            w._preview_row(err)
            self.assertIsNone(w.preview._item)

    def test_done_row_has_no_tooltip(self):
        from eps2svg_gui.main_window import MainWindow
        from eps2svg_gui.file_list import FileRow
        w = MainWindow()
        rid = w._append_row(FileRow(src=Path("logo.eps")))
        w._on_finished(rid, True, "logo.svg", "Pure Python")
        self.assertEqual(w.list_widget.item(rid).toolTip(), "")

    def test_fit_and_one_to_one_buttons_present_and_clickable(self):
        # The buttons are now icon-only (label moved to the tooltip), so they
        # are located by objectName rather than visible text.
        from eps2svg_gui.main_window import MainWindow
        w = MainWindow()
        self.assertFalse(w.fit_btn.icon().isNull())
        self.assertFalse(w.one_to_one_btn.icon().isNull())
        self.assertEqual(w.fit_btn.text(), "")
        self.assertEqual(w.one_to_one_btn.text(), "")
        # Clicking with no SVG loaded must not raise.
        w.fit_btn.click()
        w.one_to_one_btn.click()

    def test_split_button_enabled_only_with_selection(self):
        from eps2svg_gui.main_window import MainWindow
        from eps2svg_gui.file_list import FileRow
        w = MainWindow()
        self.assertFalse(w.split_btn.isEnabled())
        w._append_row(FileRow(src=Path("logo.eps")))
        w.list_widget.setCurrentRow(0)
        self.assertTrue(w.split_btn.isEnabled())

    def test_format_selector_defaults_to_svg(self):
        from eps2svg_gui.main_window import MainWindow
        w = MainWindow()
        self.assertEqual(w.output_format, "svg")
        w.format_combo.setCurrentText("PPTX")
        self.assertEqual(w.output_format, "pptx")

    def test_action_toolbar_fits_default_window(self):
        # Regression: the toolbar holding the action buttons must not exceed
        # the default window width, else the rightmost button is pushed into the
        # overflow chevron and is invisible.
        from eps2svg_gui.main_window import MainWindow
        from PySide6.QtWidgets import QToolBar
        w = MainWindow()
        w.resize(1000, 640)
        action_bar = next(b for b in w.findChildren(QToolBar)
                          if b.isAncestorOf(w.split_btn))
        self.assertLessEqual(action_bar.sizeHint().width(), w.width())


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class MainWindowEndToEndTests(unittest.TestCase):
    def _wait_until_done(self, w, app, timeout=8.0):
        from eps2svg_gui.file_list import RowStatus
        waited = 0.0
        while waited < timeout and w.rows[0].status not in (
            RowStatus.DONE,
            RowStatus.ERROR,
        ):
            app.processEvents()
            time.sleep(0.02)
            waited += 0.02

    def test_add_only_queues_then_convert_makes_svg(self):
        from eps2svg_gui.main_window import MainWindow
        from eps2svg_gui.file_list import RowStatus
        app = ensure_qapp()
        with tempfile.TemporaryDirectory() as d:
            w = MainWindow()
            w.set_output_dir(d)
            w.add_paths([str(FIXTURES / "grid_3x3.eps")])
            # Adding only queues — nothing is converted yet.
            self.assertEqual(len(w.rows), 1)
            self.assertEqual(w.rows[0].status, RowStatus.QUEUED)
            w._convert_all()
            self._wait_until_done(w, app)
            self.assertEqual(w.rows[0].status, RowStatus.DONE, msg=w.rows[0].message)
            self.assertTrue(w.rows[0].out_path.endswith(".svg"))
            self.assertTrue(Path(w.rows[0].out_path).exists())

    def test_add_paths_filters_unsupported(self):
        from eps2svg_gui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as d:
            junk = Path(d) / "note.txt"
            junk.write_text("x")
            w = MainWindow()
            w.add_paths([str(junk)])
            self.assertEqual(len(w.rows), 0)

    def test_convert_in_pptx_format_makes_pptx(self):
        from eps2svg_gui.main_window import MainWindow
        from eps2svg_gui.file_list import RowStatus
        app = ensure_qapp()
        with tempfile.TemporaryDirectory() as d:
            w = MainWindow()
            w.set_output_dir(d)
            w.format_combo.setCurrentText("PPTX")
            w.add_paths([str(FIXTURES / "grid_3x3.eps")])
            w._convert_all()
            self._wait_until_done(w, app)
            self.assertEqual(w.rows[0].status, RowStatus.DONE, msg=w.rows[0].message)
            self.assertTrue(w.rows[0].out_path.endswith(".pptx"))
            self.assertTrue((Path(d) / "grid_3x3.pptx").exists())

    def test_switching_format_then_convert_reconverts(self):
        from eps2svg_gui.main_window import MainWindow
        from eps2svg_gui.file_list import RowStatus
        app = ensure_qapp()
        with tempfile.TemporaryDirectory() as d:
            w = MainWindow()
            w.set_output_dir(d)
            w.add_paths([str(FIXTURES / "grid_3x3.eps")])
            w._convert_all()                 # SVG
            self._wait_until_done(w, app)
            self.assertTrue(w.rows[0].out_path.endswith(".svg"))
            w.format_combo.setCurrentText("PPTX")
            w._convert_all()                 # re-convert to PPTX
            waited = 0.0
            while waited < 8.0 and not w.rows[0].out_path.endswith(".pptx"):
                app.processEvents()
                time.sleep(0.02)
                waited += 0.02
            self.assertEqual(w.rows[0].status, RowStatus.DONE, msg=w.rows[0].message)
            self.assertTrue(w.rows[0].out_path.endswith(".pptx"))

    def test_pptx_row_still_previews_as_svg(self):
        from eps2svg_gui.main_window import MainWindow
        app = ensure_qapp()
        with tempfile.TemporaryDirectory() as d:
            w = MainWindow()
            w.set_output_dir(d)
            w.format_combo.setCurrentText("PPTX")
            w.add_paths([str(FIXTURES / "grid_3x3.eps")])
            w._convert_all()
            self._wait_until_done(w, app)
            # Output is PPTX, so the preview lazily renders an SVG instead.
            w._preview_row(0)
            waited = 0.0
            while waited < 8.0 and not w.rows[0].preview_svg:
                app.processEvents()
                time.sleep(0.02)
                waited += 0.02
            self.assertTrue(w.rows[0].preview_svg.endswith(".svg"))
            self.assertTrue(Path(w.rows[0].preview_svg).exists())
