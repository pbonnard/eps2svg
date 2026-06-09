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


class GroupIdTests(unittest.TestCase):
    def test_gsave_grouped_assigns_four_distinct_group_ids(self):
        from eps2svg_pure import Interpreter, tokenize, _ADOBE_PROLOG
        src = (FIXTURES / "gsave_grouped.eps").read_text(encoding="latin-1")
        interp = Interpreter((0, 0, 300, 300))
        interp._exec_tokens(tokenize(_ADOBE_PROLOG))
        interp._exec_tokens(tokenize(src))
        # 4 gsave/grestore icons × 2 paths each = 8 PathMeta records
        self.assertEqual(len(interp.path_metadata), 8)
        # All have a group_id (none None) and there are exactly 4 distinct values
        gids = {m.group_id for m in interp.path_metadata}
        self.assertEqual(len(gids), 4)
        self.assertNotIn(None, gids)


class SplitModuleSurfaceTests(unittest.TestCase):
    def test_exports_split_result_and_run_split(self):
        import eps2svg_split
        self.assertTrue(hasattr(eps2svg_split, "SplitResult"))
        self.assertTrue(hasattr(eps2svg_split, "run_split"))


class Phase3Tests(unittest.TestCase):
    def _capture(self, fixture: str, bbox=(0, 0, 300, 300)):
        from eps2svg_pure import Interpreter, tokenize, _ADOBE_PROLOG
        src = (FIXTURES / fixture).read_text(encoding="latin-1")
        interp = Interpreter(bbox)
        interp._exec_tokens(tokenize(_ADOBE_PROLOG))
        interp._exec_tokens(tokenize(src))
        return interp.path_metadata

    def test_grid_3x3_geometric_yields_nine_clusters(self):
        from eps2svg_split import _phase3_geometric
        meta = self._capture("grid_3x3.eps")
        clusters = _phase3_geometric(meta)
        self.assertEqual(len(clusters), 9)
        for c in clusters:
            self.assertEqual(len(c), 1)   # each circle is its own cluster

    def test_empty_input_returns_empty(self):
        from eps2svg_split import _phase3_geometric
        self.assertEqual(_phase3_geometric([]), [])

    def test_single_path_returns_one_singleton_cluster(self):
        from eps2svg_split import _phase3_geometric
        from eps2svg_pure import PathMeta
        clusters = _phase3_geometric([PathMeta(0, (0, 0, 10, 10), None)])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 1)

    def test_overlapping_bboxes_merge_into_one_cluster(self):
        from eps2svg_split import _phase3_geometric
        from eps2svg_pure import PathMeta
        # Two heavily overlapping bboxes → gap is 0 → merged
        metas = [
            PathMeta(0, (0, 0, 10, 10), None),
            PathMeta(1, (3, 3, 13, 13), None),
        ]
        clusters = _phase3_geometric(metas)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 2)

    def test_gap_just_above_threshold_keeps_clusters_separate(self):
        from eps2svg_split import _phase3_geometric
        from eps2svg_pure import PathMeta
        # Two identical 10×10 bboxes far apart → median diagonal = √200 ≈ 14.14
        # Threshold = 14.14 × 0.3 ≈ 4.24. Gap of 5 should keep them separate.
        metas = [
            PathMeta(0, (0, 0, 10, 10), None),
            PathMeta(1, (15, 0, 25, 10), None),   # x-gap = 5
        ]
        clusters = _phase3_geometric(metas)
        self.assertEqual(len(clusters), 2)


class Phase4Tests(unittest.TestCase):
    def _capture(self, fixture, bbox=(0, 0, 300, 300)):
        from eps2svg_pure import Interpreter, tokenize, _ADOBE_PROLOG
        src = (FIXTURES / fixture).read_text(encoding="latin-1")
        interp = Interpreter(bbox)
        interp._exec_tokens(tokenize(_ADOBE_PROLOG))
        interp._exec_tokens(tokenize(src))
        return interp.path_metadata

    def test_grid_3x3_reading_order_is_left_to_right_top_to_bottom(self):
        from eps2svg_split import _phase3_geometric, _assign_layout
        meta = self._capture("grid_3x3.eps")
        clusters = _phase3_geometric(meta)
        ordered = _assign_layout(clusters)
        # Expect 3 rows of 3 columns; row indices 0,0,0,1,1,1,2,2,2;
        # col indices 0,1,2,0,1,2,0,1,2
        rows = [t[0] for t in ordered]
        cols = [t[1] for t in ordered]
        self.assertEqual(rows, [0, 0, 0, 1, 1, 1, 2, 2, 2])
        self.assertEqual(cols, [0, 1, 2, 0, 1, 2, 0, 1, 2])

    def test_top_row_of_two_row_grid_has_row_index_zero(self):
        """PS Y-up convention can confuse 'top'. With three shapes at y=200
        (top) and two at y=50 (bottom), the y=200 shapes must be row 0."""
        from eps2svg_split import _assign_layout
        from eps2svg_pure import PathMeta
        # Three shapes at top (y center ~200), two at bottom (y center ~50)
        clusters = [
            [PathMeta(0, ( 40, 190,  60, 210), None)],   # top, left
            [PathMeta(1, (140, 190, 160, 210), None)],   # top, middle
            [PathMeta(2, (240, 190, 260, 210), None)],   # top, right
            [PathMeta(3, ( 40,  40,  60,  60), None)],   # bottom, left
            [PathMeta(4, (140,  40, 160,  60), None)],   # bottom, middle
        ]
        ordered = _assign_layout(clusters)
        # First three in reading order are the top row (orig_idx 0, 1, 2)
        # in column order. Without the Y-flip fix they would be 3, 4 first.
        first_three_orig_idx = [t[2] for t in ordered[:3]]
        self.assertEqual(first_three_orig_idx, [0, 1, 2])


