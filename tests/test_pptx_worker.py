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
class PptxExportTaskTests(unittest.TestCase):
    def test_export_writes_pptx(self):
        from eps2svg_gui.pptx_worker import PptxExportTask
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.pptx"
            captured = []
            task = PptxExportTask(FIXTURES / "grid_3x3.eps", out)
            task.signals.finished.connect(lambda ok, msg: captured.append((ok, msg)))
            task.run()
            self.assertEqual(len(captured), 1)
            ok, msg = captured[0]
            self.assertTrue(ok, msg)
            self.assertTrue(out.exists())

    def test_export_reports_error_on_missing_file(self):
        from eps2svg_gui.pptx_worker import PptxExportTask
        with tempfile.TemporaryDirectory() as d:
            captured = []
            task = PptxExportTask(Path("nope.eps"), Path(d) / "x.pptx")
            task.signals.finished.connect(lambda ok, msg: captured.append((ok, msg)))
            task.run()
            self.assertFalse(captured[0][0])
