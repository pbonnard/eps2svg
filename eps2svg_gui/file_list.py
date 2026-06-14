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


def row_label(row: FileRow) -> str:
    """Single-line label for a list item, e.g. 'logo.eps    ✓ Done'."""
    return f"{row.src.name}    {_ICON[row.status]} {row.status.value}"
