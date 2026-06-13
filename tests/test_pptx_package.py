import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

EXPECTED_PARTS = {
    "[Content_Types].xml",
    "_rels/.rels",
    "ppt/presentation.xml",
    "ppt/_rels/presentation.xml.rels",
    "ppt/slideMasters/slideMaster1.xml",
    "ppt/slideMasters/_rels/slideMaster1.xml.rels",
    "ppt/slideLayouts/slideLayout1.xml",
    "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
    "ppt/theme/theme1.xml",
    "ppt/slides/slide1.xml",
    "ppt/slides/_rels/slide1.xml.rels",
}


class WritePptxTests(unittest.TestCase):
    def _build(self, body, media=None):
        from eps2pptx.package import write_pptx
        with tempfile.TemporaryDirectory() as d:
            dst = Path(d) / "out.pptx"
            write_pptx(dst, body, media_jpeg=media)
            return dst.read_bytes()

    def test_zip_contains_expected_parts_all_well_formed(self):
        raw = self._build("<p:sp/>")
        zf = zipfile.ZipFile(io.BytesIO(raw))
        names = set(zf.namelist())
        self.assertTrue(EXPECTED_PARTS.issubset(names), names)
        for name in names:
            if name.endswith(".xml") or name.endswith(".rels"):
                ET.fromstring(zf.read(name))  # raises on malformed XML

    def test_slide_contains_body(self):
        raw = self._build('<p:sp id="marker"/>')
        zf = zipfile.ZipFile(io.BytesIO(raw))
        slide = zf.read("ppt/slides/slide1.xml").decode("utf-8")
        self.assertIn('<p:sp id="marker"/>', slide)

    def test_media_adds_image_part_and_rel(self):
        raw = self._build("<p:pic/>", media=b"\xff\xd8\xff\xe0JPEGDATA")
        zf = zipfile.ZipFile(io.BytesIO(raw))
        self.assertIn("ppt/media/image1.jpeg", zf.namelist())
        rels = zf.read("ppt/slides/_rels/slide1.xml.rels").decode("utf-8")
        self.assertIn("../media/image1.jpeg", rels)
        self.assertIn('Id="rId2"', rels)
