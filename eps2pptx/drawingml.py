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


def _hexval(color: str) -> str:
    """'#ff0000' or 'ff0000' -> 'FF0000'."""
    return color.lstrip("#").upper()


def _solid_fill(color: str) -> str:
    return f'<a:solidFill><a:srgbClr val="{_hexval(color)}"/></a:solidFill>'


_CAP = {"butt": "flat", "round": "rnd", "square": "sq"}
_JOIN = {"miter": "<a:miter/>", "round": "<a:round/>", "bevel": "<a:bevel/>"}


def _line_xml(style: dict, s: float) -> str:
    stroke = style.get("stroke", "none")
    if stroke == "none":
        return ""
    w = max(1, round(float(style.get("stroke-width", "1")) * s))
    attrs = [f'w="{w}"']
    cap = _CAP.get(style.get("stroke-linecap", ""))
    if cap:
        attrs.append(f'cap="{cap}"')
    parts = [f'<a:ln {" ".join(attrs)}>', _solid_fill(stroke)]
    join = _JOIN.get(style.get("stroke-linejoin", ""))
    if join:
        parts.append(join)
    if style.get("stroke-dasharray"):
        parts.append('<a:prstDash val="dash"/>')
    parts.append("</a:ln>")
    return "".join(parts)


def _path_commands_xml(cmds, minx, miny, cx, cy):
    """Emit <a:moveTo>/<a:lnTo>/<a:cubicBezTo>/<a:close> in local EMU coords."""
    def loc(x, y):
        lx = min(max(round(x - minx), 0), cx)
        ly = min(max(round(y - miny), 0), cy)
        return f'<a:pt x="{lx}" y="{ly}"/>'

    out = []
    for cmd, nums in cmds:
        if cmd == "M":
            out.append(f"<a:moveTo>{loc(nums[0], nums[1])}</a:moveTo>")
        elif cmd == "L":
            out.append(f"<a:lnTo>{loc(nums[0], nums[1])}</a:lnTo>")
        elif cmd == "C":
            out.append(
                "<a:cubicBezTo>"
                + loc(nums[0], nums[1]) + loc(nums[2], nums[3]) + loc(nums[4], nums[5])
                + "</a:cubicBezTo>"
            )
        elif cmd == "Z":
            out.append("<a:close/>")
    return "".join(out)


def shape_xml(d: str, style: dict, to_emu, s: float, shape_id: int):
    """Build a <p:sp> custom-geometry shape, or None if `d` is empty.

    `to_emu(X, Y) -> (float, float)` maps a PS device point to slide EMU.
    `s` is EMU-per-PS-point (for stroke width)."""
    cmds = parse_path_d(d)
    pts = []
    mapped = []
    for cmd, nums in cmds:
        emu_nums = []
        for k in range(0, len(nums), 2):
            ex, ey = to_emu(nums[k], nums[k + 1])
            emu_nums.extend([ex, ey])
            pts.append((ex, ey))
        mapped.append((cmd, emu_nums))
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, miny = min(xs), min(ys)
    cx = max(1, round(max(xs) - minx))
    cy = max(1, round(max(ys) - miny))
    off_x, off_y = round(minx), round(miny)

    fill = style.get("fill", "none")
    fill_xml = _solid_fill(fill) if fill and fill != "none" else "<a:noFill/>"
    line_xml = _line_xml(style, s)
    path_cmds = _path_commands_xml(mapped, minx, miny, cx, cy)

    return (
        "<p:sp>"
        f'<p:nvSpPr><p:cNvPr id="{shape_id}" name="Path {shape_id}"/>'
        "<p:cNvSpPr/><p:nvPr/></p:nvSpPr>"
        "<p:spPr>"
        f'<a:xfrm><a:off x="{off_x}" y="{off_y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        "<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>"
        f'<a:rect l="0" t="0" r="{cx}" b="{cy}"/>'
        f'<a:pathLst><a:path w="{cx}" h="{cy}">{path_cmds}</a:path></a:pathLst>'
        "</a:custGeom>"
        f"{fill_xml}{line_xml}"
        "</p:spPr>"
        "<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>"
        "</p:sp>"
    )


def picture_xml(off, ext, rid="rId2", pic_id=2):
    """Build a <p:pic> referencing an embedded image relationship `rid`."""
    ox, oy = round(off[0]), round(off[1])
    cx, cy = round(ext[0]), round(ext[1])
    return (
        "<p:pic>"
        f'<p:nvPicPr><p:cNvPr id="{pic_id}" name="Picture {pic_id}"/>'
        "<p:cNvPicPr/><p:nvPr/></p:nvPicPr>"
        f'<p:blipFill><a:blip r:embed="{rid}"/>'
        "<a:stretch><a:fillRect/></a:stretch></p:blipFill>"
        "<p:spPr>"
        f'<a:xfrm><a:off x="{ox}" y="{oy}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "</p:spPr>"
        "</p:pic>"
    )
