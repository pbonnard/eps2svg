"""The Split window: page canvas + grid overlay + extraction controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QThreadPool
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
from eps2svg_gui.split_worker import AutoSplitTask, PrepareTask

_DEFAULT_NAME = "{stem}-{index:03d}.svg"


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
        auto_grid = QPushButton("Auto-detect grid")
        auto_grid.clicked.connect(self._on_auto_detect)
        bar.addWidget(auto_grid)
        self.ignore_bg = QCheckBox("Ignore background")
        self.ignore_bg.stateChanged.connect(self._update_count)
        bar.addWidget(self.ignore_bg)

        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setBackgroundBrush(QBrush(_checkerboard()))

        out_panel = QWidget()
        out_layout = QVBoxLayout(out_panel)
        out_layout.addWidget(QLabel("Output folder:"))
        self.folder_label = QLabel(str(self._resolve_out_dir()))
        self.folder_label.setWordWrap(True)
        out_layout.addWidget(self.folder_label)
        change = QPushButton("Change...")
        change.clicked.connect(self._choose_output_dir)
        out_layout.addWidget(change)
        out_layout.addWidget(QLabel("Name pattern:"))
        self.name_edit = QLineEdit(_DEFAULT_NAME)
        self.name_edit.setToolTip("Placeholders: {stem}, {index}, {row}, {col}")
        out_layout.addWidget(self.name_edit)
        self.count_label = QLabel("Cells with content: -")
        out_layout.addWidget(self.count_label)
        out_layout.addStretch(1)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(self.view, stretch=1)
        layout.addWidget(out_panel)
        self.setCentralWidget(central)

        self.status_label = QLabel("")
        self.statusBar().addWidget(self.status_label)
        auto_split = QPushButton("Auto-split now")
        auto_split.clicked.connect(self._on_auto_split)
        self.statusBar().addPermanentWidget(auto_split)
        extract = QPushButton("Extract")
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
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self._set_status("page ready")

    def _on_failed(self, message):
        self._set_status(f"error: {message}")

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
