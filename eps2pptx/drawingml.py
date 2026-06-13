"""Pure DrawingML emitters: parse the interpreter's SVG path/fragment output and
produce <p:sp> (custom-geometry shape) and <p:pic> (picture) XML. No I/O, no Qt."""

from __future__ import annotations

import re

_CMD_RE = re.compile(r"[MLCZ]")
_NCOORDS = {"M": 2, "L": 2, "C": 6, "Z": 0}
_D_RE = re.compile(r'\bd="([^"]*)"')
_ATTR_RE = re.compile(r'([a-zA-Z-]+)="([^"]*)"')


def parse_path_d(d: str):
    """Parse an SVG path `d` of absolute M/L/C/Z into [(cmd, [coords]), ...]."""
    tokens = _CMD_RE.sub(lambda m: " " + m.group(0) + " ", d).split()
    cmds = []
    i = 0
    while i < len(tokens):
        c = tokens[i]
        i += 1
        if c not in _NCOORDS:
            continue  # stray number without a command — skip defensively
        n = _NCOORDS[c]
        cmds.append((c, [float(tokens[i + k]) for k in range(n)]))
        i += n
    return cmds


def parse_fragment(fragment: str):
    """Split a `<path d=... .../>` fragment into (d_string, {attr: value})."""
    dm = _D_RE.search(fragment)
    d = dm.group(1) if dm else ""
    style = {k: v for k, v in _ATTR_RE.findall(fragment) if k != "d"}
    return d, style
