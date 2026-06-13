import unittest


class PackageSmokeTests(unittest.TestCase):
    def test_package_imports(self):
        import eps2svg_gui
        self.assertTrue(hasattr(eps2svg_gui, "__version__"))

    def test_pyside6_available(self):
        import PySide6  # noqa: F401
        from PySide6.QtWidgets import QApplication  # noqa: F401
