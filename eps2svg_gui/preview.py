"""SVG preview pane: a QGraphicsView showing one QGraphicsSvgItem over a
checkerboard background (so transparent regions read as transparent)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView
from PySide6.QtSvgWidgets import QGraphicsSvgItem


class SvgPreview(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QBrush(self._checkerboard()))
        self._item = None

    @staticmethod
    def _checkerboard(tile: int = 12) -> QPixmap:
        pm = QPixmap(tile * 2, tile * 2)
        pm.fill(QColor("#ffffff"))
        painter = QPainter(pm)
        dark = QColor("#e6e6e6")
        painter.fillRect(0, 0, tile, tile, dark)
        painter.fillRect(tile, tile, tile, tile, dark)
        painter.end()
        return pm

    def load(self, svg_path) -> bool:
        """Render `svg_path`. Returns False if it is missing/invalid."""
        self.clear()
        item = QGraphicsSvgItem(str(svg_path))
        renderer = item.renderer()
        if renderer is None or not renderer.isValid():
            return False
        self._item = item
        self._scene.addItem(item)
        self._scene.setSceneRect(item.boundingRect())
        self.fit()
        return True

    def fit(self) -> None:
        if self._item is not None:
            self.resetTransform()
            self.fitInView(self._item, Qt.KeepAspectRatio)

    def actual_size(self) -> None:
        self.resetTransform()

    def clear(self) -> None:
        self._scene.clear()
        self._item = None

    def wheelEvent(self, event):  # Ctrl+wheel to zoom, plain wheel scrolls
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.25 if event.angleDelta().y() > 0 else 0.8
            self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)
