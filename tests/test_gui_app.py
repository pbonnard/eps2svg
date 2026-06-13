import unittest

HAVE_QT = True
try:
    from tests.qt_app import ensure_qapp
except Exception:
    HAVE_QT = False


def setUpModule():
    if HAVE_QT:
        ensure_qapp()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class AppEntryTests(unittest.TestCase):
    def test_main_is_callable(self):
        from eps2svg_gui.app import main
        self.assertTrue(callable(main))

    def test_build_window_returns_mainwindow(self):
        from eps2svg_gui.app import build_window
        from eps2svg_gui.main_window import MainWindow
        ensure_qapp()
        win = build_window()
        self.assertIsInstance(win, MainWindow)
