"""Off-thread conversion task. Wraps the existing engine unchanged."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

import eps2svg
from eps2svg_gui.paths import resolve_output_path

# Fixed engine defaults for v1 (no advanced-options UI).
_DPI = 96
_TIMEOUT = 30.0
_MAX_OPS = 5_000_000


class WorkerSignals(QObject):
    # row_id, ok, out_path (str, "" on failure), message (backend name or error)
    finished = Signal(int, bool, str, str)
    # Note: this signals object is created on the GUI thread (in __init__,
    # called from MainWindow._submit), so `finished` is delivered to the main
    # thread via a queued connection. run() emits before returning, so the
    # event is posted while the task — and this object — are still referenced.


class ConvertTask(QRunnable):
    def __init__(self, row_id: int, src, output_dir=None, fmt: str = "svg"):
        super().__init__()
        self.row_id = row_id
        self.src = Path(src)
        self.output_dir = output_dir
        self.fmt = fmt
        self.signals = WorkerSignals()

    def run(self) -> None:  # executed on a QThreadPool worker thread
        try:
            if self.fmt == "pptx":
                message, dst = self._to_pptx()
            elif self.fmt == "emf":
                message, dst = self._to_emf()
            else:
                message, dst = self._to_svg()
            self.signals.finished.emit(self.row_id, True, str(dst), message)
        except Exception as exc:  # any engine/runtime failure -> Error row
            self.signals.finished.emit(self.row_id, False, "", str(exc))

    def _to_svg(self):
        dst = resolve_output_path(self.src, self.output_dir, ext=".svg")
        backend = eps2svg.convert(
            self.src,
            dst,
            dpi=_DPI,
            strip_bg=True,
            verbose=False,
            backend=None,
            page=None,
            max_ops=_MAX_OPS,
            timeout=_TIMEOUT,
        )
        return backend, dst

    def _to_pptx(self):
        from eps2pptx import convert_eps_to_pptx
        dst = resolve_output_path(self.src, self.output_dir, ext=".pptx")
        status = convert_eps_to_pptx(self.src, dst)
        return status, dst

    def _to_emf(self):
        from eps2emf import convert_eps_to_emf
        dst = resolve_output_path(self.src, self.output_dir, ext=".emf")
        status = convert_eps_to_emf(self.src, dst)
        return status, dst
