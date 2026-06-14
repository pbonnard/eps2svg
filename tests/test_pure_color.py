"""Colour-space-aware setcolor in the pure-Python interpreter."""

import unittest

from eps2svg_pure import Interpreter, tokenize


def _run(src):
    interp = Interpreter((0, 0, 100, 100))
    interp._exec_tokens(tokenize(src))
    return interp


def _rgb(interp):
    return tuple(round(x, 3) for x in interp.gstate.fill_color)


class ColorSpaceTests(unittest.TestCase):
    def test_devicecmyk_setcolor_is_converted(self):
        # c=0 m=1 y=1 k=0 -> red
        i = _run("[/DeviceCMYK] setcolorspace 0 1 1 0 setcolor")
        self.assertEqual(_rgb(i), (1.0, 0.0, 0.0))

    def test_devicecmyk_setcolor_pops_all_four_components(self):
        i = _run("[/DeviceCMYK] setcolorspace 0 0 0 1 setcolor")
        self.assertEqual(_rgb(i), (0.0, 0.0, 0.0))     # k=1 -> black
        self.assertEqual(len(i.stack), 0)              # no stray operand left

    def test_devicergb_setcolor(self):
        i = _run("[/DeviceRGB] setcolorspace 0.2 0.4 0.6 setcolor")
        self.assertEqual(_rgb(i), (0.2, 0.4, 0.6))

    def test_devicegray_setcolor(self):
        i = _run("[/DeviceGray] setcolorspace 0.5 setcolor")
        self.assertEqual(_rgb(i), (0.5, 0.5, 0.5))

    def test_name_form_colorspace(self):
        i = _run("/DeviceCMYK setcolorspace 1 0 0 0 setcolor")  # cyan
        self.assertEqual(_rgb(i), (0.0, 1.0, 1.0))

    def test_separation_tint_approximates_to_gray(self):
        i = _run("[/Separation /Spot /DeviceGray {pop 1}] setcolorspace 1 setcolor")
        self.assertEqual(_rgb(i), (0.0, 0.0, 0.0))     # full tint -> dark
        i2 = _run("[/Separation /Spot /DeviceGray {pop 1}] setcolorspace 0 setcolor")
        self.assertEqual(_rgb(i2), (1.0, 1.0, 1.0))    # no tint -> white

    def test_setrgbcolor_still_works(self):
        i = _run("0.1 0.2 0.3 setrgbcolor")
        self.assertEqual(_rgb(i), (0.1, 0.2, 0.3))

    def test_setcmykcolor_still_works(self):
        i = _run("0 1 1 0 setcmykcolor")
        self.assertEqual(_rgb(i), (1.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
