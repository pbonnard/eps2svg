"""Pure path helpers for the GUI — no Qt, no engine import, fully unit-testable.

SUPPORTED_EXTS mirrors eps2svg._EPS_EXTS; kept local to avoid importing the CLI
module just for a constant.
"""

from __future__ import annotations

from pathlib import Path

SUPPORTED_EXTS = (".eps", ".ps", ".epsf")


def is_supported(path) -> bool:
    """True if `path` has an EPS/PS extension we accept (case-insensitive)."""
    return Path(path).suffix.lower() in SUPPORTED_EXTS


def resolve_output_path(src, output_dir=None, ext=".svg") -> Path:
    """Where the output for `src` should be written.

    - output_dir is None  -> next to the source as <stem><ext>
    - output_dir is set    -> <output_dir>/<stem><ext>

    `ext` selects the output extension (".svg" by default, ".pptx" for PowerPoint).
    """
    src = Path(src)
    if output_dir is not None:
        return Path(output_dir) / src.with_suffix(ext).name
    return src.with_suffix(ext)


def _looks_agm(src) -> bool:
    """True if the file's prolog references the Adobe AGM module — artwork the
    pure-Python interpreter can't fully execute, so the SVG auto-chain falls
    through to Ghostscript. Cheap header sniff (first 8 KB)."""
    try:
        with open(src, "rb") as f:
            head = f.read(8192)
    except OSError:
        return False
    return b"Adobe_AGM" in head


def predict_backend(src, fmt, gs_available) -> tuple[str, bool]:
    """Best-effort guess of which backend will process `src`.

    Returns (backend_label, predicted). `predicted` is True only when it is a
    genuine guess — the SVG + Ghostscript case, where the real choice (Pure
    Python, or a fall-through to Ghostscript) is only known at convert time."""
    if fmt == "pptx":
        return ("Pure Python", False)        # eps2pptx is pure-Python
    if not gs_available:
        return ("Pure Python", False)        # only backend that can run
    if _looks_agm(src):
        return ("Ghostscript", True)
    return ("Pure Python", True)


def enumerate_inputs(paths, recursive: bool = False) -> list[Path]:
    """Expand a list of file/dir paths into concrete supported source files.

    Files are kept if supported; directories are scanned (recursively when
    `recursive`). Results are de-duplicated, preserving first-seen order.
    """
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            return
        seen.add(key)
        out.append(p)

    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            for child in sorted(p.glob(pattern)):
                if child.is_file() and is_supported(child):
                    add(child)
        elif p.is_file() and is_supported(p):
            add(p)

    return out
