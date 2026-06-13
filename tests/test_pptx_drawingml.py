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


class ShapeXmlTests(unittest.TestCase):
    def _identity(self):
        return lambda X, Y: (X, Y)  # EMU == input units for easy assertions

    def test_filled_square_shape(self):
        from eps2pptx.drawingml import shape_xml
        xml = shape_xml(
            "M0 0 L100 0 L100 100 L0 100 Z",
            {"fill": "#ff0000", "stroke": "none"},
            self._identity(), s=1.0, shape_id=2,
        )
        self.assertIn("<p:sp>", xml)
        self.assertIn("<a:custGeom>", xml)
        self.assertIn("<a:moveTo>", xml)
        self.assertIn("<a:lnTo>", xml)
        self.assertIn("<a:close/>", xml)
        self.assertIn('<a:srgbClr val="FF0000"/>', xml)
        self.assertIn('<a:ext cx="100" cy="100"/>', xml)

    def test_cubic_emits_cubicbezto_with_three_points(self):
        from eps2pptx.drawingml import shape_xml
        xml = shape_xml(
            "M0 0 C0 50 50 100 100 100",
            {"fill": "#000000", "stroke": "none"},
            self._identity(), s=1.0, shape_id=3,
        )
        self.assertIn("<a:cubicBezTo>", xml)
        self.assertEqual(xml.count("<a:pt", xml.find("<a:cubicBezTo>")), 3 + 0)  # 3 pts inside

    def test_stroke_path_emits_line_and_nofill(self):
        from eps2pptx.drawingml import shape_xml
        xml = shape_xml(
            "M0 0 L100 0",
            {"fill": "none", "stroke": "#00ff00", "stroke-width": "2"},
            self._identity(), s=1.0, shape_id=4,
        )
        self.assertIn("<a:noFill/>", xml)
        self.assertIn("<a:ln", xml)
        self.assertIn('<a:srgbClr val="00FF00"/>', xml)

    def test_empty_d_returns_none(self):
        from eps2pptx.drawingml import shape_xml
        self.assertIsNone(shape_xml("", {"fill": "#000000"}, self._identity(),
                                    s=1.0, shape_id=2))

    def test_line_child_order_dash_before_join(self):
        # CT_LineProperties requires fill -> prstDash -> join order; real
        # PowerPoint rejects the reverse even though python-pptx tolerates it.
        from eps2pptx.drawingml import shape_xml
        xml = shape_xml(
            "M0 0 L100 0 L100 100",
            {"fill": "none", "stroke": "#000000", "stroke-width": "2",
             "stroke-linejoin": "miter", "stroke-dasharray": "3,3"},
            self._identity(), s=1.0, shape_id=5,
        )
        self.assertIn("<a:prstDash", xml)
        self.assertIn("<a:miter/>", xml)
        self.assertLess(xml.index("<a:prstDash"), xml.index("<a:miter/>"))


class PictureXmlTests(unittest.TestCase):
    def test_picture_references_embed_rid(self):
        from eps2pptx.drawingml import picture_xml
        xml = picture_xml(off=(10, 20), ext=(300, 400), rid="rId2", pic_id=2)
        self.assertIn("<p:pic>", xml)
        self.assertIn('r:embed="rId2"', xml)
        self.assertIn('<a:off x="10" y="20"/>', xml)
        self.assertIn('<a:ext cx="300" cy="400"/>', xml)
