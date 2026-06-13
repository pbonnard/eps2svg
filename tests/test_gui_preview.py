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


def _make_svg(dirpath) -> str:
    """Convert a fixture EPS to a real SVG and return its path."""
    from eps2svg_gui.convert_worker import ConvertTask
    results = []
    task = ConvertTask(0, FIXTURES / "grid_3x3.eps", output_dir=dirpath)
    task.signals.finished.connect(lambda *a: results.append(a))
    task.run()
    return results[0][2]


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class SvgPreviewTests(unittest.TestCase):
    def test_load_valid_svg_returns_true(self):
        from eps2svg_gui.preview import SvgPreview
        with tempfile.TemporaryDirectory() as d:
            svg = _make_svg(d)
            view = SvgPreview()
            self.assertTrue(view.load(svg))

    def test_load_missing_returns_false(self):
        from eps2svg_gui.preview import SvgPreview
        view = SvgPreview()
        self.assertFalse(view.load("definitely_not_here.svg"))

    def test_clear_after_load(self):
        from eps2svg_gui.preview import SvgPreview
        with tempfile.TemporaryDirectory() as d:
            svg = _make_svg(d)
            view = SvgPreview()
            view.load(svg)
            view.clear()
            self.assertIsNone(view._item)
