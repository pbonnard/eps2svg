"""Icon-split feature for eps2svg.

Implements the hybrid algorithm from
docs/superpowers/specs/2026-06-09-icon-split-design.md:

  Phase 2 — structural grouping by gsave-depth `group_id`
  Phase 3 — geometric clustering by bbox proximity (fallback)
  Phase 4 — layout assignment + reading order
  Phase 5 — per-icon SVG emission

Entry point: run_split(src, out_dir, ...).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eps2svg_pure import PathMeta


SplitMode = Literal["structural", "geometric", "fallback"]


# Tuning knobs for the geometric and layout phases. These match
# docs/superpowers/specs/2026-06-09-icon-split-design.md and were chosen
# empirically against the Getty icon corpus.
_GEOMETRIC_GAP_FRACTION = 0.3   # Phase 3: cluster gap threshold = median diagonal × this
_LAYOUT_GAP_FRACTION = 0.5      # Phase 4: row/col gap threshold = median width/height × this
_STRUCTURAL_IOU_THRESHOLD = 0.05      # Phase 2: reject if avg pairwise group IoU ≥ this
_STRUCTURAL_COVERAGE_THRESHOLD = 0.6  # Phase 2: reject if grouped area / total area < this


@dataclass
class SplitResult:
    mode: SplitMode
    icon_count: int
    written: list[Path] = field(default_factory=list)


def run_split(
    src: Path,
    out_dir: Path,
    *,
    pad: float = 2.0,
    min_icons: int = 2,
    max_icons: int = 500,
    name_pattern: str = "{stem}-{index:03d}.svg",
    force: bool = False,
    verbose: bool = False,
    page: int | None = None,
    max_ops: int = 5_000_000,
    timeout: float = 30.0,
    grid: bool = False,
    fmt: str = "svg",
) -> SplitResult:
    """Detect icons in `src` and write them into `out_dir`.

    `fmt="svg"` writes one SVG per icon; `fmt="pptx"` writes a single
    `<stem>.pptx` deck with one slide per icon."""
    import sys

    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()) and not force:
        raise FileExistsError(
            f"output directory {out_dir} is non-empty; pass force=True to overwrite"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    interp, bbox = _capture_pages(
        src, max_ops=max_ops, timeout=timeout, verbose=verbose
    )

    # Use the selected page's metadata + svg fragments.
    page_idx = (page - 1) if page else 0
    pages = [p for p in interp.pages if p] or [[]]
    if page_idx >= len(pages):
        page_idx = 0
    page_fragments = pages[page_idx]

    # Filter PathMeta to those whose svg_index points into the selected page.
    # In multi-page files the metadata list mixes pages; we keep it simple by
    # only using metadata when there's exactly one page (the common case for
    # icon sheets). Multi-page sheets are an explicit out-of-scope edge.
    if len(pages) > 1:
        if verbose:
            print(f"split: multi-page input; using page {page_idx + 1} only",
                  file=sys.stderr)
    meta_list = interp.path_metadata if len(pages) == 1 else []

    if grid:
        meta_list = _filter_page_spanning(meta_list, bbox)

    mode: SplitMode
    clusters = _phase2_structural(meta_list, min_icons, max_icons)
    if clusters is not None:
        mode = "structural"
    else:
        clusters = _phase3_geometric(meta_list)
        mode = "geometric"

    if grid:
        clusters = _lattice_merge(clusters)

    if not (min_icons <= len(clusters) <= max_icons):
        # Fallback: the unsplit page as a single icon.
        if fmt == "pptx":
            from eps2pptx import convert_icons_to_pptx
            dst = out_dir / f"{src.stem}.pptx"
            convert_icons_to_pptx([(page_fragments, bbox)], dst)
        else:
            bx0, by0, bx1, by1 = bbox
            width = max(1.0, bx1 - bx0); height = max(1.0, by1 - by0)
            transform = f"translate({-bx0:.3f},{by1:.3f}) scale(1,-1)"
            parts = [
                '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="0 0 {width:.3f} {height:.3f}" '
                f'width="{width:.3f}pt" height="{height:.3f}pt">',
                f'<g transform="{transform}">',
                *page_fragments,
                "</g></svg>",
            ]
            dst = out_dir / f"{src.stem}.svg"
            dst.write_text("\n".join(parts), encoding="utf-8")
        if verbose:
            print(f"split: detected {len(clusters)} cluster(s); fallback to "
                  f"unsplit {dst.name}", file=sys.stderr)
        return SplitResult(mode="fallback", icon_count=1, written=[dst])

    ordered = _assign_layout(clusters)
    icons = []  # (seq, row, col, fragments, bbox_ps)
    for seq, (row, col, _orig_idx, shape) in enumerate(ordered, start=1):
        path_fragments = [page_fragments[m.svg_index] for m in shape]
        icons.append((seq, row, col, path_fragments, _shape_bbox(shape)))

    if fmt == "pptx":
        from eps2pptx import convert_icons_to_pptx
        dst = out_dir / f"{src.stem}.pptx"
        convert_icons_to_pptx([(frags, b) for _s, _r, _c, frags, b in icons], dst)
        return SplitResult(mode=mode, icon_count=len(icons), written=[dst])

    written: list[Path] = []
    for seq, row, col, path_fragments, b in icons:
        svg_text = _emit_icon_svg(path_fragments, b, pad)
        filename = name_pattern.format(
            stem=src.stem, index=seq, row=row + 1, col=col + 1
        )
        dst = out_dir / filename
        dst.write_text(svg_text, encoding="utf-8")
        written.append(dst)

    return SplitResult(mode=mode, icon_count=len(written), written=written)


def _bbox_gap(a: tuple[float, float, float, float],
              b: tuple[float, float, float, float]) -> float:
    """Minimum axis-aligned distance between two bboxes. 0 if they overlap."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    dx = max(bx0 - ax1, ax0 - bx1, 0.0)
    dy = max(by0 - ay1, ay0 - by1, 0.0)
    return (dx * dx + dy * dy) ** 0.5


