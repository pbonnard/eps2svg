"""Auto-backend fall-through: when the pure-Python interpreter produces a
low-fidelity render (e.g. Adobe AGM artwork whose drawing operators it cannot
execute), `convert()` should prefer a higher-fidelity backend if one succeeds,
but keep the pure-Python partial when nothing better is available."""

import tempfile
import unittest
from pathlib import Path

import eps2svg

FIXTURES = Path(__file__).parent / "fixtures"

# One real stroke, then many undefined operators -> high dropped-op fraction,
# so the pure interpreter flags the render as low fidelity.
LOW_FI_EPS = (
    "%!PS-Adobe-3.0 EPSF-3.0\n"
    "%%BoundingBox: 0 0 100 100\n"
    "%%EndComments\n"
    "newpath 10 10 moveto 90 90 lineto stroke\n"
    + ("zzz\n" * 60)
)


def _fake_better(record):
    def better(src, dst, *args, **kwargs):
        record.append("better")
        Path(dst).write_text('<svg id="better"></svg>', encoding="utf-8")
        return True
    return better


class FallthroughTests(unittest.TestCase):
    def setUp(self):
        self._orig_backends = eps2svg.BACKENDS

    def tearDown(self):
        eps2svg.BACKENDS = self._orig_backends

    def _tmp(self, text=None):
        d = Path(tempfile.mkdtemp())
        dst = d / "out.svg"
        if text is None:
            return None, dst
        src = d / "in.eps"
        src.write_text(text, encoding="utf-8")
        return src, dst

    def test_low_fidelity_pure_falls_through_to_better_backend(self):
        calls = []
        eps2svg.BACKENDS = [
            ("Pure Python", eps2svg._pure_python),
            ("Fake Better", _fake_better(calls)),
        ]
        src, dst = self._tmp(LOW_FI_EPS)
        name = eps2svg.convert(src, dst, strip_bg=False)
        self.assertEqual(name, "Fake Better")
        self.assertIn("better", dst.read_text(encoding="utf-8"))
        self.assertEqual(calls, ["better"])

    def test_low_fidelity_pure_kept_when_no_better_backend(self):
        eps2svg.BACKENDS = [("Pure Python", eps2svg._pure_python)]
        src, dst = self._tmp(LOW_FI_EPS)
        name = eps2svg.convert(src, dst, strip_bg=False)
        self.assertTrue(name.startswith("Pure Python"), name)
        self.assertTrue(dst.exists() and dst.stat().st_size > 0)
        self.assertIn("svg", dst.read_text(encoding="utf-8").lower())

    def test_low_fidelity_does_not_inherit_stale_render(self):
        # Regression: a backend that reports success only if the output file
        # exists (like Inkscape, which exits 0 even on failure) must NOT inherit
        # the stashed pure-Python render. The stash must move dst aside, not copy.
        def existence_only(src, dst, *args, **kwargs):
            return Path(dst).exists()
        eps2svg.BACKENDS = [
            ("Pure Python", eps2svg._pure_python),
            ("Bad Inkscape", existence_only),
        ]
        src, dst = self._tmp(LOW_FI_EPS)
        name = eps2svg.convert(src, dst, strip_bg=False)
        self.assertTrue(name.startswith("Pure Python"), name)
        self.assertTrue(dst.exists() and dst.stat().st_size > 0)

    def test_clean_pure_render_does_not_fall_through(self):
        calls = []
        eps2svg.BACKENDS = [
            ("Pure Python", eps2svg._pure_python),
            ("Fake Better", _fake_better(calls)),
        ]
        _, dst = self._tmp()
        name = eps2svg.convert(FIXTURES / "grid_3x3.eps", dst, strip_bg=False)
        self.assertEqual(name, "Pure Python")
        self.assertEqual(calls, [])  # higher-fidelity backend never tried


class AgmShortCircuitTests(unittest.TestCase):
    def setUp(self):
        self._orig_backends = eps2svg.BACKENDS
        self._orig_find_gs = eps2svg._find_gs

    def tearDown(self):
        eps2svg.BACKENDS = self._orig_backends
        eps2svg._find_gs = self._orig_find_gs

    def _backends(self, calls):
        def pure(src, dst, *args, **kwargs):
            calls.append("pure")
            Path(dst).write_text("<svg/>", encoding="utf-8")
            stats = kwargs.get("stats")
            if stats is not None:
                stats["low_fidelity"] = False
            return True

        def gs(src, dst, *args, **kwargs):
            calls.append("gs")
            Path(dst).write_text('<svg id="gs"/>', encoding="utf-8")
            return True

        return [("Pure Python", pure), ("Ghostscript + Fake", gs)]

    def _src(self, d, name, data):
        p = Path(d) / name
        p.write_bytes(data)
        return p

    def test_agm_with_gs_skips_pure_python(self):
        calls = []
        eps2svg.BACKENDS = self._backends(calls)
        eps2svg._find_gs = lambda: "gs.exe"
        with tempfile.TemporaryDirectory() as d:
            src = self._src(d, "ai.eps",
                            b"%!PS\n%%BeginResource: procset Adobe_AGM_Core 2.0 0\n")
            name = eps2svg.convert(src, Path(d) / "o.svg", strip_bg=False)
            self.assertEqual(name, "Ghostscript + Fake")
            self.assertEqual(calls, ["gs"])  # pure-Python never ran

    def test_non_agm_keeps_pure_python_first(self):
        calls = []
        eps2svg.BACKENDS = self._backends(calls)
        eps2svg._find_gs = lambda: "gs.exe"
        with tempfile.TemporaryDirectory() as d:
            src = self._src(d, "plain.eps",
                            b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 9 9\n")
            name = eps2svg.convert(src, Path(d) / "o.svg", strip_bg=False)
            self.assertEqual(name, "Pure Python")
            self.assertEqual(calls, ["pure"])  # GS not reached

    def test_agm_without_gs_keeps_pure_python_first(self):
        calls = []
        eps2svg.BACKENDS = self._backends(calls)
        eps2svg._find_gs = lambda: None
        with tempfile.TemporaryDirectory() as d:
            src = self._src(d, "ai.eps", b"%!PS Adobe_AGM_Core\n")
            name = eps2svg.convert(src, Path(d) / "o.svg", strip_bg=False)
            self.assertEqual(name, "Pure Python")
            self.assertEqual(calls, ["pure"])


def _have_gs_and_fitz():
    if not eps2svg._find_gs():
        return False
    try:
        import fitz  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_have_gs_and_fitz(), "Ghostscript + PyMuPDF not available")
class GsPyMuPdfTests(unittest.TestCase):
    def test_gs_pymupdf_writes_svg_and_does_not_crash_on_temp_cleanup(self):
        # Regression: the temp PDF must be closed before unlink, else Windows
        # raises WinError 32 from the finally block and aborts the conversion.
        dst = Path(tempfile.mkdtemp()) / "out.svg"
        ok = eps2svg._gs_pymupdf(FIXTURES / "grid_3x3.eps", dst, 96, False, page=None)
        self.assertTrue(ok)
        self.assertTrue(dst.exists() and dst.stat().st_size > 0)


if __name__ == "__main__":
    unittest.main()
