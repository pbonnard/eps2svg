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

    def test_run_split_stub_raises_not_implemented(self):
        import eps2svg_split
        from pathlib import Path
        with self.assertRaises(NotImplementedError):
            eps2svg_split.run_split(Path("nope.eps"), Path("/tmp/out"))


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


if __name__ == "__main__":
    unittest.main()
