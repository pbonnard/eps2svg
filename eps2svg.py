#!/usr/bin/env python3
"""
eps2svg — Convert EPS files to SVG preserving vector quality and transparency.

Backends tried in order:
  1. Pure Python    (built-in — works on any system, no external tools)
  2. Inkscape       (best quality on complex files)
  3. Ghostscript + PyMuPDF
  4. Ghostscript + pdf2svg
  5. Ghostscript + Inkscape (two-step)

Run `eps2svg --diagnose` to see which backends are available on this machine.
"""

from __future__ import annotations

import argparse
import glob
import subprocess
import sys
import shutil
import tempfile
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Tool discovery (Windows-aware)
# ---------------------------------------------------------------------------

# Ghostscript on Windows ships as gswin64c / gswin32c, not gs.
_GS_CANDIDATES = ["gs", "gswin64c", "gswin32c"]

# Common non-PATH install locations on Windows
_INKSCAPE_WIN_PATHS = [
    r"C:\Program Files\Inkscape\bin\inkscape.exe",
    r"C:\Program Files (x86)\Inkscape\bin\inkscape.exe",
]
_GS_WIN_DIRS = [
    r"C:\Program Files\gs",
    r"C:\Program Files (x86)\gs",
]


def _find_inkscape() -> str | None:
    if exe := shutil.which("inkscape"):
        return exe
    for p in _INKSCAPE_WIN_PATHS:
        if Path(p).exists():
            return p
    return None


def _find_gs() -> str | None:
    for name in _GS_CANDIDATES:
        if exe := shutil.which(name):
            return exe
    # Probe common Windows install dirs (gs/gs<version>/bin/gswin64c.exe)
    for base in _GS_WIN_DIRS:
        base_path = Path(base)
        if base_path.exists():
            for sub in sorted(base_path.iterdir(), reverse=True):
                for candidate in ("gswin64c.exe", "gswin32c.exe", "gs.exe"):
                    exe = sub / "bin" / candidate
                    if exe.exists():
                        return str(exe)
    return None


