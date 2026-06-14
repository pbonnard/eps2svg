"""Main window: file list + SVG preview, drag-drop, threaded conversion."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThreadPool
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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

import eps2svg
from eps2svg_gui.convert_worker import ConvertTask
from eps2svg_gui.file_list import FileRow, RowStatus, row_label
from eps2svg_gui.icons import icon
from eps2svg_gui.paths import enumerate_inputs, predict_backend
from eps2svg_gui.preview import SvgPreview

# Toolbar/utility buttons are icon-only; the label survives as a tooltip.
_TOOLBAR_ICON_SIZE = QSize(20, 20)

_NEXT_TO_SOURCE = "Next to source"


def _icon_button(name: str, tooltip: str) -> QPushButton:
    """An icon-only button whose former label lives on as a tooltip."""
    btn = QPushButton(icon(name), "")
    btn.setToolTip(tooltip)
    btn.setIconSize(_TOOLBAR_ICON_SIZE)
    return btn


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("eps2svg — EPS/PS → SVG")
        self.resize(1000, 640)
        self.setAcceptDrops(True)

        self.rows: list[FileRow] = []
        self.output_dir: Path | None = None
        self._split_windows: list = []
        self._next_id = 0
        # Cached once: whether Ghostscript is available (drives backend guesses).
        self._gs_available = bool(eps2svg._find_gs())
        # SVGs rendered solely for the preview pane (PPTX rows and not-yet-
        # converted rows still preview as artwork) live in this temp dir.
        self._preview_dir = Path(tempfile.mkdtemp(prefix="eps2svg-preview-"))

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

        add_files = _icon_button("add_files", "Add Files…")
        add_files.clicked.connect(self._choose_files)
        bar.addWidget(add_files)

        add_folder = _icon_button("add_folder", "Add Folder…")
        add_folder.clicked.connect(self._choose_folder)
        bar.addWidget(add_folder)

        self.remove_btn = _icon_button("remove", "Remove selected (Del)")
        self.remove_btn.setEnabled(False)
        self.remove_btn.clicked.connect(self._remove_selected)
        bar.addWidget(self.remove_btn)

        self.recurse_checkbox = QCheckBox("Recurse")
        bar.addWidget(self.recurse_checkbox)

        bar.addSeparator()
        self.split_btn = _icon_button("split", "Split…")
        self.split_btn.setEnabled(False)
        self.split_btn.clicked.connect(self._open_split)
        bar.addWidget(self.split_btn)

        # Output-destination controls live on a second toolbar row: the output
        # path can be long, so keeping it off the action row prevents the row
        # from overflowing and hiding the rightmost action button.
        self.addToolBarBreak()
        out_bar = QToolBar()
        out_bar.setMovable(False)
        self.addToolBar(out_bar)
        out_bar.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["SVG", "PPTX"])
        self.format_combo.setToolTip("Output format for Convert")
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        out_bar.addWidget(self.format_combo)
        out_bar.addSeparator()
        out_bar.addWidget(QLabel("Output:"))
        self.output_label = QLabel(_NEXT_TO_SOURCE)
        out_bar.addWidget(self.output_label)
        change = _icon_button("folder", "Change output folder…")
        change.clicked.connect(self._choose_output_dir)
        out_bar.addWidget(change)

    def _build_central(self) -> None:
        splitter = QSplitter(Qt.Horizontal)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)
        del_shortcut = QShortcut(QKeySequence.Delete, self.list_widget)
        del_shortcut.setContext(Qt.WidgetShortcut)
        del_shortcut.activated.connect(self._remove_selected)
        splitter.addWidget(self.list_widget)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = SvgPreview()
        right_layout.addWidget(self.preview)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        self.fit_btn = _icon_button("fit", "Fit to view")
        self.fit_btn.setObjectName("fit_btn")
        self.fit_btn.clicked.connect(lambda: self.preview.fit())
        self.one_to_one_btn = _icon_button("one_to_one", "Actual size (1:1)")
        self.one_to_one_btn.setObjectName("one_to_one_btn")
        self.one_to_one_btn.clicked.connect(lambda: self.preview.actual_size())
        controls.addWidget(self.fit_btn)
        controls.addWidget(self.one_to_one_btn)
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

        convert_btn = QPushButton(icon("convert"), "Convert")
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

    @property
    def output_format(self) -> str:
        """Selected output format: 'svg' or 'pptx'."""
        return self.format_combo.currentText().lower()

    def add_paths(self, paths) -> None:
        # Adding only queues; conversion happens on the Convert button, in the
        # currently-selected format.
        added = []
        for src in enumerate_inputs(paths, recursive=self.recurse_checkbox.isChecked()):
            added.append(self._append_row(FileRow(src=src)))
        if added and self.list_widget.currentRow() < 0:
            pos = self._pos(added[0])
            if pos is not None:
                self.list_widget.setCurrentRow(pos)

    # ---- row + threading -------------------------------------------------

    def _append_row(self, row: FileRow) -> int:
        row.rid = self._next_id
        self._next_id += 1
        self.rows.append(row)
        self._set_predicted(row)
        item = QListWidgetItem(row_label(row))
        item.setData(Qt.UserRole, row.rid)
        self.list_widget.addItem(item)
        self._update_status_bar()
        return row.rid

    # ---- id <-> position helpers ----------------------------------------

    def _find_row(self, rid: int) -> FileRow | None:
        return next((r for r in self.rows if r.rid == rid), None)

    def _pos(self, rid: int) -> int | None:
        for i, r in enumerate(self.rows):
            if r.rid == rid:
                return i
        return None

    def _current_rid(self) -> int | None:
        pos = self.list_widget.currentRow()
        return self.rows[pos].rid if 0 <= pos < len(self.rows) else None

    def _set_predicted(self, row: FileRow) -> None:
        row.backend, row.backend_predicted = predict_backend(
            row.src, self.output_format, self._gs_available
        )

    # ---- threading -------------------------------------------------------

    def _submit(self, rid: int) -> None:
        row = self._find_row(rid)
        if row is None:
            return
        row.status = RowStatus.CONVERTING
        row.fmt = self.output_format
        self._refresh_item(rid)
        out_dir = str(self.output_dir) if self.output_dir else None
        task = ConvertTask(rid, row.src, output_dir=out_dir, fmt=row.fmt)
        task.signals.finished.connect(self._on_finished)
        self.pool.start(task)

    def _convert_all(self) -> None:
        # Convert anything not already done in the currently-selected format:
        # queued/error rows, plus rows previously converted to a different
        # format (so switching SVG<->PPTX and clicking Convert re-runs them).
        fmt = self.output_format
        for row in list(self.rows):
            if row.status == RowStatus.CONVERTING:
                continue
            if row.status != RowStatus.DONE or row.fmt != fmt:
                self._submit(row.rid)

    def _on_finished(self, rid: int, ok: bool, out_path: str, message: str) -> None:
        row = self._find_row(rid)
        if row is None:  # removed while converting
            return
        if ok:
            row.status = RowStatus.DONE
            row.out_path = out_path
            row.message = message
            # Actual backend now known (PPTX always renders via pure-Python).
            row.backend = "Pure Python" if row.fmt == "pptx" else message.split(" (")[0]
            row.backend_predicted = False
        else:
            row.status = RowStatus.ERROR
            row.message = message
        self._refresh_item(rid)
        self._update_status_bar()
        if ok and (self._current_rid() == rid or len(self.rows) == 1):
            self._preview_row(rid)

    # ---- queue editing ---------------------------------------------------

    def _remove_selected(self) -> None:
        positions = sorted(
            {i.row() for i in self.list_widget.selectedIndexes()}, reverse=True
        )
        for pos in positions:
            if 0 <= pos < len(self.rows):
                del self.rows[pos]
                self.list_widget.takeItem(pos)
        if not self.rows:
            self.preview.clear()
        self._update_status_bar()

    def _on_format_changed(self, _text=None) -> None:
        # Re-predict rows that haven't successfully converted yet; done rows keep
        # the actual backend they produced until they are re-converted.
        for row in self.rows:
            if row.status in (RowStatus.QUEUED, RowStatus.ERROR):
                self._set_predicted(row)
                self._refresh_item(row.rid)

    # ---- preview + status ------------------------------------------------

    def _on_selection_changed(self, current_row: int) -> None:
        has_sel = 0 <= current_row < len(self.rows)
        self.split_btn.setEnabled(has_sel)
        self.remove_btn.setEnabled(has_sel)
        if has_sel:
            self._preview_row(self.rows[current_row].rid)

    def _preview_row(self, rid: int) -> None:
        row = self._find_row(rid)
        if row is None:
            return
        # A row converted to SVG already has a displayable SVG on disk.
        if (row.out_path.lower().endswith(".svg")
                and Path(row.out_path).exists()):
            self.preview.load(row.out_path)
            return
        # Otherwise (PPTX output, or not yet converted) display a cached SVG
        # render of the artwork, rendering it lazily on first preview.
        if row.preview_svg and Path(row.preview_svg).exists():
            self.preview.load(row.preview_svg)
            return
        self.preview.clear()
        self._render_preview(rid)

    def _render_preview(self, rid: int) -> None:
        row = self._find_row(rid)
        if row is None or not row.src.exists():
            return
        # Per-row subdir so two sources with the same stem can't clobber each
        # other's preview render.
        pdir = self._preview_dir / str(rid)
        pdir.mkdir(exist_ok=True)
        task = ConvertTask(rid, row.src, output_dir=str(pdir), fmt="svg")
        task.signals.finished.connect(self._on_preview_rendered)
        self.pool.start(task)

    def _on_preview_rendered(self, rid: int, ok: bool, out_path: str, message: str) -> None:
        if not ok:
            return
        row = self._find_row(rid)
        if row is None:
            return
        row.preview_svg = out_path
        # The preview render exercised the real SVG auto-chain — upgrade a
        # predicted SVG backend to the actual one it selected.
        if self.output_format == "svg" and row.backend_predicted:
            row.backend = message.split(" (")[0]
            row.backend_predicted = False
            self._refresh_item(rid)
        if self._current_rid() == rid:
            self.preview.load(out_path)

    def _open_split(self) -> None:
        row_id = self.list_widget.currentRow()
        if not (0 <= row_id < len(self.rows)):
            return
        from eps2svg_gui.split_window import SplitWindow
        win = SplitWindow(self.rows[row_id].src, output_dir=self.output_dir)
        self._split_windows.append(win)
        win.show()

    def _refresh_item(self, rid: int) -> None:
        pos = self._pos(rid)
        if pos is None:
            return
        row = self.rows[pos]
        item = self.list_widget.item(pos)
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
