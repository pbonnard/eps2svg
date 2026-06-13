"""Main window: file list + SVG preview, drag-drop, threaded conversion."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from eps2svg_gui.convert_worker import ConvertTask
from eps2svg_gui.file_list import FileRow, RowStatus, row_label
from eps2svg_gui.paths import enumerate_inputs
from eps2svg_gui.preview import SvgPreview

_NEXT_TO_SOURCE = "Next to source"


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("eps2svg — EPS/PS → SVG")
        self.resize(1000, 640)
        self.setAcceptDrops(True)

        self.rows: list[FileRow] = []
        self.output_dir: Path | None = None

        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(min(4, os.cpu_count() or 1))

        self._build_toolbar()
        self._build_central()
        self._update_status_bar()

    # ---- UI construction -------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = QToolBar()
        bar.setMovable(False)
        self.addToolBar(bar)

        add_files = QPushButton("Add Files…")
        add_files.clicked.connect(self._choose_files)
        bar.addWidget(add_files)

        add_folder = QPushButton("Add Folder…")
        add_folder.clicked.connect(self._choose_folder)
        bar.addWidget(add_folder)

        self.recurse_checkbox = QCheckBox("Recurse")
        bar.addWidget(self.recurse_checkbox)

        bar.addSeparator()
        bar.addWidget(QLabel("Output:"))
        self.output_label = QLabel(_NEXT_TO_SOURCE)
        bar.addWidget(self.output_label)
        change = QPushButton("Change…")
        change.clicked.connect(self._choose_output_dir)
        bar.addWidget(change)

    def _build_central(self) -> None:
        splitter = QSplitter(Qt.Horizontal)

        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.list_widget)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = SvgPreview()
        right_layout.addWidget(self.preview)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        fit_btn = QPushButton("Fit")
        fit_btn.clicked.connect(lambda: self.preview.fit())
        one_to_one_btn = QPushButton("1:1")
        one_to_one_btn.clicked.connect(lambda: self.preview.actual_size())
        controls.addWidget(fit_btn)
        controls.addWidget(one_to_one_btn)
        controls.addStretch(1)
        right_layout.addLayout(controls)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 680])

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        convert_btn = QPushButton("Convert")
        convert_btn.clicked.connect(self._convert_all)
        self.statusBar().addPermanentWidget(convert_btn)

    # ---- file intake -----------------------------------------------------

    def _choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add EPS/PS files", "", "EPS/PS (*.eps *.ps *.epsf)"
        )
        if files:
            self.add_paths(files)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add folder")
        if folder:
            self.add_paths([folder])

    def _choose_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Output folder")
        self.set_output_dir(folder or None)

    def set_output_dir(self, path) -> None:
        self.output_dir = Path(path) if path else None
        self.output_label.setText(
            str(self.output_dir) if self.output_dir else _NEXT_TO_SOURCE
        )

    def add_paths(self, paths) -> None:
        for src in enumerate_inputs(paths, recursive=self.recurse_checkbox.isChecked()):
            rid = self._append_row(FileRow(src=src))
            self._submit(rid)

    # ---- row + threading -------------------------------------------------

    def _append_row(self, row: FileRow) -> int:
        rid = len(self.rows)
        self.rows.append(row)
        self.list_widget.addItem(QListWidgetItem(row_label(row)))
        self._update_status_bar()
        return rid

    def _submit(self, row_id: int) -> None:
        row = self.rows[row_id]
        row.status = RowStatus.CONVERTING
        self._refresh_item(row_id)
        out_dir = str(self.output_dir) if self.output_dir else None
        task = ConvertTask(row_id, row.src, output_dir=out_dir)
        task.signals.finished.connect(self._on_finished)
        self.pool.start(task)

    def _convert_all(self) -> None:
        for row_id, row in enumerate(self.rows):
            if row.status in (RowStatus.QUEUED, RowStatus.ERROR):
                self._submit(row_id)

    def _on_finished(self, row_id: int, ok: bool, out_path: str, message: str) -> None:
        row = self.rows[row_id]
        if ok:
            row.status = RowStatus.DONE
            row.out_path = out_path
            row.message = message
        else:
            row.status = RowStatus.ERROR
            row.message = message
        self._refresh_item(row_id)
        self._update_status_bar()
        if ok and (self.list_widget.currentRow() == row_id or len(self.rows) == 1):
            self._preview_row(row_id)

    # ---- preview + status ------------------------------------------------

    def _on_selection_changed(self, current_row: int) -> None:
        if 0 <= current_row < len(self.rows):
            self._preview_row(current_row)

    def _preview_row(self, row_id: int) -> None:
        row = self.rows[row_id]
        if row.status == RowStatus.DONE and row.out_path:
            self.preview.load(row.out_path)
        else:
            self.preview.clear()

    def _refresh_item(self, row_id: int) -> None:
        item = self.list_widget.item(row_id)
        row = self.rows[row_id]
        item.setText(row_label(row))
        # Only errors carry a hover message; on success row.message is the
        # backend name, which shouldn't linger as a tooltip (e.g. after a
        # failed row is re-converted successfully).
        item.setToolTip(row.message if row.status is RowStatus.ERROR else "")

    def _update_status_bar(self) -> None:
        done = sum(1 for r in self.rows if r.status == RowStatus.DONE)
        err = sum(1 for r in self.rows if r.status == RowStatus.ERROR)
        self.statusBar().showMessage(
            f"{len(self.rows)} files · {done} done · {err} error"
        )

    # ---- drag and drop ---------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if paths:
            self.add_paths(paths)
