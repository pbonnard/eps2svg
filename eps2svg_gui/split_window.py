"""The Split window: page canvas + grid overlay + extraction controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QThreadPool
from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

import eps2svg_grid
from eps2svg_gui.grid_model import GridSpec
from eps2svg_gui.grid_overlay import GridOverlay
from eps2svg_gui.icons import icon
from eps2svg_gui.split_worker import AutoSplitTask, PrepareTask

_DEFAULT_NAME = "{stem}-{index:03d}.svg"
_TOOLBAR_ICON_SIZE = QSize(20, 20)


def _icon_button(name: str, tooltip: str) -> QPushButton:
    """An icon-only button whose former label lives on as a tooltip."""
    btn = QPushButton(icon(name), "")
    btn.setToolTip(tooltip)
    btn.setIconSize(_TOOLBAR_ICON_SIZE)
    return btn


class _PageView(QGraphicsView):
    """Page canvas with Ctrl+wheel zoom (plain wheel scrolls).

    Drag mode is left at the default ``NoDrag`` so the grid overlay keeps
    receiving mouse events for moving/resizing the grid; panning when zoomed in
    is via the scrollbars.
    """

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.25 if event.angleDelta().y() > 0 else 0.8
            self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)


def _checkerboard(tile: int = 12) -> QPixmap:
    pm = QPixmap(tile * 2, tile * 2)
    pm.fill(QColor("#ffffff"))
    painter = QPainter(pm)
    painter.fillRect(0, 0, tile, tile, QColor("#e6e6e6"))
    painter.fillRect(tile, tile, tile, tile, QColor("#e6e6e6"))
    painter.end()
    return pm


class SplitWindow(QMainWindow):
    def __init__(self, src, output_dir=None, page=None, autostart=True, parent=None):
        super().__init__(parent)
        self.src = Path(src)
        self.output_dir = Path(output_dir) if output_dir else None
        self.page = page
        self.doc = None
        self.overlay = None
        self._renderer = None
        self._svg_item = None
        self.pool = QThreadPool(self)

        self.setWindowTitle(f"Split: {self.src.name}")
        self.resize(1000, 680)
        self._build_ui()

        if autostart:
            self._start_prepare()

    # ---- UI --------------------------------------------------------------

    def _build_ui(self):
        bar = QToolBar()
        bar.setMovable(False)
        self.addToolBar(bar)
        bar.addWidget(QLabel("Rows"))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 100)
        self.rows_spin.setValue(4)
        self.rows_spin.valueChanged.connect(self._on_grid_size_changed)
        bar.addWidget(self.rows_spin)
        bar.addWidget(QLabel("Cols"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 100)
        self.cols_spin.setValue(5)
        self.cols_spin.valueChanged.connect(self._on_grid_size_changed)
        bar.addWidget(self.cols_spin)
        auto_grid = _icon_button("auto_detect", "Auto-detect grid")
        auto_grid.clicked.connect(self._on_auto_detect)
        bar.addWidget(auto_grid)
        self.ignore_bg = QCheckBox("Ignore background")
        self.ignore_bg.stateChanged.connect(self._update_count)
        bar.addWidget(self.ignore_bg)

        self.scene = QGraphicsScene(self)
        self.view = _PageView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setBackgroundBrush(QBrush(_checkerboard()))

        out_panel = QWidget()
        out_layout = QVBoxLayout(out_panel)
        out_layout.addWidget(QLabel("Output folder:"))
        self.folder_label = QLabel(str(self._resolve_out_dir()))
        self.folder_label.setWordWrap(True)
        out_layout.addWidget(self.folder_label)
        change = _icon_button("folder", "Change output folder…")
        change.clicked.connect(self._choose_output_dir)
        out_layout.addWidget(change)
        out_layout.addWidget(QLabel("Name pattern:"))
        self.name_edit = QLineEdit(_DEFAULT_NAME)
        self.name_edit.setToolTip("Placeholders: {stem}, {index}, {row}, {col}")
        out_layout.addWidget(self.name_edit)
        self.count_label = QLabel("Cells with content: -")
        out_layout.addWidget(self.count_label)
        out_layout.addStretch(1)

        # View + zoom controls row (mirrors the main window's preview controls).
        view_panel = QWidget()
        view_layout = QVBoxLayout(view_panel)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.addWidget(self.view, stretch=1)

        zoom_row = QHBoxLayout()
        zoom_row.setContentsMargins(0, 0, 0, 0)
        self.fit_btn = _icon_button("fit", "Fit to view")
        self.fit_btn.setObjectName("fit_btn")
        self.fit_btn.clicked.connect(self._fit)
        self.one_to_one_btn = _icon_button("one_to_one", "Actual size (1:1)")
        self.one_to_one_btn.setObjectName("one_to_one_btn")
        self.one_to_one_btn.clicked.connect(self._actual_size)
        zoom_out_btn = _icon_button("zoom_out", "Zoom out")
        zoom_out_btn.clicked.connect(lambda: self._zoom(0.8))
        zoom_in_btn = _icon_button("zoom_in", "Zoom in")
        zoom_in_btn.clicked.connect(lambda: self._zoom(1.25))
        zoom_row.addWidget(self.fit_btn)
        zoom_row.addWidget(self.one_to_one_btn)
        zoom_row.addWidget(zoom_out_btn)
        zoom_row.addWidget(zoom_in_btn)
        zoom_row.addStretch(1)
        view_layout.addLayout(zoom_row)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(view_panel, stretch=1)
        layout.addWidget(out_panel)
        self.setCentralWidget(central)

        self.status_label = QLabel("")
        self.statusBar().addWidget(self.status_label)
        auto_split = _icon_button("scissors", "Auto-split now")
        auto_split.clicked.connect(self._on_auto_split)
        self.statusBar().addPermanentWidget(auto_split)
        extract = QPushButton(icon("extract"), "Extract")
        extract.clicked.connect(self._on_extract)
        self.statusBar().addPermanentWidget(extract)

    # ---- preparation -----------------------------------------------------

    def _start_prepare(self):
        self._set_status("rendering...")
        task = PrepareTask(self.src, page=self.page)
        task.signals.ready.connect(self._on_ready)
        task.signals.failed.connect(self._on_failed)
        self.pool.start(task)

    def _on_ready(self, doc):
        self.doc = doc
        self.scene.clear()
        self.overlay = None
        self._renderer = QSvgRenderer(QByteArray(doc.page_svg.encode("utf-8")))
        self._svg_item = QGraphicsSvgItem()
        self._svg_item.setSharedRenderer(self._renderer)
        self.scene.addItem(self._svg_item)
        self.scene.setSceneRect(0, 0, doc.width, doc.height)
        self._rebuild_overlay((0, 0, doc.width, doc.height))
        self._fit()
        self._set_status("page ready")

    def _on_failed(self, message):
        self._set_status(f"error: {message}")

    # ---- zoom ------------------------------------------------------------

    def _fit(self):
        self.view.resetTransform()
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def _actual_size(self):
        self.view.resetTransform()

    def _zoom(self, factor):
        self.view.scale(factor, factor)

    # ---- grid editing ----------------------------------------------------

    def _rebuild_overlay(self, frame):
        spec = GridSpec.uniform(frame, self.rows_spin.value(), self.cols_spin.value())
        if self.overlay is not None:
            self.scene.removeItem(self.overlay)
        self.overlay = GridOverlay(spec)
        self.overlay.changed.connect(self._update_count)
        self.scene.addItem(self.overlay)
        self._update_count()

    def _on_grid_size_changed(self):
        if self.doc is None or self.overlay is None:
            return
        self._rebuild_overlay(self.overlay.spec().frame)

    def _on_auto_detect(self):
        if self.doc is None:
            return
        suggestion = self.doc.suggest_grid()
        if suggestion is None:
            self._set_status("auto-detect: nothing found")
            return
        rows, cols, frame = suggestion
        self.rows_spin.blockSignals(True)
        self.cols_spin.blockSignals(True)
        self.rows_spin.setValue(rows)
        self.cols_spin.setValue(cols)
        self.rows_spin.blockSignals(False)
        self.cols_spin.blockSignals(False)
        self._rebuild_overlay(frame)
        self._set_status(f"auto-detected {rows}x{cols}")

    def _current_cells(self):
        return self.overlay.spec().cell_rects() if self.overlay else []

    def _update_count(self):
        if self.doc is None or self.overlay is None:
            return
        cells = self._current_cells()
        n = self.doc.content_cell_count(
            cells, ignore_background=self.ignore_bg.isChecked()
        )
        self.count_label.setText(f"Cells with content: {n} / {len(cells)}")

    # ---- output ----------------------------------------------------------

    def _resolve_out_dir(self) -> Path:
        if self.output_dir:
            return self.output_dir
        return self.src.with_suffix("").parent / f"{self.src.stem}-icons"

    def _choose_output_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Output folder")
        if folder:
            self.output_dir = Path(folder)
            self.folder_label.setText(str(self.output_dir))

    def _on_extract(self):
        if self.doc is None:
            self._set_status("nothing to extract yet")
            return
        out_dir = self._resolve_out_dir()
        cells = self._current_cells()
        pattern = self.name_edit.text() or _DEFAULT_NAME
        ignore = self.ignore_bg.isChecked()
        try:
            written = eps2svg_grid.write_grid(
                self.doc, out_dir, cells, name_pattern=pattern,
                ignore_background=ignore, stem=self.src.stem,
            )
        except FileExistsError:
            if not self._ask_overwrite(out_dir):
                self._set_status("cancelled")
                return
            written = eps2svg_grid.write_grid(
                self.doc, out_dir, cells, name_pattern=pattern,
                ignore_background=ignore, stem=self.src.stem, force=True,
            )
        except Exception as exc:
            self._set_status(f"error: {exc}")
            return
        self._set_status(f"wrote {len(written)} icon(s) to {out_dir}")

    def _ask_overwrite(self, out_dir) -> bool:
        answer = QMessageBox.question(
            self, "Overwrite?",
            f"{out_dir} is not empty. Write icons into it anyway?",
        )
        return answer == QMessageBox.Yes

    def _on_auto_split(self):
        out_dir = self._resolve_out_dir()
        # "Ignore background" maps to run_split's grid/lattice mode, which drops
        # page-spanning shapes (and snaps clusters to a lattice) — intentional:
        # that mode subsumes background filtering for the auto-detect path.
        task = AutoSplitTask(self.src, out_dir, grid=self.ignore_bg.isChecked(),
                             force=True)
        task.signals.finished.connect(
            lambda ok, msg: self._set_status(msg if ok else f"error: {msg}")
        )
        self._set_status("auto-splitting...")
        self.pool.start(task)

    def _set_status(self, text):
        self.status_label.setText(text)
