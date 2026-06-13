import unittest


class UniformTests(unittest.TestCase):
    def test_uniform_produces_rows_times_cols_equal_cells(self):
        from eps2svg_gui.grid_model import GridSpec
        spec = GridSpec.uniform((0, 0, 300, 300), 3, 3)
        cells = spec.cell_rects()
        self.assertEqual(len(cells), 9)
        for row, col, x0, y0, x1, y1 in cells:
            self.assertAlmostEqual(x1 - x0, 100.0)
            self.assertAlmostEqual(y1 - y0, 100.0)

    def test_rows_cols_properties(self):
        from eps2svg_gui.grid_model import GridSpec
        spec = GridSpec.uniform((0, 0, 200, 100), 2, 4)
        self.assertEqual(spec.rows, 2)
        self.assertEqual(spec.cols, 4)

    def test_cell_rects_are_row_major(self):
        from eps2svg_gui.grid_model import GridSpec
        spec = GridSpec.uniform((0, 0, 200, 200), 2, 2)
        coords = [(r, c) for r, c, *_ in spec.cell_rects()]
        self.assertEqual(coords, [(0, 0), (0, 1), (1, 0), (1, 1)])


class MutatorTests(unittest.TestCase):
    def test_translated_shifts_frame_and_lines(self):
        from eps2svg_gui.grid_model import GridSpec, translated
        spec = translated(GridSpec.uniform((0, 0, 100, 100), 2, 2), 10, 20)
        self.assertEqual(spec.frame, (10, 20, 110, 120))
        self.assertEqual(spec.col_lines, [60.0])
        self.assertEqual(spec.row_lines, [70.0])

    def test_resized_rescales_interior_lines(self):
        from eps2svg_gui.grid_model import GridSpec, resized
        spec = resized(GridSpec.uniform((0, 0, 100, 100), 2, 2), (0, 0, 200, 200))
        self.assertEqual(spec.frame, (0, 0, 200, 200))
        self.assertEqual(spec.col_lines, [100.0])
        self.assertEqual(spec.row_lines, [100.0])

    def test_with_col_line_clamps_between_neighbors(self):
        from eps2svg_gui.grid_model import GridSpec, with_col_line
        spec = GridSpec.uniform((0, 0, 300, 300), 3, 3)  # col_lines [100, 200]
        self.assertEqual(with_col_line(spec, 0, 50).col_lines, [50.0, 200.0])
        self.assertEqual(with_col_line(spec, 0, 250).col_lines, [200.0, 200.0])

    def test_with_row_line_clamps_between_neighbors(self):
        from eps2svg_gui.grid_model import GridSpec, with_row_line
        spec = GridSpec.uniform((0, 0, 300, 300), 3, 3)  # row_lines [100, 200]
        self.assertEqual(with_row_line(spec, 1, 250).row_lines, [100.0, 250.0])
        self.assertEqual(with_row_line(spec, 1, 50).row_lines, [100.0, 100.0])
