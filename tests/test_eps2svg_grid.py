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
