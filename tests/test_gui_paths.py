import tempfile
import unittest
from pathlib import Path


class IsSupportedTests(unittest.TestCase):
    def test_accepts_eps_ps_epsf_any_case(self):
        from eps2svg_gui.paths import is_supported
        for name in ("a.eps", "B.PS", "c.epsf", "D.EpS"):
            self.assertTrue(is_supported(name), name)

    def test_rejects_others(self):
        from eps2svg_gui.paths import is_supported
        for name in ("a.svg", "b.png", "c.txt", "d"):
            self.assertFalse(is_supported(name), name)


class ResolveOutputPathTests(unittest.TestCase):
    def test_next_to_source_when_no_dir(self):
        from eps2svg_gui.paths import resolve_output_path
        out = resolve_output_path(Path("/x/y/logo.eps"))
        self.assertEqual(out, Path("/x/y/logo.svg"))

    def test_into_output_dir_keeps_stem(self):
        from eps2svg_gui.paths import resolve_output_path
        out = resolve_output_path(Path("/x/y/logo.eps"), output_dir=Path("/out"))
        self.assertEqual(out, Path("/out/logo.svg"))


class PredictBackendTests(unittest.TestCase):
    def _write(self, d, name, data):
        p = Path(d) / name
        p.write_bytes(data)
        return p

    def test_pptx_is_always_pure_python_and_certain(self):
        from eps2svg_gui.paths import predict_backend
        backend, predicted = predict_backend(Path("x.eps"), "pptx", True)
        self.assertEqual(backend, "Pure Python")
        self.assertFalse(predicted)

    def test_svg_without_ghostscript_is_pure_python_and_certain(self):
        from eps2svg_gui.paths import predict_backend
        backend, predicted = predict_backend(Path("x.eps"), "svg", False)
        self.assertEqual(backend, "Pure Python")
        self.assertFalse(predicted)

    def test_svg_with_ghostscript_guesses_ghostscript_for_agm(self):
        from eps2svg_gui.paths import predict_backend
        with tempfile.TemporaryDirectory() as d:
            agm = self._write(d, "ai.eps",
                              b"%!PS-Adobe-3.1 EPSF-3.0\n%%Creator: Adobe\n"
                              b"%%BeginResource: procset Adobe_AGM_Core 2.0 0\n")
            backend, predicted = predict_backend(agm, "svg", True)
            self.assertEqual(backend, "Ghostscript")
            self.assertTrue(predicted)

    def test_svg_with_ghostscript_guesses_pure_python_for_plain(self):
        from eps2svg_gui.paths import predict_backend
        with tempfile.TemporaryDirectory() as d:
            plain = self._write(d, "plain.eps",
                                b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n")
            backend, predicted = predict_backend(plain, "svg", True)
            self.assertEqual(backend, "Pure Python")
            self.assertTrue(predicted)


class EnumerateInputsTests(unittest.TestCase):
    def test_keeps_supported_files_and_drops_others(self):
        from eps2svg_gui.paths import enumerate_inputs
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "a.eps").write_text("x")
            (d / "b.txt").write_text("x")
            got = enumerate_inputs([d / "a.eps", d / "b.txt"])
            self.assertEqual([p.name for p in got], ["a.eps"])

    def test_scans_directory_nonrecursive_then_recursive(self):
        from eps2svg_gui.paths import enumerate_inputs
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "top.eps").write_text("x")
            sub = d / "sub"
            sub.mkdir()
            (sub / "deep.ps").write_text("x")
            flat = enumerate_inputs([d], recursive=False)
            self.assertEqual(sorted(p.name for p in flat), ["top.eps"])
            deep = enumerate_inputs([d], recursive=True)
            self.assertEqual(sorted(p.name for p in deep), ["deep.ps", "top.eps"])

    def test_deduplicates(self):
        from eps2svg_gui.paths import enumerate_inputs
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            f = d / "a.eps"
            f.write_text("x")
            got = enumerate_inputs([f, f, d])
            self.assertEqual(len(got), 1)
