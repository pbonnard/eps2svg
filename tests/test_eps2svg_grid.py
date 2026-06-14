import tempfile
import unittest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _uniform_cells(x0, y0, x1, y1, rows, cols):
    """Build row-major (row, col, x0, y0, x1, y1) cells without importing GUI code."""
    cells = []
    for r in range(rows):
        for c in range(cols):
            cells.append((
                r, c,
                x0 + (x1 - x0) * c / cols, y0 + (y1 - y0) * r / rows,
                x0 + (x1 - x0) * (c + 1) / cols, y0 + (y1 - y0) * (r + 1) / rows,
            ))
    return cells


class PrepareTests(unittest.TestCase):
    def test_prepare_reports_page_size_and_svg(self):
        import eps2svg_grid
        doc = eps2svg_grid.prepare_split(FIXTURES / "grid_3x3.eps")
        self.assertAlmostEqual(doc.width, 300.0, delta=0.5)
        self.assertAlmostEqual(doc.height, 300.0, delta=0.5)
        self.assertIn("<svg", doc.page_svg)
        self.assertIn("<path", doc.page_svg)


class ExtractTests(unittest.TestCase):
    def test_three_by_three_grid_yields_nine_cells(self):
        import eps2svg_grid
        doc = eps2svg_grid.prepare_split(FIXTURES / "grid_3x3.eps")
        cells = _uniform_cells(0, 0, 300, 300, 3, 3)
        results = doc.extract_grid(cells, pad=2.0)
        self.assertEqual(len(results), 9)
        for cr in results:
            self.assertEqual(cr.svg_text.count("<path"), 1)

    def test_finer_grid_skips_empty_cells(self):
        import eps2svg_grid
        doc = eps2svg_grid.prepare_split(FIXTURES / "grid_3x3.eps")
        cells = _uniform_cells(0, 0, 300, 300, 4, 4)  # 16 cells, only 9 have a circle
        results = doc.extract_grid(cells, pad=2.0)
        self.assertEqual(len(results), 9)

    def test_content_cell_count(self):
        import eps2svg_grid
        doc = eps2svg_grid.prepare_split(FIXTURES / "grid_3x3.eps")
        cells = _uniform_cells(0, 0, 300, 300, 3, 3)
        self.assertEqual(doc.content_cell_count(cells), 9)

    def test_write_grid_writes_files(self):
        import eps2svg_grid
        doc = eps2svg_grid.prepare_split(FIXTURES / "grid_3x3.eps")
        cells = _uniform_cells(0, 0, 300, 300, 3, 3)
        with tempfile.TemporaryDirectory() as d:
            written = eps2svg_grid.write_grid(doc, d, cells, stem="grid")
            self.assertEqual(len(written), 9)
            self.assertTrue(all(p.exists() for p in written))
            self.assertEqual(written[0].name, "grid-001.svg")

    def test_write_grid_pptx_writes_single_deck(self):
        import io
        import zipfile
        import eps2svg_grid
        doc = eps2svg_grid.prepare_split(FIXTURES / "grid_3x3.eps")
        cells = _uniform_cells(0, 0, 300, 300, 3, 3)
        with tempfile.TemporaryDirectory() as d:
            written = eps2svg_grid.write_grid(doc, d, cells, stem="grid", fmt="pptx")
            self.assertEqual(len(written), 1)
            self.assertEqual(written[0].name, "grid.pptx")
            zf = zipfile.ZipFile(io.BytesIO(written[0].read_bytes()))
            slides = [n for n in zf.namelist()
                      if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
            self.assertEqual(len(slides), 9)

    def test_write_grid_refuses_nonempty_dir_without_force(self):
        import eps2svg_grid
        doc = eps2svg_grid.prepare_split(FIXTURES / "grid_3x3.eps")
        cells = _uniform_cells(0, 0, 300, 300, 3, 3)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "existing.txt").write_text("x")
            with self.assertRaises(FileExistsError):
                eps2svg_grid.write_grid(doc, d, cells, stem="grid")
            written = eps2svg_grid.write_grid(doc, d, cells, stem="grid", force=True)
            self.assertEqual(len(written), 9)


class SuggestGridTests(unittest.TestCase):
    def test_suggests_three_by_three_for_grid_fixture(self):
        import eps2svg_grid
        doc = eps2svg_grid.prepare_split(FIXTURES / "grid_3x3.eps")
        suggestion = doc.suggest_grid()
        self.assertIsNotNone(suggestion)
        rows, cols, frame = suggestion
        self.assertEqual(rows, 3)
        self.assertEqual(cols, 3)
        x0, y0, x1, y1 = frame
        self.assertLess(x0, x1)
        self.assertLess(y0, y1)

    def test_suggest_grid_none_when_no_paths(self):
        import eps2svg_grid
        doc = eps2svg_grid.SplitDocument("<svg/>", 10.0, 10.0, [], (0, 0, 10, 10))
        self.assertIsNone(doc.suggest_grid())


class IgnoreBackgroundTests(unittest.TestCase):
    def _doc_with_background(self):
        from eps2svg_grid import SplitDocument, _PathRec
        # A full-page background rect (centre 150,150) plus one small icon
        # (centre 50,50), on a 300x300 page.
        recs = [
            _PathRec(svg_index=0, fragment="<path id='bg'/>",
                     bbox=(0, 0, 300, 300), group_id=None,
                     cx=150, cy=150, bbox_svg=(0, 0, 300, 300)),
            _PathRec(svg_index=1, fragment="<path id='icon'/>",
                     bbox=(40, 40, 60, 60), group_id=None,
                     cx=50, cy=50, bbox_svg=(40, 240, 60, 260)),
        ]
        return SplitDocument("<svg/>", 300.0, 300.0, recs, (0, 0, 300, 300))

    def test_ignore_background_drops_page_spanning_path(self):
        doc = self._doc_with_background()
        cells = _uniform_cells(0, 0, 300, 300, 2, 2)
        # Without the filter: background cell (1,1) and icon cell (0,0) both count.
        self.assertEqual(doc.content_cell_count(cells), 2)
        # With it: the page-spanning rect is dropped, only the icon remains.
        self.assertEqual(doc.content_cell_count(cells, ignore_background=True), 1)
        results = doc.extract_grid(cells, ignore_background=True)
        self.assertEqual(len(results), 1)
        self.assertIn("icon", results[0].svg_text)
