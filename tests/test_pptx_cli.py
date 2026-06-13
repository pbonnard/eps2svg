import tempfile
import unittest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


class CliFormatTests(unittest.TestCase):
    def test_format_pptx_writes_pptx(self):
        import eps2svg
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.pptx"
            rc = eps2svg.main([str(FIXTURES / "grid_3x3.eps"),
                               "--format", "pptx", "-o", str(out)])
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 0)

    def test_default_output_uses_pptx_extension(self):
        import eps2svg
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "logo.eps"
            src.write_bytes((FIXTURES / "grid_3x3.eps").read_bytes())
            rc = eps2svg.main([str(src), "--format", "pptx"])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(d) / "logo.pptx").exists())

    def test_format_pptx_with_nonpure_backend_errors(self):
        import eps2svg
        with self.assertRaises(SystemExit):
            eps2svg.main([str(FIXTURES / "grid_3x3.eps"),
                          "--format", "pptx", "--backend", "inkscape"])
