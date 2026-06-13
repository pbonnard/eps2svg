"""Off-thread tasks for the split window: page capture and one-click auto-split."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

import eps2svg_grid


class PrepareSignals(QObject):
    ready = Signal(object)   # SplitDocument
    failed = Signal(str)


class PrepareTask(QRunnable):
    def __init__(self, src, page=None):
        super().__init__()
        self.src = Path(src)
        self.page = page
        self.signals = PrepareSignals()

    def run(self) -> None:
        try:
            doc = eps2svg_grid.prepare_split(self.src, page=self.page)
            self.signals.ready.emit(doc)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class AutoSplitSignals(QObject):
    finished = Signal(bool, str)   # ok, message (mode/count, or error)


class AutoSplitTask(QRunnable):
    def __init__(self, src, out_dir, *, grid=False, force=False):
        super().__init__()
        self.src = Path(src)
        self.out_dir = Path(out_dir)
        self.grid = grid
        self.force = force
        self.signals = AutoSplitSignals()

    def run(self) -> None:
        try:
            from eps2svg_split import run_split
            result = run_split(self.src, self.out_dir, grid=self.grid,
                               force=self.force)
            self.signals.finished.emit(
                True, f"{result.mode}: {result.icon_count} icon(s)"
            )
        except Exception as exc:
            self.signals.finished.emit(False, str(exc))
