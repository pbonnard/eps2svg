import unittest


class ParsePathDTests(unittest.TestCase):
    def test_parses_move_line_close(self):
        from eps2pptx.drawingml import parse_path_d
        cmds = parse_path_d("M0.000 0.000 L10.000 0.000 L10.000 10.000 Z")
        self.assertEqual(cmds, [
            ("M", [0.0, 0.0]),
            ("L", [10.0, 0.0]),
            ("L", [10.0, 10.0]),
            ("Z", []),
        ])

    def test_parses_cubic(self):
        from eps2pptx.drawingml import parse_path_d
        cmds = parse_path_d("M1.000 2.000 C3.000 4.000 5.000 6.000 7.000 8.000")
        self.assertEqual(cmds[0], ("M", [1.0, 2.0]))
        self.assertEqual(cmds[1], ("C", [3.0, 4.0, 5.0, 6.0, 7.0, 8.0]))


class ParseFragmentTests(unittest.TestCase):
    def test_parses_fill_path(self):
        from eps2pptx.drawingml import parse_fragment
        d, style = parse_fragment(
            '<path d="M0 0 L1 0 Z" fill="#ff0000" fill-rule="nonzero" stroke="none"/>'
        )
        self.assertEqual(d, "M0 0 L1 0 Z")
        self.assertEqual(style["fill"], "#ff0000")
        self.assertEqual(style["stroke"], "none")

    def test_parses_stroke_path(self):
        from eps2pptx.drawingml import parse_fragment
        d, style = parse_fragment(
            '<path d="M0 0 L9 9" fill="none" stroke="#00ff00" stroke-width="2.500"/>'
        )
        self.assertEqual(style["fill"], "none")
        self.assertEqual(style["stroke"], "#00ff00")
        self.assertEqual(style["stroke-width"], "2.500")
