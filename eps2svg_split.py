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


SplitMode = Literal["structural", "geometric", "fallback"]


# Tuning knobs for the geometric and layout phases. These match
# docs/superpowers/specs/2026-06-09-icon-split-design.md and were chosen
# empirically against the Getty icon corpus.
_GEOMETRIC_GAP_FRACTION = 0.3   # Phase 3: cluster gap threshold = median diagonal × this


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
) -> SplitResult:
    """Detect icons in `src` and write one SVG per icon into `out_dir`."""
    raise NotImplementedError("Filled in by later tasks.")


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
