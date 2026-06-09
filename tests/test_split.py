import unittest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


class FixtureSanityTests(unittest.TestCase):
    def test_grid_3x3_fixture_exists(self):
        self.assertTrue((FIXTURES / "grid_3x3.eps").exists())

    def test_grid_3x3_renders_nine_paths(self):
        from eps2svg_pure import Interpreter, tokenize, _ADOBE_PROLOG
        src = (FIXTURES / "grid_3x3.eps").read_text(encoding="latin-1")
        interp = Interpreter((0, 0, 300, 300))
        interp._exec_tokens(tokenize(_ADOBE_PROLOG))
        interp._exec_tokens(tokenize(src))
        # Each fill emits one <path …/> string into pages[-1]
        page = interp.pages[0]
        self.assertEqual(len([p for p in page if "<path " in p]), 9)


class PathMetaTests(unittest.TestCase):
    def test_grid_3x3_produces_nine_path_metas(self):
        from eps2svg_pure import Interpreter, tokenize, _ADOBE_PROLOG
        src = (FIXTURES / "grid_3x3.eps").read_text(encoding="latin-1")
        interp = Interpreter((0, 0, 300, 300))
        interp._exec_tokens(tokenize(_ADOBE_PROLOG))
        interp._exec_tokens(tokenize(src))
        self.assertEqual(len(interp.path_metadata), 9)
        for meta in interp.path_metadata:
            x0, y0, x1, y1 = meta.bbox
            # circle radius 20 → bbox width and height ~40 geometrically,
            # but bbox includes cubic Bezier control points which overshoot
            # the on-curve circle by r/3 each side (alpha = 4/3·tan(π/8) ≈ 0.55),
            # giving an actual bbox width of 8r/3 ≈ 53.33. delta of 15 covers
            # that overshoot.
            self.assertAlmostEqual(x1 - x0, 40.0, delta=15.0)
            self.assertAlmostEqual(y1 - y0, 40.0, delta=15.0)
            self.assertIsNone(meta.group_id)   # no gsave/grestore in this fixture


if __name__ == "__main__":
    unittest.main()