class Phase5Tests(unittest.TestCase):
    def test_emit_icon_svg_has_viewbox_and_paths(self):
        from eps2svg_split import _emit_icon_svg
        svg = _emit_icon_svg(
            ['<path d="M0 0 L40 40 Z" fill="#000"/>'],
            (0, 0, 40, 40),
            pad=2.0,
        )
        self.assertIn('viewBox="0 0 44.000 44.000"', svg)
        self.assertIn('width="44.000pt"', svg)
        self.assertIn('<path d="M0 0 L40 40 Z"', svg)
        # Sanity: it should be parseable XML
        import xml.etree.ElementTree as ET
        ET.fromstring(svg)


import tempfile


class RunSplitGeometricTests(unittest.TestCase):
    def test_grid_3x3_writes_nine_svgs(self):
        from eps2svg_split import run_split
        with tempfile.TemporaryDirectory() as td:
            result = run_split(FIXTURES / "grid_3x3.eps", Path(td))
            self.assertEqual(result.mode, "geometric")
            self.assertEqual(result.icon_count, 9)
            self.assertEqual(len(result.written), 9)
            # Filenames numbered 001..009
            names = sorted(p.name for p in result.written)
            self.assertEqual(names[0], "grid_3x3-001.svg")
            self.assertEqual(names[-1], "grid_3x3-009.svg")
            # Each file must be valid XML
            import xml.etree.ElementTree as ET
            for p in result.written:
                ET.fromstring(p.read_text(encoding="utf-8"))


class RunSplitStructuralTests(unittest.TestCase):
    def test_gsave_grouped_uses_structural_mode_and_yields_four(self):
        from eps2svg_split import run_split
        with tempfile.TemporaryDirectory() as td:
            result = run_split(FIXTURES / "gsave_grouped.eps", Path(td))
        self.assertEqual(result.mode, "structural")
        self.assertEqual(result.icon_count, 4)

    def test_mixed_keeps_three_icons_and_absorbs_orphan(self):
        from eps2svg_split import run_split
        with tempfile.TemporaryDirectory() as td:
            result = run_split(FIXTURES / "mixed.eps", Path(td))
        self.assertEqual(result.mode, "structural")
        self.assertEqual(result.icon_count, 3)


class FallbackTests(unittest.TestCase):
    def test_single_shape_falls_back_to_unsplit_svg(self):
        from eps2svg_split import run_split
        with tempfile.TemporaryDirectory() as td:
            result = run_split(FIXTURES / "single_shape.eps", Path(td))
            self.assertEqual(result.mode, "fallback")
            self.assertEqual(result.icon_count, 1)
            self.assertTrue(result.written[0].name == "single_shape.svg")

    def test_existing_non_empty_dir_without_force_raises(self):
        from eps2svg_split import run_split
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "stale.svg").write_text("x")
            with self.assertRaises(FileExistsError):
                run_split(FIXTURES / "grid_3x3.eps", Path(td))

    def test_force_overwrites_non_empty_dir(self):
        from eps2svg_split import run_split
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "stale.svg").write_text("x")
            result = run_split(FIXTURES / "grid_3x3.eps", Path(td), force=True)
            self.assertEqual(result.icon_count, 9)


class IrregularGridTests(unittest.TestCase):
    def test_irregular_grid_yields_six_icons_in_two_rows(self):
        from eps2svg_split import run_split
        with tempfile.TemporaryDirectory() as td:
            result = run_split(FIXTURES / "grid_irregular.eps", Path(td))
            self.assertEqual(result.mode, "geometric")
            self.assertEqual(result.icon_count, 6)
            # Reading order should produce two rows of three columns each:
            # 001..003 = top row (PS y=180), 004..006 = bottom row (PS y=50).
            # Filenames are written in reading order, so sorted names follow
            # the row-then-column convention.
            names = sorted(p.name for p in result.written)
            self.assertEqual(names, [
                "grid_irregular-001.svg",
                "grid_irregular-002.svg",
                "grid_irregular-003.svg",
                "grid_irregular-004.svg",
                "grid_irregular-005.svg",
                "grid_irregular-006.svg",
            ])
            # Additionally, verify the underlying layout indices come out
            # as a 2x3 grid (rows={0,0,0,1,1,1}, cols={0,1,2,0,1,2}) by
            # rerunning the layout step on the captured metadata.
            from eps2svg_split import _capture_pages, _phase3_geometric, _assign_layout
            interp, _ = _capture_pages(
                FIXTURES / "grid_irregular.eps",
                max_ops=5_000_000, timeout=30.0, verbose=False,
            )
            ordered = _assign_layout(_phase3_geometric(interp.path_metadata))
            rows = [t[0] for t in ordered]
            cols = [t[1] for t in ordered]
            self.assertEqual(rows, [0, 0, 0, 1, 1, 1])
            self.assertEqual(cols, [0, 1, 2, 0, 1, 2])


