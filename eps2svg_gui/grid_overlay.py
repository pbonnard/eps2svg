"""Interactive grid overlay drawn over the page SVG in the split window.

Holds a GridSpec (SVG-unit coordinates). Dragging the body moves the grid,
dragging a corner resizes it, dragging an interior line adjusts that line.
All mutations go through the pure grid_model functions; hit() and
resize_corner() are plain methods so they're testable without mouse events.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsObject

from eps2svg_gui import grid_model
from eps2svg_gui.grid_model import GridSpec

_FRAME_COLOR = QColor("#1e88e5")
_LINE_COLOR = QColor(30, 136, 229, 160)


class GridOverlay(QGraphicsObject):
    changed = Signal()

    def __init__(self, spec: GridSpec, parent=None):
        super().__init__(parent)
        self._spec = spec
        self._drag = None       # ("move",) | ("corner", i) | ("col", i) | ("row", i)
        self._last = None
        self.setZValue(10)

    # ---- state -----------------------------------------------------------

    def spec(self) -> GridSpec:
        return self._spec

    def set_spec(self, spec: GridSpec) -> None:
        self.prepareGeometryChange()
        self._spec = spec
        self.update()
        self.changed.emit()

    # ---- geometry helpers ------------------------------------------------

    def _tol(self) -> float:
        x0, y0, x1, y1 = self._spec.frame
        return max(6.0, min(abs(x1 - x0), abs(y1 - y0)) * 0.03)

    def _corners(self):
        x0, y0, x1, y1 = self._spec.frame
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def boundingRect(self) -> QRectF:
        x0, y0, x1, y1 = self._spec.frame
        m = self._tol()
        return QRectF(x0 - m, y0 - m, (x1 - x0) + 2 * m, (y1 - y0) + 2 * m)

    def hit(self, pos: QPointF):
        tol = self._tol()
        for i, (hx, hy) in enumerate(self._corners()):
            if abs(pos.x() - hx) <= tol and abs(pos.y() - hy) <= tol:
                return ("corner", i)
        x0, y0, x1, y1 = self._spec.frame
        for i, x in enumerate(sorted(self._spec.col_lines)):
            if abs(pos.x() - x) <= tol and y0 <= pos.y() <= y1:
                return ("col", i)
        for i, y in enumerate(sorted(self._spec.row_lines)):
            if abs(pos.y() - y) <= tol and x0 <= pos.x() <= x1:
                return ("row", i)
        if x0 <= pos.x() <= x1 and y0 <= pos.y() <= y1:
            return ("move",)
        return None

    def resize_corner(self, i: int, pos: QPointF) -> GridSpec:
        x0, y0, x1, y1 = self._spec.frame
        if i == 0:
            new = (pos.x(), pos.y(), x1, y1)
        elif i == 1:
            new = (x0, pos.y(), pos.x(), y1)
        elif i == 2:
            new = (x0, y0, pos.x(), pos.y())
        else:
            new = (pos.x(), y0, x1, pos.y())
        return grid_model.resized(self._spec, new)

    # ---- painting --------------------------------------------------------

    def paint(self, painter, option, widget=None):
        x0, y0, x1, y1 = self._spec.frame
        frame_pen = QPen(_FRAME_COLOR)
        frame_pen.setCosmetic(True)
        frame_pen.setWidth(2)
        painter.setPen(frame_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))

        line_pen = QPen(_LINE_COLOR)
        line_pen.setCosmetic(True)
        painter.setPen(line_pen)
        for x in self._spec.col_lines:
            painter.drawLine(QPointF(x, y0), QPointF(x, y1))
        for y in self._spec.row_lines:
            painter.drawLine(QPointF(x0, y), QPointF(x1, y))

        handle_pen = QPen(_FRAME_COLOR)
        handle_pen.setCosmetic(True)
        painter.setPen(handle_pen)
        painter.setBrush(QBrush(QColor("#ffffff")))
        r = self._tol()
        for hx, hy in self._corners():
            painter.drawRect(QRectF(hx - r / 2, hy - r / 2, r, r))

    # ---- mouse -----------------------------------------------------------

    def mousePressEvent(self, event):
        self._last = event.pos()
        self._drag = self.hit(event.pos())
        if self._drag is None:
            event.ignore()
        else:
            event.accept()

    def mouseMoveEvent(self, event):
        if not self._drag:
            return
        pos = event.pos()
        kind = self._drag[0]
        if kind == "move":
            dx = pos.x() - self._last.x()
            dy = pos.y() - self._last.y()
            self.set_spec(grid_model.translated(self._spec, dx, dy))
        elif kind == "corner":
            self.set_spec(self.resize_corner(self._drag[1], pos))
        elif kind == "col":
            self.set_spec(grid_model.with_col_line(self._spec, self._drag[1], pos.x()))
        elif kind == "row":
            self.set_spec(grid_model.with_row_line(self._spec, self._drag[1], pos.y()))
        self._last = pos

    def mouseReleaseEvent(self, event):
        self._drag = None
