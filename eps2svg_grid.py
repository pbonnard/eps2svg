"""Grid-based icon extraction for the GUI split feature.

Captures the page once (via eps2svg_split._capture_pages), exposes the rendered
page SVG plus each painted path's centre/bbox in SVG display coordinates, and
slices the page into one cropped SVG per non-empty grid cell. Reuses the
eps2svg_split helpers — no algorithm duplication.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eps2svg_split import (
    _capture_pages,
    _emit_icon_svg,
    _filter_page_spanning,
    _shape_bbox,
    strip_clip_attr,
)


@dataclass
class _PathRec:
    """One painted path. `bbox`/`group_id` are named to match what the
    eps2svg_split helpers read (PS coords); cx/cy/bbox_svg are SVG-unit."""
    svg_index: int
    fragment: str
    bbox: tuple[float, float, float, float]        # PS coords
    group_id: int | None
    cx: float                                      # centre x, SVG units
    cy: float                                      # centre y, SVG units
    bbox_svg: tuple[float, float, float, float]    # SVG units


@dataclass
class CellResult:
    row: int
    col: int
    svg_text: str
    fragments: list           # SVG path fragments of the cell's members
    bbox_ps: tuple            # union bbox in PS coords (for PPTX placement)


def _ps_to_svg_bbox(b_ps, bx0, by1):
    x0, y0, x1, y1 = b_ps
    return (x0 - bx0, by1 - y1, x1 - bx0, by1 - y0)


def _build_page_svg(fragments, bbox) -> str:
    bx0, by0, bx1, by1 = bbox
    width = max(1.0, bx1 - bx0)
    height = max(1.0, by1 - by0)
    transform = f"translate({-bx0:.3f},{by1:.3f}) scale(1,-1)"
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width:.3f} {height:.3f}" '
        f'width="{width:.3f}pt" height="{height:.3f}pt">',
        f'<g transform="{transform}">',
        *(strip_clip_attr(f) for f in fragments),
        "</g>",
        "</svg>",
    ]
    return "\n".join(parts)


class SplitDocument:
    def __init__(self, page_svg, width, height, recs, page_bbox):
        self.page_svg = page_svg
        self.width = width
        self.height = height
        self._recs = recs
        self._page_bbox = page_bbox

    def _active(self, ignore_background):
        if not ignore_background:
            return self._recs
        return _filter_page_spanning(self._recs, self._page_bbox)

    def extract_grid(self, cells, *, pad=2.0, ignore_background=False):
        """`cells` is a list of (row, col, x0, y0, x1, y1) in SVG units.
        A path joins the cell containing its bbox centre (half-open intervals).
        Empty cells are skipped."""
        recs = self._active(ignore_background)
        out = []
        for (row, col, x0, y0, x1, y1) in cells:
            members = [r for r in recs if x0 <= r.cx < x1 and y0 <= r.cy < y1]
            if not members:
                continue
            fragments = [r.fragment for r in members]
            bbox_ps = _shape_bbox(members)  # members expose .bbox in PS coords
            out.append(CellResult(row, col,
                                  _emit_icon_svg(fragments, bbox_ps, pad),
                                  fragments, bbox_ps))
        return out

    def content_cell_count(self, cells, *, ignore_background=False) -> int:
        recs = self._active(ignore_background)
        n = 0
        for (row, col, x0, y0, x1, y1) in cells:
            if any(x0 <= r.cx < x1 and y0 <= r.cy < y1 for r in recs):
                n += 1
        return n

    def suggest_grid(self):
        """Infer (rows, cols, frame) in SVG units from the cluster detector,
        or None if nothing usable is found."""
        from eps2svg_split import (
            _phase2_structural, _phase3_geometric, _lattice_merge, _assign_layout,
        )
        if not self._recs:
            return None
        clusters = _phase2_structural(self._recs, 2, 500)
        if clusters is None:
            clusters = _phase3_geometric(self._recs)
        clusters = _lattice_merge(clusters)
        if not clusters:
            return None
        ordered = _assign_layout(clusters)
        rows = max(r for r, _, _, _ in ordered) + 1
        cols = max(c for _, c, _, _ in ordered) + 1
        union_ps = _shape_bbox([p for c in clusters for p in c])
        bx0, by0, bx1, by1 = self._page_bbox
        frame = _ps_to_svg_bbox(union_ps, bx0, by1)
        return (rows, cols, frame)


def prepare_split(src, *, page=None, max_ops=5_000_000, timeout=30.0,
                  verbose=False) -> SplitDocument:
    src = Path(src)
    interp, bbox = _capture_pages(src, max_ops=max_ops, timeout=timeout,
                                  verbose=verbose)
    bx0, by0, bx1, by1 = bbox
    width = max(1.0, bx1 - bx0)
    height = max(1.0, by1 - by0)

    page_idx = (page - 1) if page else 0
    pages = [p for p in interp.pages if p] or [[]]
    if page_idx >= len(pages):
        page_idx = 0
    fragments = pages[page_idx]
    meta = interp.path_metadata if len(pages) == 1 else []

    recs = []
    for m in meta:
        if m.svg_index >= len(fragments):
            continue
        b_svg = _ps_to_svg_bbox(m.bbox, bx0, by1)
        recs.append(_PathRec(
            svg_index=m.svg_index,
            fragment=fragments[m.svg_index],
            bbox=m.bbox,
            group_id=m.group_id,
            cx=(b_svg[0] + b_svg[2]) / 2,
            cy=(b_svg[1] + b_svg[3]) / 2,
            bbox_svg=b_svg,
        ))

    return SplitDocument(_build_page_svg(fragments, bbox), width, height, recs, bbox)


def write_grid(doc: SplitDocument, out_dir, cells, *, pad=2.0,
               name_pattern="{stem}-{index:03d}.svg", force=False,
               ignore_background=False, stem="icons", fmt="svg"):
    """Write the non-empty cells. `fmt="svg"` writes one SVG per cell;
    `fmt="pptx"` writes a single `<stem>.pptx` deck, one slide per cell."""
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()) and not force:
        raise FileExistsError(
            f"output directory {out_dir} is non-empty; pass force=True to overwrite"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    results = doc.extract_grid(cells, pad=pad, ignore_background=ignore_background)

    if fmt == "pptx":
        from eps2pptx import convert_icons_to_pptx
        dst = out_dir / f"{stem}.pptx"
        convert_icons_to_pptx([(cr.fragments, cr.bbox_ps) for cr in results], dst)
        return [dst]

    written = []
    for index, cr in enumerate(results, start=1):
        filename = name_pattern.format(
            stem=stem, index=index, row=cr.row + 1, col=cr.col + 1
        )
        dst = out_dir / filename
        dst.write_text(cr.svg_text, encoding="utf-8")
        written.append(dst)
    return written
