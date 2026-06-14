"""EPS/PS -> Enhanced Metafile (.emf): editable Windows/Office vector graphics.

Captures the page once via the pure-Python interpreter and turns each painted
path fragment into EMF path records (BeginPath/…/FillPath|StrokePath). Like the
PPTX exporter it consumes the interpreter's SVG path fragments, so it inherits
the pure-Python fidelity limits (no text, raster images, gradients, or clipping;
Adobe AGM artwork is degraded). For full fidelity use Ghostscript via SVG/PDF.
"""

from __future__ import annotations

import struct
from pathlib import Path

from eps2pptx import drawingml  # parse_fragment / parse_path_d (pure SVG parsing)

_PT_TO_MM100 = 2540.0 / 72.0   # PostScript points -> 0.01 mm
_S = 100                       # logical EMF units per PostScript point

# EMF record types
_EMR_HEADER = 1
_EMR_EOF = 14
_EMR_SETPOLYFILLMODE = 19
_EMR_MOVETOEX = 27
_EMR_SELECTOBJECT = 37
_EMR_CREATEPEN = 38
_EMR_CREATEBRUSHINDIRECT = 39
_EMR_DELETEOBJECT = 40
_EMR_LINETO = 54
_EMR_BEGINPATH = 59
_EMR_ENDPATH = 60
_EMR_CLOSEFIGURE = 61
_EMR_FILLPATH = 62
_EMR_STROKEPATH = 64

_ALTERNATE, _WINDING = 1, 2    # poly-fill modes (even-odd / nonzero)


def _colorref(hexstr: str) -> int:
    """'#rrggbb' -> COLORREF 0x00BBGGRR."""
    h = hexstr.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _flatten_cubic(p0, p1, p2, p3):
    """Subdivide a cubic Bézier into line points (excluding p0). Segment count
    scales with the control-polygon length so curves stay smooth at any size.

    We flatten rather than emit EMF Bézier records (EMR_POLYBEZIERTO) because
    not every EMF consumer honours curve records inside a path (e.g. Inkscape's
    importer drops them); polylines render in every reader."""
    n = max(2, min(48, round((_dist(p0, p1) + _dist(p1, p2) + _dist(p2, p3)) / 200)))
    out = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1 - t
        a, b, c, e = mt*mt*mt, 3*mt*mt*t, 3*mt*t*t, t*t*t
        out.append((round(a*p0[0] + b*p1[0] + c*p2[0] + e*p3[0]),
                    round(a*p0[1] + b*p1[1] + c*p2[1] + e*p3[1])))
    return out


class _Emf:
    """Accumulates EMF records and assembles the final byte stream."""

    def __init__(self):
        self._records: list[bytes] = []
        self.max_handle = 0
        self._path_bounds = None   # bounds of the path currently being built

    def _rec(self, itype: int, payload: bytes = b"") -> None:
        size = 8 + len(payload)
        assert size % 4 == 0, (itype, size)
        self._records.append(struct.pack("<II", itype, size) + payload)

    def _pt(self, x: int, y: int) -> None:
        box = self._path_bounds
        if box is None:
            self._path_bounds = [x, y, x, y]
        else:
            box[0] = min(box[0], x); box[1] = min(box[1], y)
            box[2] = max(box[2], x); box[3] = max(box[3], y)

    # -- objects --
    def set_fill_mode(self, even_odd: bool) -> None:
        self._rec(_EMR_SETPOLYFILLMODE,
                  struct.pack("<I", _ALTERNATE if even_odd else _WINDING))

    def create_brush(self, handle: int, color: int) -> None:
        self.max_handle = max(self.max_handle, handle)
        self._rec(_EMR_CREATEBRUSHINDIRECT,
                  struct.pack("<IIII", handle, 0, color, 0))  # BS_SOLID

    def create_pen(self, handle: int, width: int, color: int) -> None:
        self.max_handle = max(self.max_handle, handle)
        self._rec(_EMR_CREATEPEN,
                  struct.pack("<IIiiI", handle, 0, width, 0, color))  # PS_SOLID

    def select(self, handle: int) -> None:
        self._rec(_EMR_SELECTOBJECT, struct.pack("<I", handle))

    def delete(self, handle: int) -> None:
        self._rec(_EMR_DELETEOBJECT, struct.pack("<I", handle))

    # -- path --
    def begin_path(self) -> None:
        self._path_bounds = None
        self._rec(_EMR_BEGINPATH)

    def move_to(self, x: int, y: int) -> None:
        self._pt(x, y)
        self._rec(_EMR_MOVETOEX, struct.pack("<ii", x, y))

    def line_to(self, x: int, y: int) -> None:
        self._pt(x, y)
        self._rec(_EMR_LINETO, struct.pack("<ii", x, y))

    def close_figure(self) -> None:
        self._rec(_EMR_CLOSEFIGURE)

    def end_path(self) -> None:
        self._rec(_EMR_ENDPATH)

    def _path_rcl(self) -> bytes:
        b = self._path_bounds or [0, 0, 0, 0]
        return struct.pack("<iiii", *b)

    def fill_path(self) -> None:
        self._rec(_EMR_FILLPATH, self._path_rcl())

    def stroke_path(self) -> None:
        self._rec(_EMR_STROKEPATH, self._path_rcl())

    def assemble(self, frame_w100: int, frame_h100: int,
                 dev_w: int, dev_h: int) -> bytes:
        eof = struct.pack("<IIIII", _EMR_EOF, 20, 0, 16, 20)
        body = b"".join(self._records)
        n_records = len(self._records) + 2          # + header + eof
        n_bytes = 88 + len(body) + len(eof)
        # rclBounds = the full page extent (not the tight content bbox), so
        # consumers preserve the page margins / placement of the artwork.
        bounds = [0, 0, max(1, dev_w), max(1, dev_h)]
        header = (
            struct.pack("<II", _EMR_HEADER, 88)
            + struct.pack("<iiii", *bounds)                 # rclBounds (logical)
            + struct.pack("<iiii", 0, 0, frame_w100, frame_h100)  # rclFrame (.01mm)
            + struct.pack("<I", 0x464D4520)                 # " EMF"
            + struct.pack("<I", 0x00010000)                 # version
            + struct.pack("<I", n_bytes)
            + struct.pack("<I", n_records)
            + struct.pack("<H", self.max_handle + 1)        # nHandles
            + struct.pack("<H", 0)                           # reserved
            + struct.pack("<I", 0)                           # nDescription
            + struct.pack("<I", 0)                           # offDescription
            + struct.pack("<I", 0)                           # nPalEntries
            + struct.pack("<ii", max(1, dev_w), max(1, dev_h))      # szlDevice (px)
            + struct.pack("<ii", max(1, round(frame_w100 / 100)),
                          max(1, round(frame_h100 / 100)))          # szlMillimeters
        )
        return header + body + eof


