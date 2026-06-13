"""Off-thread PPTX export task for the desktop GUI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from eps2pptx import convert_eps_to_pptx


class PptxExportSignals(QObject):
    finished = Signal(bool, str)   # ok, message (status or error)


class PptxExportTask(QRunnable):
    def __init__(self, src, dst):
        super().__init__()
        self.src = Path(src)
        self.dst = Path(dst)
        self.signals = PptxExportSignals()

    def run(self) -> None:
        try:
            status = convert_eps_to_pptx(self.src, self.dst)
            self.signals.finished.emit(True, f"{status} -> {self.dst}")
        except Exception as exc:
            self.signals.finished.emit(False, str(exc))
