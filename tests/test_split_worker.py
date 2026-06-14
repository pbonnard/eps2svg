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
class PrepareTaskTests(unittest.TestCase):
    def test_prepare_emits_ready_with_document(self):
        from eps2svg_gui.split_worker import PrepareTask
        captured = []
        task = PrepareTask(FIXTURES / "grid_3x3.eps")
        task.signals.ready.connect(lambda doc: captured.append(doc))
        task.signals.failed.connect(lambda msg: captured.append(RuntimeError(msg)))
        task.run()
        self.assertEqual(len(captured), 1)
        doc = captured[0]
        self.assertFalse(isinstance(doc, Exception))
        self.assertAlmostEqual(doc.width, 300.0, delta=0.5)

    def test_prepare_emits_failed_on_missing_file(self):
        from eps2svg_gui.split_worker import PrepareTask
        captured = []
        task = PrepareTask(Path("does_not_exist.eps"))
        task.signals.ready.connect(lambda doc: captured.append(("ready", doc)))
        task.signals.failed.connect(lambda msg: captured.append(("failed", msg)))
        task.run()
        self.assertEqual(captured[0][0], "failed")


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class AutoSplitTaskTests(unittest.TestCase):
    def test_auto_split_writes_icons(self):
        from eps2svg_gui.split_worker import AutoSplitTask
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "icons"
            captured = []
            task = AutoSplitTask(FIXTURES / "grid_3x3.eps", out, force=True)
            task.signals.finished.connect(lambda ok, msg: captured.append((ok, msg)))
            task.run()
            self.assertEqual(len(captured), 1)
            ok, msg = captured[0]
            self.assertTrue(ok, msg)
            self.assertTrue(any(out.glob("*.svg")))

    def test_auto_split_pptx_writes_deck(self):
        from eps2svg_gui.split_worker import AutoSplitTask
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "icons"
            captured = []
            task = AutoSplitTask(FIXTURES / "grid_3x3.eps", out, force=True,
                                 fmt="pptx")
            task.signals.finished.connect(lambda ok, msg: captured.append((ok, msg)))
            task.run()
            ok, msg = captured[0]
            self.assertTrue(ok, msg)
            self.assertEqual(len(list(out.glob("*.pptx"))), 1)
            self.assertFalse(any(out.glob("*.svg")))
