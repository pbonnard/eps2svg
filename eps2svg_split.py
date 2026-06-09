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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


SplitMode = Literal["structural", "geometric", "fallback"]


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
