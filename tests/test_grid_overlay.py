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
class GridOverlayTests(unittest.TestCase):
    def _overlay(self):
        from eps2svg_gui.grid_overlay import GridOverlay
        from eps2svg_gui.grid_model import GridSpec
        return GridOverlay(GridSpec.uniform((0, 0, 300, 300), 3, 3))

    def test_hit_corner(self):
        from PySide6.QtCore import QPointF
        ov = self._overlay()
        self.assertEqual(ov.hit(QPointF(0, 0)), ("corner", 0))
        self.assertEqual(ov.hit(QPointF(300, 300)), ("corner", 2))

    def test_hit_interior_column_line(self):
        from PySide6.QtCore import QPointF
        ov = self._overlay()
        self.assertEqual(ov.hit(QPointF(100, 150)), ("col", 0))

    def test_hit_body(self):
        from PySide6.QtCore import QPointF
        ov = self._overlay()
        self.assertEqual(ov.hit(QPointF(150, 150)), ("move",))

    def test_hit_outside_returns_none(self):
        from PySide6.QtCore import QPointF
        ov = self._overlay()
        self.assertIsNone(ov.hit(QPointF(-50, -50)))

    def test_set_spec_emits_changed(self):
        from eps2svg_gui.grid_model import GridSpec
        ov = self._overlay()
        seen = []
        ov.changed.connect(lambda: seen.append(1))
        ov.set_spec(GridSpec.uniform((10, 10, 310, 310), 2, 2))
        self.assertTrue(seen)
        self.assertEqual(ov.spec().frame, (10, 10, 310, 310))

    def test_resize_corner_returns_resized_spec(self):
        from PySide6.QtCore import QPointF
        ov = self._overlay()
        spec = ov.resize_corner(2, QPointF(150, 150))  # drag bottom-right inward
        self.assertEqual(spec.frame, (0, 0, 150, 150))