def convert_eps_to_emf(src, dst, *, page=None, max_ops=5_000_000,
                       timeout=30.0, verbose=False) -> str:
    src = Path(src)
    dst = Path(dst)
    from eps2svg_split import _capture_pages
    interp, bbox = _capture_pages(src, max_ops=max_ops, timeout=timeout,
                                  verbose=verbose)
    bx0, by0, bx1, by1 = bbox

    page_idx = (page - 1) if page else 0
    pages = [p for p in interp.pages if p] or [[]]
    if page_idx >= len(pages):
        page_idx = 0
    fragments = pages[page_idx]

    def to_log(x, y):
        return (round((x - bx0) * _S), round((by1 - y) * _S))   # flip Y (EMF Y-down)

    emf = _Emf()
    handle = 1
    n_paths = 0
    for frag in fragments:
        if "<path" not in frag:
            continue
        d, style = drawingml.parse_fragment(frag)
        cmds = drawingml.parse_path_d(d)
        if not cmds:
            continue
        fill = style.get("fill", "none")
        stroke = style.get("stroke", "none")
        is_fill = bool(fill) and fill != "none"
        is_stroke = bool(stroke) and stroke != "none"
        if not (is_fill or is_stroke):
            continue

        if is_fill:
            emf.set_fill_mode(style.get("fill-rule") == "evenodd")
            emf.create_brush(handle, _colorref(fill))
        else:
            w = max(1, round(float(style.get("stroke-width", "1")) * _S))
            emf.create_pen(handle, w, _colorref(stroke))
        emf.select(handle)

        emf.begin_path()
        cur = (0, 0)
        for cmd, nums in cmds:
            if cmd == "M":
                cur = to_log(nums[0], nums[1]); emf.move_to(*cur)
            elif cmd == "L":
                cur = to_log(nums[0], nums[1]); emf.line_to(*cur)
            elif cmd == "C":
                c1 = to_log(nums[0], nums[1])
                c2 = to_log(nums[2], nums[3])
                end = to_log(nums[4], nums[5])
                for p in _flatten_cubic(cur, c1, c2, end):
                    emf.line_to(*p)
                cur = end
            elif cmd == "Z":
                emf.close_figure()
        emf.end_path()
        emf.fill_path() if is_fill else emf.stroke_path()
        emf.delete(handle)          # free & reuse the handle slot
        n_paths += 1

    w = max(1.0, bx1 - bx0)
    h = max(1.0, by1 - by0)
    data = emf.assemble(
        frame_w100=round(w * _PT_TO_MM100), frame_h100=round(h * _PT_TO_MM100),
        dev_w=round(w * _S), dev_h=round(h * _S),
    )
    dst.write_bytes(data)
    return f"emf ({n_paths} paths)"
