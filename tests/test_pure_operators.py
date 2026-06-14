"""Standard PostScript operators added in the corpus-driven 'easy batch':
bitshift, rand/srand/rrand, concatmatrix/invertmatrix, makefont, output stubs."""

import unittest

from eps2svg_pure import Interpreter, tokenize


def _run(src):
    interp = Interpreter((0, 0, 100, 100))
    interp._exec_tokens(tokenize(src))
    return interp


class BitwiseTests(unittest.TestCase):
    def test_bitshift_left(self):
        self.assertEqual(_run("8 2 bitshift").stack[-1], 32)

    def test_bitshift_right(self):
        self.assertEqual(_run("32 -2 bitshift").stack[-1], 8)

    def test_xor(self):
        self.assertEqual(_run("12 10 xor").stack[-1], 6)


class RandomTests(unittest.TestCase):
    def test_rand_is_deterministic_across_runs(self):
        self.assertEqual(_run("rand").stack[-1], _run("rand").stack[-1])

    def test_rand_in_range(self):
        v = _run("rand").stack[-1]
        self.assertTrue(0 <= v <= 0x7FFFFFFF)

    def test_srand_reseeds_reproducibly(self):
        a = _run("42 srand rand rand").stack[-2:]
        b = _run("42 srand rand rand").stack[-2:]
        self.assertEqual(a, b)

    def test_rrand_returns_seed(self):
        self.assertEqual(_run("7 srand rrand").stack[-1], 7)


class MatrixTests(unittest.TestCase):
    def test_concatmatrix(self):
        # [translate 10,20] × [scale 2,3] = [2 0 0 3 20 60]
        i = _run("[1 0 0 1 10 20] [2 0 0 3 0 0] [0 0 0 0 0 0] concatmatrix")
        self.assertEqual([round(x, 3) for x in i.stack[-1]], [2, 0, 0, 3, 20, 60])

    def test_invertmatrix(self):
        i = _run("[2 0 0 4 10 20] [0 0 0 0 0 0] invertmatrix")
        self.assertEqual([round(x, 3) for x in i.stack[-1]],
                         [0.5, 0, 0, 0.25, -5, -5])

    def test_invert_then_concat_is_identity(self):
        i = _run("[2 0 0 4 10 20] dup [0 0 0 0 0 0] invertmatrix "
                 "[0 0 0 0 0 0] concatmatrix")
        self.assertEqual([round(x, 3) for x in i.stack[-1]], [1, 0, 0, 1, 0, 0])


class StubTests(unittest.TestCase):
    def test_equals_pops_one(self):
        i = _run("1 2 =")
        self.assertEqual(i.stack, [1])

    def test_print_pops_string(self):
        self.assertEqual(_run("(hello) print").stack, [])

    def test_stack_does_not_pop(self):
        self.assertEqual(_run("1 2 stack").stack, [1, 2])

    def test_makefont_pops_matrix_leaves_font(self):
        # findfont leaves a font dict; makefont consumes the matrix, keeps font.
        i = _run("/Helvetica findfont [12 0 0 12 0 0] makefont")
        self.assertEqual(len(i.stack), 1)
        self.assertIsInstance(i.stack[-1], dict)


class DictTests(unittest.TestCase):
    def test_dict_constructor(self):
        self.assertEqual(_run("<< /a 1 /b 2 >>").stack[-1], {"a": 1, "b": 2})

    def test_empty_dict_constructor(self):
        self.assertEqual(_run("<< >>").stack[-1], {})

    def test_known_true_and_false(self):
        self.assertTrue(_run("<< /a 1 >> /a known").stack[-1])
        self.assertFalse(_run("<< /a 1 >> /b known").stack[-1])

    def test_dict_get_after_constructor(self):
        self.assertEqual(_run("<< /a 42 >> /a get").stack[-1], 42)

    def test_hex_string_still_works(self):
        # `<<` must not break `<hex>` strings.
        self.assertEqual(_run("<4142>").stack[-1], "AB")


class TypeTests(unittest.TestCase):
    def test_type_matches_via_eq(self):
        self.assertTrue(_run("5 type /integertype eq").stack[-1])
        self.assertTrue(_run("5.5 type /realtype eq").stack[-1])
        self.assertTrue(_run("/foo type /nametype eq").stack[-1])
        self.assertTrue(_run("(hi) type /stringtype eq").stack[-1])
        self.assertTrue(_run("<< >> type /dicttype eq").stack[-1])
        self.assertTrue(_run("[1 2] type /arraytype eq").stack[-1])

    def test_psname_eq_by_value(self):
        self.assertTrue(_run("/foo /foo eq").stack[-1])
        self.assertFalse(_run("/foo /bar eq").stack[-1])


class ConvertTests(unittest.TestCase):
    def test_cvs_integer(self):
        self.assertEqual(_run("123 (    ) cvs").stack[-1], "123")

    def test_cvs_name(self):
        self.assertEqual(_run("/Helv (    ) cvs").stack[-1], "Helv")

    def test_cvx_makes_name_executable(self):
        from eps2svg_pure import PSName
        n = _run("/add cvx").stack[-1]
        self.assertIsInstance(n, PSName)
        self.assertFalse(n.literal)

    def test_definefont_pops_key_leaves_font(self):
        i = _run("/MyFont << /FontType 1 >> definefont")
        self.assertEqual(len(i.stack), 1)
        self.assertIsInstance(i.stack[-1], dict)


if __name__ == "__main__":
    unittest.main()
