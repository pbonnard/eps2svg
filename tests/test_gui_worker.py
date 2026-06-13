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
class ConvertTaskTests(unittest.TestCase):
    def _run(self, src, output_dir):
        from eps2svg_gui.convert_worker import ConvertTask
        results = []
        task = ConvertTask(7, src, output_dir=output_dir)
        task.signals.finished.connect(lambda *a: results.append(a))
        task.run()
        self.assertEqual(len(results), 1)
        return results[0]

    def test_converts_fixture_to_nonempty_svg(self):
        with tempfile.TemporaryDirectory() as d:
            row_id, ok, out_path, message = self._run(FIXTURES / "grid_3x3.eps", d)
            self.assertEqual(row_id, 7)
            self.assertTrue(ok, msg=message)
            self.assertTrue(Path(out_path).exists())
            self.assertGreater(Path(out_path).stat().st_size, 0)

    def test_missing_source_reports_error(self):
        with tempfile.TemporaryDirectory() as d:
            row_id, ok, out_path, message = self._run(Path(d) / "nope.eps", d)
            self.assertFalse(ok)
            self.assertEqual(out_path, "")
            self.assertTrue(message)
