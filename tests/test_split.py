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


if __name__ == "__main__":
    unittest.main()