def _phase3_geometric(meta_list: list) -> list[list]:
    """Single-link cluster paths by bbox gap. Returns a list of clusters,
    each cluster being a list of `PathMeta` records.

    Note: parameter typed as `list` (not `list[PathMeta]`) to avoid a circular
    import with `eps2svg_pure`. The function reads only `m.bbox` on each
    element, so any tuple-bbox-bearing object will work.
    """
    if not meta_list:
        return []

    # Adaptive gap threshold: median diagonal × 0.3
    diagonals = []
    for m in meta_list:
        x0, y0, x1, y1 = m.bbox
        diagonals.append(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5)
    threshold = statistics.median(diagonals) * _GEOMETRIC_GAP_FRACTION if diagonals else 0.0

    # Union-find over path indices
    # Union-find with path compression only — no rank/size. Adequate for
    # the few-thousand-paths regime; α(n) amortised per find.
    parent = list(range(len(meta_list)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    # Sort by x-centre then sweep with a window equal to 2 * threshold.
    by_x = sorted(range(len(meta_list)),
                  key=lambda i: (meta_list[i].bbox[0] + meta_list[i].bbox[2]) / 2)
    window: list[int] = []
    for idx in by_x:
        cx = (meta_list[idx].bbox[0] + meta_list[idx].bbox[2]) / 2
        # Drop window entries whose right edge is too far left
        cutoff = cx - 2 * threshold - max(
            meta_list[idx].bbox[2] - meta_list[idx].bbox[0], 1.0
        )
        # Conservative cutoff: assumes window-entry widths are roughly
        # comparable to the current path. Safe for icon sheets where
        # bbox sizes cluster. `max(width, 1.0)` floors zero-width bboxes
        # so the cutoff still advances on degenerate paths.
        window = [w for w in window
                  if (meta_list[w].bbox[0] + meta_list[w].bbox[2]) / 2 > cutoff]
        for w in window:
            if _bbox_gap(meta_list[idx].bbox, meta_list[w].bbox) <= threshold:
                union(idx, w)
        window.append(idx)

    # Materialise clusters
    buckets: dict[int, list] = defaultdict(list)
    for i, m in enumerate(meta_list):
        buckets[find(i)].append(m)
    return list(buckets.values())


# Pre-filter / lattice helpers (used by --grid mode)

_PAGE_SPAN_FRACTION = 0.7          # Drop paths whose bbox covers ≥ this much of the page
_LATTICE_MERGE_FRACTION = 0.7      # Merge clusters whose centres are within median_size × this

def _filter_page_spanning(meta_list: list,
                          page_bbox: tuple[float, float, float, float]) -> list:
    """Drop paths whose individual bbox covers more than _PAGE_SPAN_FRACTION of
    the page area. These are almost always background rectangles or borders, not
    icons. The corresponding entries are removed; the rest are returned in order.
    """
    px0, py0, px1, py1 = page_bbox
    page_area = max(1.0, (px1 - px0)) * max(1.0, (py1 - py0))
    cutoff = _PAGE_SPAN_FRACTION * page_area
    return [m for m in meta_list if _bbox_area(m.bbox) <= cutoff]


def _lattice_merge(clusters: list[list]) -> list[list]:
    """Snap initial clusters to a regular X × Y lattice and merge any clusters
    that land in the same cell. Works well for uniform icon sheets where the
    Phase 3 threshold is too tight and splits one icon into several clusters.

    The lattice pitch is derived from the median cluster bbox (width × height).
    A small threshold (median × _LATTICE_MERGE_FRACTION) collapses cluster
    centres that fall inside the same icon cell. Returns the merged cluster
    list, preserving cluster order within each cell.
    """
    if len(clusters) < 2:
        return clusters
    bboxes = [_shape_bbox(c) for c in clusters]
    widths = sorted(b[2] - b[0] for b in bboxes if b[2] > b[0])
    heights = sorted(b[3] - b[1] for b in bboxes if b[3] > b[1])
    if not widths or not heights:
        return clusters
    med_w = widths[len(widths) // 2]
    med_h = heights[len(heights) // 2]
    cx = [(b[0] + b[2]) / 2 for b in bboxes]
    cy = [(b[1] + b[3]) / 2 for b in bboxes]
    col_idx = _cluster_1d(cx, med_w * _LATTICE_MERGE_FRACTION)
    row_idx = _cluster_1d(cy, med_h * _LATTICE_MERGE_FRACTION)
    merged: dict[tuple[int, int], list] = defaultdict(list)
    for i, c in enumerate(clusters):
        merged[(row_idx[i], col_idx[i])].extend(c)
    return list(merged.values())


def _cluster_1d(values: list[float], threshold: float) -> list[int]:
    """Assign each value to a cluster index by gap-threshold clustering.
    Values are processed in sorted order; consecutive values whose gap is
    ≤ threshold share a cluster.

    Returns a list of cluster indices, parallel to `values`."""
    if not values:
        return []
    order = sorted(range(len(values)), key=lambda i: values[i])
    cluster_idx = [0] * len(values)
    current = 0
    prev = values[order[0]]
    cluster_idx[order[0]] = current
    for k in range(1, len(order)):
        v = values[order[k]]
        if v - prev > threshold:
            current += 1
        cluster_idx[order[k]] = current
        prev = v
    return cluster_idx


def _shape_bbox(paths: list["PathMeta"]) -> tuple[float, float, float, float]:
    xs0 = [p.bbox[0] for p in paths]; ys0 = [p.bbox[1] for p in paths]
    xs1 = [p.bbox[2] for p in paths]; ys1 = [p.bbox[3] for p in paths]
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def _assign_layout(shapes: list[list["PathMeta"]]):
    """Order shapes by (row, col) reading order using 1D gap clustering on
    centres. Returns a list of (row, col, index, shape) tuples sorted in
    reading order.

    `shapes` is a list of lists of PathMeta (the output of Phase 2 or 3)."""
    if not shapes:
        return []
    bboxes = [_shape_bbox(s) for s in shapes]
    cx = [(b[0] + b[2]) / 2 for b in bboxes]
    cy = [(b[1] + b[3]) / 2 for b in bboxes]
    widths = [b[2] - b[0] for b in bboxes]
    heights = [b[3] - b[1] for b in bboxes]
    col_threshold = statistics.median(widths) * _LAYOUT_GAP_FRACTION if widths else 0.0
    row_threshold = statistics.median(heights) * _LAYOUT_GAP_FRACTION if heights else 0.0

    col_idx = _cluster_1d(cx, col_threshold)
    row_idx = _cluster_1d(cy, row_threshold)
    # PS Y-axis goes UP, so _cluster_1d puts the lowest cy (bottom of the
    # page) at row 0. Flip the indices so the TOP of the page is row 0,
    # which matches user expectations for icon reading order.
    if row_idx:
        n_rows = max(row_idx) + 1
        row_idx = [n_rows - 1 - r for r in row_idx]

    enriched = list(zip(row_idx, col_idx, range(len(shapes)), shapes))
    enriched.sort(key=lambda t: (t[0], t[1]))
    return enriched


def _emit_icon_svg(path_fragments: list[str],
                   bbox: tuple[float, float, float, float],
                   pad: float) -> str:
    """Build a standalone SVG document for one icon.

    `path_fragments` are the raw `<path …/>` strings the interpreter emitted,
    already in PostScript device coordinates. `bbox` is the icon's union bbox.
    The wrapping <g> applies pad-translate, origin-translate, and the PS Y-flip
    that the parent page SVG normally applies — re-derived locally per icon.
    """
    x0, y0, x1, y1 = bbox
    w = max(1.0, (x1 - x0) + 2 * pad)
    h = max(1.0, (y1 - y0) + 2 * pad)
    tx = pad - x0
    ty = y1 + pad
    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8" standalone="no"?>')
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {w:.3f} {h:.3f}" '
        f'width="{w:.3f}pt" height="{h:.3f}pt">'
    )
    parts.append(f'<g transform="translate({tx:.3f},{ty:.3f}) scale(1,-1)">')
    parts.extend(path_fragments)
    parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts)


def _bbox_area(b: tuple[float, float, float, float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _bbox_iou(a: tuple[float, float, float, float],
              b: tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = _bbox_area(a) + _bbox_area(b) - inter
    return inter / union if union > 0 else 0.0


def _phase2_structural(meta_list: list,
                       min_icons: int,
                       max_icons: int) -> list[list] | None:
    """Return a list of clusters (each a list of PathMeta) if structural
    grouping is accepted; otherwise None."""
    grouped: dict[int, list] = defaultdict(list)
    for m in meta_list:
        if m.group_id is not None:
            grouped[m.group_id].append(m)
    if not grouped:
        return None
    groups = list(grouped.values())
    n = len(groups)
    if not (min_icons <= n <= max_icons):
        return None

    # Step 2b: IoU check (avg pairwise)
    bboxes = [_shape_bbox(g) for g in groups]
    if n > 1:
        total = 0.0; pairs = 0
        for i in range(n):
            for j in range(i + 1, n):
                total += _bbox_iou(bboxes[i], bboxes[j])
                pairs += 1
        if (total / pairs) >= _STRUCTURAL_IOU_THRESHOLD:
            return None

    # Coverage check: area of grouped path bboxes / area of all path bboxes
    grouped_area = sum(_bbox_area(m.bbox) for m in meta_list
                       if m.group_id is not None)
    total_area = sum(_bbox_area(m.bbox) for m in meta_list)
    if total_area > 0 and (grouped_area / total_area) < _STRUCTURAL_COVERAGE_THRESHOLD:
        return None

    # Step 2c: merge orphans (group_id is None) into nearest group by centre
    orphans = [m for m in meta_list if m.group_id is None]
    for m in orphans:
        ox = (m.bbox[0] + m.bbox[2]) / 2
        oy = (m.bbox[1] + m.bbox[3]) / 2
        best_idx = 0
        best_d = float("inf")
        for i, gb in enumerate(bboxes):
            gx = (gb[0] + gb[2]) / 2
            gy = (gb[1] + gb[3]) / 2
            d = (gx - ox) ** 2 + (gy - oy) ** 2
            if d < best_d:
                best_d = d; best_idx = i
        groups[best_idx].append(m)

    return groups


def _capture_pages(src: Path, *, max_ops: int, timeout: float, verbose: bool):
    """Run the interpreter on `src` and return (interp, bbox)."""
    from eps2svg_pure import (
        strip_eps_binary_header, parse_bbox, parse_page_size,
        Interpreter, tokenize, _Budget, _ADOBE_PROLOG, _ExitException,
        _BudgetExhausted,
    )
    raw = strip_eps_binary_header(src.read_bytes())
    bbox = parse_bbox(raw)
    if bbox is None:
        ps = parse_page_size(raw)
        bbox = (0.0, 0.0, ps[0], ps[1]) if ps else (0.0, 0.0, 612.0, 792.0)

    budget = _Budget(max_ops=max_ops, max_seconds=timeout)
    interp = Interpreter(bbox, budget=budget)
    try:
        interp._exec_tokens(tokenize(_ADOBE_PROLOG))
    except (_ExitException, _BudgetExhausted):
        pass
    interp.budget = budget
    try:
        tokens = tokenize(raw.decode("latin-1", errors="replace"), budget=budget)
    except _BudgetExhausted:
        tokens = []
    try:
        interp._exec_tokens(tokens)
    except (_ExitException, _BudgetExhausted):
        pass
    return interp, bbox