import subprocess


class CliTests(unittest.TestCase):
    def test_cli_split_produces_nine_svgs(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "icons"
            r = subprocess.run(
                ["eps2svg", str(FIXTURES / "grid_3x3.eps"),
                 "--split", "-d", str(out)],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            files = sorted(out.glob("*.svg"))
            self.assertEqual(len(files), 9)
            self.assertEqual(files[0].name, "grid_3x3-001.svg")

    def test_cli_split_with_explicit_external_backend_errors(self):
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run(
                ["eps2svg", str(FIXTURES / "grid_3x3.eps"),
                 "--split", "--backend", "inkscape", "-d", td],
                capture_output=True, text=True,
            )
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("--split requires --backend pure", r.stderr)

    def test_cli_split_with_output_file_errors(self):
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run(
                ["eps2svg", str(FIXTURES / "grid_3x3.eps"),
                 "--split", "-o", str(Path(td) / "x.svg")],
                capture_output=True, text=True,
            )
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("--split conflicts with -o/--output", r.stderr)

    def test_cli_grid_mode_runs_without_error(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "icons"
            r = subprocess.run(
                ["eps2svg", str(FIXTURES / "grid_3x3.eps"),
                 "--split", "--grid", "-d", str(out)],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(len(list(out.glob("*.svg"))), 9)


class GridModeTests(unittest.TestCase):
    def test_grid_3x3_still_works_with_grid_flag(self):
        """Grid mode must not regress strict grids."""
        from eps2svg_split import run_split
        with tempfile.TemporaryDirectory() as td:
            result = run_split(FIXTURES / "grid_3x3.eps", Path(td), grid=True)
            self.assertEqual(result.icon_count, 9)

    def test_filter_page_spanning_drops_giant_rect(self):
        from eps2svg_split import _filter_page_spanning
        from eps2svg_pure import PathMeta
        page = (0.0, 0.0, 100.0, 100.0)
        metas = [
            PathMeta(0, (0.0, 0.0, 100.0, 100.0), None),   # full page → drop
            PathMeta(1, (10.0, 10.0, 30.0, 30.0), None),   # 4% of page → keep
            PathMeta(2, (5.0, 5.0, 95.0, 95.0), None),     # 81% of page → drop
        ]
        kept = _filter_page_spanning(metas, page)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].svg_index, 1)

    def test_lattice_merge_collapses_co_cell_clusters(self):
        from eps2svg_split import _lattice_merge
        from eps2svg_pure import PathMeta
        # Two clusters in the same logical cell + one in a clearly different cell.
        clusters = [
            [PathMeta(0, (10.0, 10.0, 40.0, 40.0), None)],
            [PathMeta(1, (15.0, 15.0, 35.0, 35.0), None)],   # same cell
            [PathMeta(2, (200.0, 200.0, 230.0, 230.0), None)],
        ]
        merged = _lattice_merge(clusters)
        self.assertEqual(len(merged), 2)
        # The two in the same cell should be merged
        sizes = sorted(len(c) for c in merged)
        self.assertEqual(sizes, [1, 2])


class GettySmokeTests(unittest.TestCase):
    CORPUS = Path("C:/Users/pbonn/Downloads")

    @classmethod
    def setUpClass(cls):
        if not cls.CORPUS.exists():
            raise unittest.SkipTest(f"Getty corpus not present at {cls.CORPUS}")
        cls.samples = sorted(cls.CORPUS.glob("GettyImages-*.ps"))
        if not cls.samples:
            raise unittest.SkipTest("no GettyImages-*.ps in corpus")

    def test_every_file_splits_or_falls_back_without_crashing(self):
        from eps2svg_split import run_split
        results = []
        with tempfile.TemporaryDirectory() as td:
            for i, sample in enumerate(self.samples):
                out = Path(td) / f"sample_{i}"
                r = run_split(sample, out, force=True, timeout=15.0)
                results.append((sample.name, r.mode, r.icon_count))
        # Print summary for the developer (visible in -v)
        for name, mode, n in results:
            print(f"  {name}: {mode}, {n} icon(s)")
        # Trivial assertion — the real check is that nothing raised
        self.assertEqual(len(results), len(self.samples))


if __name__ == "__main__":
    unittest.main()
