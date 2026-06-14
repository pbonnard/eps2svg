"""Row model for the file list: status enum, row dataclass, label formatting."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path


class RowStatus(enum.Enum):
    QUEUED = "Queued"
    CONVERTING = "Converting"
    DONE = "Done"
    ERROR = "Error"


_ICON = {
    RowStatus.QUEUED: "…",
    RowStatus.CONVERTING: "⟳",
    RowStatus.DONE: "✓",
    RowStatus.ERROR: "✗",
}


@dataclass
class FileRow:
    src: Path
    status: RowStatus = RowStatus.QUEUED
    out_path: str = ""
    message: str = ""
    # Format the row was (or is being) converted as: "svg" | "pptx" | "".
    fmt: str = ""
    # Cached temp SVG rendered purely for the preview pane (PPTX rows, or rows
    # not yet converted, still preview as artwork). "" until rendered.
    preview_svg: str = ""
    # Stable identifier (monotonic), independent of list position, so rows can
    # be removed without corrupting in-flight task references.
    rid: int = -1
    # Backend that will/did process the row, e.g. "Pure Python", "Ghostscript".
    # `backend_predicted` marks a pre-convert guess (rendered with a '~').
    backend: str = ""
    backend_predicted: bool = False


def row_label(row: FileRow) -> str:
    """Single-line label for a list item, e.g. 'logo.eps    ✓ Done · Pure Python'."""
    label = f"{row.src.name}    {_ICON[row.status]} {row.status.value}"
    if row.backend:
        mark = "~" if row.backend_predicted else ""
        label += f"    · {mark}{row.backend}"
    return label
