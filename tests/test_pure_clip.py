"""Clipping (clip / eoclip) in the pure-Python interpreter."""

import tempfile
import unittest
from pathlib import Path

from eps2svg_pure import Interpreter, convert_eps_to_svg, tokenize

_RECT = "0 0 moveto 10 0 lineto 10 10 lineto 0 10 lineto closepath"
_TRI = "newpath 2 2 moveto 8 2 lineto 8 8 lineto closepath"


def _run(src):
    interp = Interpreter((0, 0, 100, 100))
    interp._exec_tokens(tokenize(src))
    return interp


class ClipTests(unittest.TestCase):
    def test_clip_registers_clippath_and_marks_fill(self):
        i = _run(f"{_RECT} clip {_TRI} fill")
        self.assertEqual(len(i.clip_defs), 1)
        self.assertIn('id="clip1"', i.clip_defs[0])
        self.assertIn('clip-path="url(#clip1)"', i.pages[0][-1])

    def test_eoclip_uses_evenodd_rule(self):
        i = _run(f"{_RECT} eoclip {_TRI} fill")
        self.assertIn('clip-rule="evenodd"', i.clip_defs[0])

    def test_grestore_drops_the_clip(self):
        i = _run(f"gsave {_RECT} clip {_TRI} fill grestore "
                 f"newpath 1 1 moveto 3 1 lineto 3 3 lineto closepath fill")
        clipped, unclipped = i.pages[0][0], i.pages[0][1]
        self.assertIn("clip-path=", clipped)
        self.assertNotIn("clip-path=", unclipped)

    def test_nested_clips_chain_to_parent(self):
        i = _run(f"{_RECT} clip 0 0 moveto 5 0 lineto 5 5 lineto closepath clip "
                 f"{_TRI} fill")
        self.assertEqual(len(i.clip_defs), 2)
        self.assertIn('clip-path="url(#clip1)"', i.clip_defs[1])  # clip2 ∩ clip1
        self.assertIn('clip-path="url(#clip2)"', i.pages[0][-1])


class ConvertClipTests(unittest.TestCase):
    def test_output_has_defs_and_clip_reference(self):
        eps = ("%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 20 20\n%%EndComments\n"
               f"{_RECT} clip {_TRI} fill\n")
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "clip.eps"
            src.write_text(eps, encoding="latin-1")
            dst = Path(d) / "out.svg"
            convert_eps_to_svg(src, dst)
            svg = dst.read_text(encoding="utf-8")
            self.assertIn("<defs>", svg)
            self.assertIn("<clipPath", svg)
            self.assertIn('clip-path="url(#clip1)"', svg)


class SplitStripTests(unittest.TestCase):
    def test_strip_clip_attr_removes_only_clip_path(self):
        from eps2svg_split import strip_clip_attr
        frag = '<path d="M0 0 L1 1" fill="#000000" clip-path="url(#clip1)"/>'
        out = strip_clip_attr(frag)
        self.assertNotIn("clip-path", out)
        self.assertIn('d="M0 0 L1 1"', out)
        self.assertIn('fill="#000000"', out)

    def test_icon_svg_keeps_path_without_dangling_clip(self):
        from eps2svg_split import _emit_icon_svg
        frag = '<path d="M2 2 L8 2 L8 8 Z" fill="#000000" clip-path="url(#clip1)"/>'
        svg = _emit_icon_svg([frag], (2.0, 2.0, 8.0, 8.0), 2.0)
        self.assertIn('d="M2 2 L8 2 L8 8 Z"', svg)   # path survives
        self.assertNotIn("clip-path", svg)            # no dangling reference


if __name__ == "__main__":
    unittest.main()
