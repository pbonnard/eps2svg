import struct
import tempfile
import unittest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

_EMR_HEADER = 1
_EMR_EOF = 14
_EMR_CREATEBRUSHINDIRECT = 39
_EMR_FILLPATH = 62


def _records(data):
    """Walk the EMF record stream -> list of (iType, nSize, offset)."""
    recs, off = [], 0
    while off + 8 <= len(data):
        itype, size = struct.unpack_from("<II", data, off)
        recs.append((itype, size, off))
        if size < 8 or off + size > len(data):
            break
        off += size
    return recs


class EmfStructureTests(unittest.TestCase):
    def _emf(self, name="grid_3x3.eps"):
        from eps2emf import convert_eps_to_emf
        d = Path(tempfile.mkdtemp())
        dst = d / "out.emf"
        status = convert_eps_to_emf(FIXTURES / name, dst)
        return dst.read_bytes(), status

    def test_header_signature_and_sizes(self):
        data, _ = self._emf()
        self.assertGreater(len(data), 88)
        itype, nsize = struct.unpack_from("<II", data, 0)
        self.assertEqual(itype, _EMR_HEADER)
        self.assertEqual(nsize, 88)
        self.assertEqual(struct.unpack_from("<I", data, 40)[0], 0x464D4520)  # " EMF"
        n_bytes = struct.unpack_from("<I", data, 48)[0]
        n_records = struct.unpack_from("<I", data, 52)[0]
        self.assertEqual(n_bytes, len(data))                  # header nBytes is exact
        recs = _records(data)
        self.assertEqual(n_records, len(recs))                # header nRecords is exact
        self.assertTrue(all(sz % 4 == 0 for _, sz, _ in recs))  # 4-byte aligned
        self.assertEqual(sum(sz for _, sz, _ in recs), len(data))

    def test_last_record_is_eof(self):
        data, _ = self._emf()
        self.assertEqual(_records(data)[-1][0], _EMR_EOF)

    def test_one_fill_per_circle(self):
        # grid_3x3 fixture = 9 filled circles -> 9 fill paths + 9 brushes.
        data, status = self._emf()
        recs = _records(data)
        fills = sum(1 for t, _, _ in recs if t == _EMR_FILLPATH)
        brushes = sum(1 for t, _, _ in recs if t == _EMR_CREATEBRUSHINDIRECT)
        self.assertEqual(fills, 9)
        self.assertEqual(brushes, 9)
        self.assertIn("9", status)


class EmfCliTests(unittest.TestCase):
    def test_format_emf_writes_emf(self):
        import eps2svg
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.emf"
            rc = eps2svg.main([str(FIXTURES / "grid_3x3.eps"),
                               "--format", "emf", "-o", str(out)])
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists() and out.stat().st_size > 88)
            self.assertEqual(struct.unpack_from("<I", out.read_bytes(), 40)[0],
                             0x464D4520)

    def test_default_output_uses_emf_extension(self):
        import eps2svg
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "logo.eps"
            src.write_bytes((FIXTURES / "grid_3x3.eps").read_bytes())
            rc = eps2svg.main([str(src), "--format", "emf"])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(d) / "logo.emf").exists())

    def test_format_emf_with_nonpure_backend_errors(self):
        import eps2svg
        with self.assertRaises(SystemExit):
            eps2svg.main([str(FIXTURES / "grid_3x3.eps"),
                          "--format", "emf", "--backend", "inkscape"])


if __name__ == "__main__":
    unittest.main()
