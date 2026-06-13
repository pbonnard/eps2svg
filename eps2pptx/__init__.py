"""EPS/PS -> native PowerPoint (.pptx) with editable DrawingML shapes.

Captures the page once via the pure-Python interpreter, maps each painted path
into a 16:9 slide (uniform fit, centered), and emits one editable custGeom
shape per path. Vector-less files fall back to embedding the largest JPEG."""

from __future__ import annotations

from pathlib import Path

from eps2pptx import drawingml, package

EMU_PER_PT = 12700
_MARGIN = 0.9  # fraction of the slide the artwork may occupy


def convert_eps_to_pptx(src, dst, *, page=None, max_ops=5_000_000,
                        timeout=30.0, verbose=False) -> str:
    src = Path(src)
    dst = Path(dst)
    from eps2svg_split import _capture_pages
    interp, bbox = _capture_pages(src, max_ops=max_ops, timeout=timeout,
                                  verbose=verbose)
    bx0, by0, bx1, by1 = bbox
    w = max(1.0, bx1 - bx0)
    h = max(1.0, by1 - by0)
    fit = min(_MARGIN * package.SLIDE_W / (w * EMU_PER_PT),
              _MARGIN * package.SLIDE_H / (h * EMU_PER_PT))
    s = EMU_PER_PT * fit
    aw, ah = w * s, h * s
    ox, oy = (package.SLIDE_W - aw) / 2, (package.SLIDE_H - ah) / 2

    def to_emu(x, y):
        return (ox + (x - bx0) * s, oy + (by1 - y) * s)

    page_idx = (page - 1) if page else 0
    pages = [p for p in interp.pages if p] or [[]]
    if page_idx >= len(pages):
        page_idx = 0
    fragments = pages[page_idx]

    shapes = []
    shape_id = 2  # id 1 is the group
    for frag in fragments:
        if "<path" not in frag:
            continue
        d, style = drawingml.parse_fragment(frag)
        xml = drawingml.shape_xml(d, style, to_emu, s, shape_id)
        if xml:
            shapes.append(xml)
            shape_id += 1

    if shapes:
        package.write_pptx(dst, "".join(shapes))
        return f"pptx ({len(shapes)} shapes)"

    # Raster fallback: embed the largest JPEG over the placed-art rectangle.
    from eps2svg_pure import strip_eps_binary_header, extract_jpegs
    jpegs = extract_jpegs(strip_eps_binary_header(src.read_bytes()))
    if jpegs:
        biggest = max(jpegs, key=len)
        pic = drawingml.picture_xml(off=(ox, oy), ext=(aw, ah),
                                    rid="rId2", pic_id=2)
        package.write_pptx(dst, pic, media_jpeg=biggest)
        return "pptx (1 image)"

    package.write_pptx(dst, "")
    return "pptx (0 shapes)"
