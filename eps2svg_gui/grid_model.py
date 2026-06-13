"""Qt-free grid geometry for the split editor.

A GridSpec is an outer frame plus interior gridline positions, all in SVG
display units. The mutator functions return new GridSpecs so the overlay and
the window never share mutable state by accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Rect = "tuple[float, float, float, float]"


def _normalize_frame(frame):
    x0, y0, x1, y1 = frame
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return (x0, y0, x1, y1)


@dataclass
class GridSpec:
    frame: tuple[float, float, float, float]   # (x0, y0, x1, y1) in SVG units
    col_lines: list[float] = field(default_factory=list)  # interior x positions
    row_lines: list[float] = field(default_factory=list)  # interior y positions

    @classmethod
    def uniform(cls, frame, rows, cols) -> "GridSpec":
        x0, y0, x1, y1 = _normalize_frame(frame)
        col_lines = [x0 + (x1 - x0) * i / cols for i in range(1, cols)]
        row_lines = [y0 + (y1 - y0) * i / rows for i in range(1, rows)]
        return cls((x0, y0, x1, y1), col_lines, row_lines)

    @property
    def rows(self) -> int:
        return len(self.row_lines) + 1

    @property
    def cols(self) -> int:
        return len(self.col_lines) + 1

    def cell_rects(self):
        """Row-major list of (row, col, x0, y0, x1, y1) in SVG units."""
        x0, y0, x1, y1 = self.frame
        xs = [x0] + sorted(self.col_lines) + [x1]
        ys = [y0] + sorted(self.row_lines) + [y1]
        out = []
        for r in range(len(ys) - 1):
            for c in range(len(xs) - 1):
                out.append((r, c, xs[c], ys[r], xs[c + 1], ys[r + 1]))
        return out


def translated(spec: GridSpec, dx: float, dy: float) -> GridSpec:
    x0, y0, x1, y1 = spec.frame
    return GridSpec(
        (x0 + dx, y0 + dy, x1 + dx, y1 + dy),
        [x + dx for x in spec.col_lines],
        [y + dy for y in spec.row_lines],
    )


def resized(spec: GridSpec, new_frame) -> GridSpec:
    nx0, ny0, nx1, ny1 = _normalize_frame(new_frame)
    ox0, oy0, ox1, oy1 = spec.frame
    ow = (ox1 - ox0) or 1.0
    oh = (oy1 - oy0) or 1.0
    cols = [nx0 + (x - ox0) / ow * (nx1 - nx0) for x in spec.col_lines]
    rows = [ny0 + (y - oy0) / oh * (ny1 - ny0) for y in spec.row_lines]
    return GridSpec((nx0, ny0, nx1, ny1), cols, rows)


def with_col_line(spec: GridSpec, index: int, x: float) -> GridSpec:
    lines = sorted(spec.col_lines)
    lo = spec.frame[0] if index == 0 else lines[index - 1]
    hi = spec.frame[2] if index == len(lines) - 1 else lines[index + 1]
    lines[index] = min(max(x, lo), hi)
    return GridSpec(spec.frame, lines, list(spec.row_lines))


def with_row_line(spec: GridSpec, index: int, y: float) -> GridSpec:
    lines = sorted(spec.row_lines)
    lo = spec.frame[1] if index == 0 else lines[index - 1]
    hi = spec.frame[3] if index == len(lines) - 1 else lines[index + 1]
    lines[index] = min(max(y, lo), hi)
    return GridSpec(spec.frame, list(spec.col_lines), lines)