def _run(cmd: list[str], verbose: bool = False) -> subprocess.CompletedProcess:
    if verbose:
        print(f"  $ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, capture_output=True, text=True)


def _gs_to_pdf(gs: str, src: Path, dst: Path, dpi: int, verbose: bool,
               page: int | None = None, is_eps: bool = True) -> bool:
    """Run Ghostscript: EPS or PS → PDF. -dEPSCrop only when source is EPS."""
    cmd = [
        gs,
        "-dBATCH", "-dNOPAUSE", "-dNOSAFER",
        "-dCompressPages=false",
        "-sDEVICE=pdfwrite",
        f"-r{dpi}",
    ]
    if is_eps:
        cmd.append("-dEPSCrop")
    if page:
        cmd.extend([f"-dFirstPage={page}", f"-dLastPage={page}"])
    cmd.extend([f"-sOutputFile={dst}", str(src)])
    r = _run(cmd, verbose)
    if r.returncode != 0 and verbose:
        print(f"  gs stderr: {r.stderr.strip()}", file=sys.stderr)
    return r.returncode == 0 and dst.exists() and dst.stat().st_size > 0


def _is_eps_file(src: Path) -> bool:
    """Quick check: does the file declare itself as EPSF?"""
    try:
        with open(src, "rb") as f:
            head = f.read(200)
        return b"EPSF" in head
    except Exception:
        return src.suffix.lower() in (".eps", ".epsf")


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def _pure_python(src: Path, dst: Path, dpi: int, verbose: bool,
                 page: int | None = None,
                 max_ops: int = 5_000_000,
                 timeout: float = 30.0) -> bool:
    """Pure Python — built-in PostScript subset interpreter."""
    try:
        from eps2svg_pure import convert_eps_to_svg
    except ImportError:
        try:
            from .eps2svg_pure import convert_eps_to_svg  # type: ignore
        except Exception:
            return False
    try:
        status = convert_eps_to_svg(
            src, dst,
            dpi=dpi, verbose=verbose, page=page,
            max_ops=max_ops, timeout=timeout,
        )
        if verbose:
            print(f"  {status}", file=sys.stderr)
        return dst.exists() and dst.stat().st_size > 0
    except Exception as e:
        if verbose:
            print(f"  pure-python error: {e}", file=sys.stderr)
        return False


def _inkscape(src: Path, dst: Path, dpi: int, verbose: bool,
              page: int | None = None, **_ignored) -> bool:
    """Direct EPS/PS → SVG via Inkscape."""
    exe = _find_inkscape()
    if not exe:
        return False
    cmd = [
        exe, str(src),
        f"--export-dpi={dpi}",
        "--export-background-opacity=0",
        "--export-type=svg",
        f"--export-filename={dst}",
    ]
    if page:
        cmd.append(f"--export-page={page}")
    r = _run(cmd, verbose)
    if r.returncode != 0 and verbose:
        print(f"  inkscape stderr: {r.stderr.strip()}", file=sys.stderr)
    return r.returncode == 0 and dst.exists()


def _gs_pymupdf(src: Path, dst: Path, dpi: int, verbose: bool,
                page: int | None = None, **_ignored) -> bool:
    """EPS/PS → PDF (Ghostscript) then PDF → SVG (PyMuPDF). pip install pymupdf."""
    gs = _find_gs()
    if not gs:
        return False
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return False
    is_eps = _is_eps_file(src)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        tmp = Path(f.name)
    try:
        if not _gs_to_pdf(gs, src, tmp, dpi, verbose, page=page, is_eps=is_eps):
            return False
        doc = fitz.open(str(tmp))
        pg_idx = (page - 1) if page else 0
        if pg_idx >= len(doc):
            pg_idx = 0
        scale = dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        svg_text = doc[pg_idx].get_svg_image(matrix=matrix)
        dst.write_text(svg_text, encoding="utf-8")
        return dst.exists() and dst.stat().st_size > 0
    except Exception as e:
        if verbose:
            print(f"  PyMuPDF error: {e}", file=sys.stderr)
        return False
    finally:
        tmp.unlink(missing_ok=True)


def _gs_pdf2svg(src: Path, dst: Path, dpi: int, verbose: bool,
                page: int | None = None, **_ignored) -> bool:
    """EPS/PS → PDF (Ghostscript) then PDF → SVG (pdf2svg)."""
    gs = _find_gs()
    if not gs or not shutil.which("pdf2svg"):
        return False
    is_eps = _is_eps_file(src)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        tmp = Path(f.name)
    try:
        if not _gs_to_pdf(gs, src, tmp, dpi, verbose, page=page, is_eps=is_eps):
            return False
        # pdf2svg takes optional page number as 3rd arg (1-based)
        cmd = ["pdf2svg", str(tmp), str(dst)]
        if page:
            cmd.append(str(page))
        r = _run(cmd, verbose)
        if r.returncode != 0 and verbose:
            print(f"  pdf2svg stderr: {r.stderr.strip()}", file=sys.stderr)
        return r.returncode == 0 and dst.exists()
    finally:
        tmp.unlink(missing_ok=True)


def _gs_inkscape(src: Path, dst: Path, dpi: int, verbose: bool,
                 page: int | None = None, **_ignored) -> bool:
    """EPS/PS → PDF (Ghostscript) then PDF → SVG (Inkscape)."""
    gs = _find_gs()
    exe = _find_inkscape()
    if not gs or not exe:
        return False
    is_eps = _is_eps_file(src)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        tmp = Path(f.name)
    try:
        if not _gs_to_pdf(gs, src, tmp, dpi, verbose, page=page, is_eps=is_eps):
            return False
        cmd = [
            exe, str(tmp),
            "--export-background-opacity=0",
            "--export-type=svg",
            f"--export-filename={dst}",
        ]
        if page:
            cmd.append(f"--export-page={page}")
        r = _run(cmd, verbose)
        if r.returncode != 0 and verbose:
            print(f"  inkscape stderr: {r.stderr.strip()}", file=sys.stderr)
        return r.returncode == 0 and dst.exists()
    finally:
        tmp.unlink(missing_ok=True)


BACKENDS: list[tuple[str, object]] = [
    ("Pure Python",            _pure_python),
    ("Inkscape",               _inkscape),
    ("Ghostscript + PyMuPDF",  _gs_pymupdf),
    ("Ghostscript + pdf2svg",  _gs_pdf2svg),
    ("Ghostscript + Inkscape", _gs_inkscape),
]

# ---------------------------------------------------------------------------
# Diagnose
# ---------------------------------------------------------------------------

def diagnose() -> None:
    """Print a table of available backends and what's missing."""
    inkscape = _find_inkscape()
    gs       = _find_gs()
    pdf2svg  = shutil.which("pdf2svg")
    try:
        import fitz as _fitz
        pymupdf_ver = _fitz.version[0]
    except ImportError:
        pymupdf_ver = None

    def tick(v): return "OK" if v else "--"

    # Pure Python backend is always available (it's part of this package)
    pure_ok = True
    try:
        import eps2svg_pure  # noqa: F401
    except ImportError:
        pure_ok = False

    print("eps2svg backend availability")
    print("-" * 44)
    print(f"  {tick(pure_ok)}  Pure Python    (built-in subset interpreter)")
    print(f"  {tick(inkscape)}  Inkscape       {inkscape or '(not found)'}")
    print(f"  {tick(gs)}  Ghostscript    {gs or '(not found)'}")
    print(f"  {tick(pymupdf_ver)}  PyMuPDF        {'v' + pymupdf_ver if pymupdf_ver else '(pip install pymupdf)'}")
    print(f"  {tick(pdf2svg)}  pdf2svg        {pdf2svg or '(not found)'}")
    print()

    ready = []
    if pure_ok:
        ready.append("Pure Python")
    if inkscape:
        ready.append("Inkscape")
    if gs and pymupdf_ver:
        ready.append("Ghostscript + PyMuPDF")
    if gs and pdf2svg:
        ready.append("Ghostscript + pdf2svg")
    if gs and inkscape:
        ready.append("Ghostscript + Inkscape")

    print(f"Ready backends: {', '.join(ready) if ready else '(none)'}")
    if not (inkscape or gs):
        print()
        print("Note: pure-Python backend covers most vector EPS and detects")
        print("embedded JPEGs in raster EPS (Getty/iStock). For maximum")
        print("fidelity on complex files, install Inkscape or Ghostscript.")

# ---------------------------------------------------------------------------
# Post-processing: strip explicit white background rect
# ---------------------------------------------------------------------------

def _strip_white_bg(svg_path: Path, verbose: bool) -> None:
    import re
    text = svg_path.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(
        r'<rect\b[^>]*\b(?:fill=["\'](?:white|#fff(?:fff)?|rgb\(255,\s*255,\s*255\))["\'])[^>]*/?>',
        re.IGNORECASE,
    )
    new_text, n = pattern.subn("", text, count=1)
    if n and verbose:
        print("  Stripped white background rectangle.", file=sys.stderr)
    if n:
        svg_path.write_text(new_text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Conversion entry point
# ---------------------------------------------------------------------------

def convert(
    src: Path,
    dst: Path,
    *,
    dpi: int = 96,
    strip_bg: bool = True,
    verbose: bool = False,
    backend: str | None = None,
    page: int | None = None,
    max_ops: int = 5_000_000,
    timeout: float = 30.0,
) -> str:
    chosen = [(n, fn) for n, fn in BACKENDS
              if backend is None or n.lower().startswith(backend.lower())]
    if not chosen:
        raise ValueError(f"Unknown backend '{backend}'. Options: {[n for n, _ in BACKENDS]}")

    for name, fn in chosen:
        if verbose:
            print(f"  Trying backend: {name}", file=sys.stderr)
        if fn(src, dst, dpi, verbose,
              page=page, max_ops=max_ops, timeout=timeout):
            if strip_bg:
                _strip_white_bg(dst, verbose)
            return name

    raise RuntimeError(
        "Conversion failed — no working backend found.\n"
        "Run `eps2svg --diagnose` to see what's missing and how to fix it."
    )

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="eps2svg",
        description="Convert EPS / PS to SVG preserving vector quality and background transparency.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Accepted inputs: .eps  .ps  .epsf  (also any file the backends accept).

            Backends (tried in order unless --backend is set):
              1. Pure Python              — built-in, no external tools needed
              2. Inkscape                 — best quality on complex files
              3. Ghostscript + PyMuPDF
              4. Ghostscript + pdf2svg
              5. Ghostscript + Inkscape

            Inputs can be files, directories, or glob patterns.
            Globs (*, ?, [...]) are expanded internally — works on Windows.

            Multi-page PS:
              - Default: renders page 1.
              - Use --page N to select a specific page.

            Examples:
              eps2svg logo.eps
              eps2svg paper.ps -o paper.svg --dpi 150
              eps2svg report.ps --page 3 -o page3.svg
              eps2svg *.eps -d converted/
              eps2svg C:/icons/ -r -d converted/      # recursive folder
              eps2svg --diagnose
        """),
    )
    p.add_argument("inputs", nargs="*", metavar="INPUT",
                   help="EPS/PS file(s), directory, or glob pattern")
    p.add_argument("--diagnose", action="store_true",
                   help="Show which backends are available and exit")
    p.add_argument("-o", "--output", metavar="FILE",
                   help="Output SVG path (single file only)")
    p.add_argument("-d", "--output-dir", metavar="DIR",
                   help="Write all SVGs into this directory")
    p.add_argument("-r", "--recursive", action="store_true",
                   help="Recurse into subdirectories when input is a directory or **/*.eps glob")
    p.add_argument("--page", type=int, metavar="N",
                   help="For multi-page PS files: render page N (1-based). Default: 1.")
    p.add_argument("--split", action="store_true",
                   help="Split into one SVG per detected icon. Requires pure-Python backend.")
    p.add_argument("--pad", type=float, default=2.0, metavar="PT",
                   help="Padding (points) around each icon's viewBox in --split mode (default: 2)")
    p.add_argument("--min-icons", dest="min_icons", type=int, default=2, metavar="N",
                   help="Refuse to split if fewer icons detected (default: 2)")
    p.add_argument("--max-icons", dest="max_icons", type=int, default=500, metavar="N",
                   help="Refuse to split if more icons detected (default: 500)")
    p.add_argument("--name-pattern", dest="name_pattern",
                   default="{stem}-{index:03d}.svg", metavar="PATTERN",
                   help="Output naming. Placeholders: {stem}, {index}, {row}, {col}")
    p.add_argument("--force", action="store_true",
                   help="Allow --split to write into a non-empty output directory")
    p.add_argument("--grid", action="store_true",
                   help="Lattice-aware --split: drop page-spanning paths and snap clusters "
                        "to a regular grid (use when icons are uniformly sized and aligned)")
    p.add_argument("--timeout", type=float, default=30.0, metavar="SEC",
                   help="Wall-clock seconds before pure-Python conversion aborts "
                        "with a partial result (default: 30; 0 disables)")
    p.add_argument("--max-ops", dest="max_ops", type=int, default=5_000_000, metavar="N",
                   help="Hard cap on PostScript operator dispatches in pure-Python "
                        "mode (default: 5,000,000)")
    p.add_argument("--dpi", type=int, default=96, metavar="N",
                   help="Resolution hint passed to the converter (default: 96)")
    p.add_argument("--no-strip-bg", dest="strip_bg", action="store_false",
                   help="Skip post-processing that removes white background rects")
    p.add_argument("--backend", metavar="NAME",
                   help="Force a specific backend prefix (pure / inkscape / ghostscript)")
    p.add_argument("--format", choices=["svg", "pptx"], default="svg",
                   help="Output format: svg (default) or pptx (native "
                        "PowerPoint with editable shapes; pure-Python only)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Show converter commands and details")
    return p


_EPS_EXTS = (".eps", ".ps", ".epsf")


def _expand_inputs(patterns: list[str], recursive: bool, verbose: bool) -> list[Path]:
    """Expand each argument into concrete file paths.

    - Literal existing files are kept as-is.
    - Directories are scanned for .eps/.ps/.epsf (recursively if --recursive).
    - Glob patterns (*, ?, [...]) are expanded via glob.glob.
    - Unmatched non-glob, non-existing entries are returned as-is so the
      caller can report a clear 'file not found' error.
    """
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path):
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            return
        seen.add(key)
        out.append(p)

    for raw in patterns:
        p = Path(raw)

        # Existing directory -> scan
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            for child in sorted(p.glob(pattern)):
                if child.is_file() and child.suffix.lower() in _EPS_EXTS:
                    add(child)
            continue

        # Existing file -> keep
        if p.exists():
            add(p)
            continue

        # Glob pattern -> expand
        if any(ch in raw for ch in "*?[") :
            matches = sorted(glob.glob(raw, recursive=recursive))
            if matches:
                for m in matches:
                    mp = Path(m)
                    if mp.is_dir():
                        sub_pat = "**/*" if recursive else "*"
                        for child in sorted(mp.glob(sub_pat)):
                            if child.is_file() and child.suffix.lower() in _EPS_EXTS:
                                add(child)
                    else:
                        add(mp)
            else:
                if verbose:
                    print(f"warning: no files matched pattern '{raw}'", file=sys.stderr)
                # keep the literal so caller reports it cleanly
                add(p)
            continue

        # Nothing matched - keep literal for 'file not found' error
        add(p)

    return out


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.diagnose:
        diagnose()
        return 0

    if not args.inputs:
        parser.print_help()
        return 1

    inputs = _expand_inputs(args.inputs, recursive=args.recursive, verbose=args.verbose)
    out_dir = Path(args.output_dir) if args.output_dir else None

    if not inputs:
        print("error: no input files found", file=sys.stderr)
        return 1
    if args.output and len(inputs) > 1:
        parser.error(f"--output can only be used with a single input file "
                     f"(got {len(inputs)} after expansion).")
    if args.output and args.output_dir:
        parser.error("--output and --output-dir are mutually exclusive.")
    if args.format == "pptx":
        if args.split:
            parser.error("--format pptx conflicts with --split.")
        if args.backend and not args.backend.lower().startswith("pure"):
            parser.error("--format pptx requires the pure-Python backend.")
    if args.split:
        if args.output:
            parser.error("--split conflicts with -o/--output; use -d DIR.")
        if args.backend and not args.backend.lower().startswith("pure"):
            parser.error("--split requires --backend pure (the default).")
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    if args.verbose and len(inputs) > 1:
        print(f"Converting {len(inputs)} file(s)...", file=sys.stderr)

    errors = 0
    for src in inputs:
        if not src.exists():
            print(f"error: {src}: file not found", file=sys.stderr)
            errors += 1
            continue
        if src.suffix.lower() not in _EPS_EXTS:
            print(f"warning: {src}: unexpected extension (continuing anyway)", file=sys.stderr)

        ext = ".pptx" if args.format == "pptx" else ".svg"
        if args.output:
            dst = Path(args.output)
        elif out_dir:
            dst = out_dir / src.with_suffix(ext).name
        else:
            dst = src.with_suffix(ext)

        # Pre-validate --page against actual page count
        if args.page is not None:
            try:
                from eps2svg_pure import count_pages
                n_pages = count_pages(src)
                if args.page < 1 or args.page > n_pages:
                    print(f"error: {src}: --page {args.page} out of range "
                          f"(file has {n_pages} page(s))", file=sys.stderr)
                    errors += 1
                    continue
            except Exception:
                pass  # best-effort; fall through to backend

        try:
            if args.format == "pptx":
                from eps2pptx import convert_eps_to_pptx
                status = convert_eps_to_pptx(
                    src, dst, page=args.page,
                    max_ops=args.max_ops, timeout=args.timeout,
                    verbose=args.verbose,
                )
                size_kb = dst.stat().st_size / 1024
                print(f"{src}  ->  {dst}  [{status}, {size_kb:.1f} KB]")
            elif args.split:
                from eps2svg_split import run_split
                target_dir = (Path(args.output_dir) if args.output_dir
                              else src.with_suffix("").parent / f"{src.stem}-icons")
                result = run_split(
                    src, target_dir,
                    pad=args.pad,
                    min_icons=args.min_icons,
                    max_icons=args.max_icons,
                    name_pattern=args.name_pattern,
                    force=args.force,
                    verbose=args.verbose,
                    page=args.page,
                    max_ops=args.max_ops,
                    timeout=args.timeout,
                    grid=args.grid,
                )
                print(f"{src}  ->  {target_dir}/  "
                      f"[{result.mode}, {result.icon_count} icon(s)]")
            else:
                used = convert(
                    src, dst,
                    dpi=args.dpi,
                    strip_bg=args.strip_bg,
                    verbose=args.verbose,
                    backend=args.backend,
                    page=args.page,
                    max_ops=args.max_ops,
                    timeout=args.timeout,
                )
                size_kb = dst.stat().st_size / 1024
                print(f"{src}  ->  {dst}  [{used}, {size_kb:.1f} KB]")
        except Exception as e:
            print(f"error: {src}: {e}", file=sys.stderr)
            errors += 1

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
