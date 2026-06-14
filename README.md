# eps2svg

Convert EPS / PostScript files to SVG, preserving vector quality and background transparency. Works **with zero external tools** via a built-in pure-Python PostScript interpreter.

## Features

- True vector conversion — no rasterization
- Transparent background preserved (no white fill injected into SVG)
- **Pure-Python backend included** — works on any system, no Ghostscript or Inkscape required
- Falls back to Inkscape / Ghostscript when present for maximum fidelity on complex files
- Supports both `.eps` and `.ps` files (single- and multi-page)
- Batch conversion: glob patterns, directories, recursive scan
- Hardened against pathological inputs (Adobe Distiller ASCII85, unmatched parens, base85 raster blocks)
- Hard execution budget (op count + wall-clock) — no more runaway processing on broken files

## Quick start

```bash
pip install .
eps2svg logo.eps                              # produces logo.svg
eps2svg --diagnose                            # show available backends
```

No external tools required for the pure-Python backend — it ships in the package.

## Desktop GUI (Windows)

A PySide6 desktop app wraps the same engine with a file list + live SVG preview.

```bash
pip install ".[gui]"     # installs PySide6
eps2svg-gui              # launch the app (no console window)
# or, without installing the entry point:
python -m eps2svg_gui
```

- Drag-and-drop (or **Add Files…/Add Folder…**) EPS/PS files; they are added to
  the list as *Queued*. Selecting a file previews it. Remove files with the
  **Remove** button or the **Delete** key.
- Each row shows the backend that will process it (e.g. *Pure Python*,
  *Ghostscript*); a leading `~` marks a pre-Convert guess, replaced by the
  actual backend once the file is converted or previewed.
- Pick the output **Format** (**SVG**, **PPTX**, or **EMF**), then click
  **Convert** to process every queued file in that format, with per-file status.
- Output goes next to each source by default; use **Change…** to pick an
  output folder for the session.
- The preview always shows the artwork rendered as SVG, even when the selected
  format is PPTX or EMF.
- Conversions run off the UI thread, so the window stays responsive; engine
  defaults (auto backend, dpi 96, 30 s timeout) match the CLI.

### Splitting icon sheets in the GUI

Select a file and click **Split…** to open the Split window:

- **Auto-split now** runs the automatic detector (the same engine as the CLI
  `--split`) and writes one SVG per detected icon.
- **Auto-detect grid** seeds an editable grid from that detection so you can
  verify it visually.
- Or define the grid by hand: set **Rows**/**Cols** and drag the blue frame to
  cover the icons; drag interior gridlines to fix uneven spacing. **Extract**
  writes the non-empty cells. **Ignore background** drops page-spanning shapes
  (borders/backgrounds) before slicing.
- Pick the **Format**: **SVG** writes one file per icon; **PPTX** writes a
  single deck with one slide per icon. Applies to both Extract and Auto-split.

Output goes to `<name>-icons/` next to the source (or the chosen output folder).

### Building a standalone `.exe`

```bash
pip install ".[gui]" "pyinstaller>=6.0"
pyinstaller eps2svg-gui.spec       # produces dist/eps2svg-gui.exe
```

## PowerPoint export (.pptx)

Convert an EPS/PS file to a native PowerPoint deck where every vector path is an
**editable DrawingML shape** (not a flattened picture). Pure-Python, no external
tools, no third-party libraries.

```bash
eps2svg logo.eps --format pptx          # -> logo.pptx (one 16:9 slide)
eps2svg sheet.ps --format pptx -d out/  # batch into out/
```

- Each path becomes an editable freeform shape (recolor / move / ungroup in
  PowerPoint), placed on a 16:9 slide, scaled to fit and centered.
- Vector-less files (embedded-JPEG stock art) embed the largest JPEG as a slide
  picture.
- Desktop GUI: set the **Format** selector to **PPTX** and click **Convert**.
- Limitations (v1): single page; no text, gradients, clipping, or grouping;
  even-odd fills approximate as nonzero. `--format pptx` requires the
  pure-Python backend.

## Enhanced Metafile export (.emf)

Convert to a Windows Enhanced Metafile — a vector format that pastes into Office
and other Windows apps as editable shapes.

```bash
eps2svg logo.eps --format emf           # -> logo.emf
eps2svg sheet.ps --format emf -d out/   # batch into out/
```

- Each painted path becomes an EMF path record (fill or stroke), placed at the
  source's physical size. Curves are flattened to polylines so the file renders
  in every EMF consumer.
- Desktop GUI: set the **Format** selector to **EMF** and click **Convert**.
- Limitations (v1): built from the pure-Python interpreter, so — like PPTX — no
  text, raster images, gradients, or clipping; Adobe AGM artwork is degraded.
  `--format emf` requires the pure-Python backend.

## Backends

| # | Backend | Notes |
|---|---|---|
| 1 | **Pure Python** (built-in) | Always available. Best for standard EPS/PS, vector EPS, AI shorthand. Limited on Adobe AGM color management. |
| 2 | **Inkscape** | Highest fidelity on complex Adobe Illustrator output. Needs Ghostscript on Windows for PS parsing. |
| 3 | **Ghostscript + PyMuPDF** | `winget install GhostScript.GhostScript` + `pip install pymupdf`. Fast, high fidelity. |
| 4 | **Ghostscript + pdf2svg** | POSIX-friendly. `apt install ghostscript pdf2svg`. |
| 5 | **Ghostscript + Inkscape** | Fallback two-step pipeline. |

Backends are tried in order. The first one that succeeds wins. Run `eps2svg --diagnose` to see what's installed.

### Installing optional backends

```bash
# Windows
winget install Inkscape.Inkscape
winget install GhostScript.GhostScript
pip install pymupdf

# Linux / macOS
sudo apt install inkscape ghostscript pdf2svg
pip install pymupdf
```

## Usage

```
eps2svg [-h] [--diagnose] [-o FILE] [-d DIR] [-r] [--page N]
        [--timeout SEC] [--max-ops N] [--dpi N] [--no-strip-bg]
        [--backend NAME] [-v]
        INPUT [INPUT ...]
```

### Inputs

Inputs can be files, directories, or glob patterns. **Globs work on Windows** — the CLI expands them itself instead of relying on shell expansion.

| Form | Behaviour |
|---|---|
| `eps2svg logo.eps` | One file, output next to it |
| `eps2svg *.eps -d out/` | Glob expansion (Windows-safe), write into `out/` |
| `eps2svg folder/` | Convert every `.eps`/`.ps`/`.epsf` in folder |
| `eps2svg folder/ -r` | Recurse into subfolders |
| `eps2svg '**/*.eps' -r -d out/` | Recursive glob |
| `eps2svg a.eps b.ps c.eps -d out/` | Explicit list, mixed extensions |

### Multi-page PostScript

PS files often contain multiple pages. By default `eps2svg` renders page 1. Use `--page N` to pick a specific page.

```bash
eps2svg report.ps                       # page 1 of N
eps2svg report.ps --page 3              # page 3
```

Pre-flight check catches out-of-range page numbers with a clear error.

## Icon splitting

Icon-sheet EPS/PS files (e.g. "Finance Icons set", "Programming icons") can be
split into one SVG per icon with `--split`:

```bash
eps2svg sheet.ps --split -d icons/
```

The algorithm is hybrid:

1. **Structural** — if the source wraps each icon in `gsave ... grestore`, those
   blocks are the icons.
2. **Geometric** (fallback) — single-link cluster paths by bbox proximity; cluster
   the cluster centres into rows and columns.

If neither phase yields between `--min-icons` and `--max-icons` shapes, the file
is treated as a single illustration and written unsplit into the output directory.

`--split` only works with the pure-Python backend; pairing it with
`--backend inkscape` or `--backend ghostscript` is an error.

### Options

| Flag | Default | Description |
|---|---|---|
| `-o FILE` | `<input>.svg` | Output path (single file) |
| `-d DIR` | — | Write all outputs into this directory |
| `-r` / `--recursive` | — | Recurse into subdirectories |
| `--page N` | `1` | For multi-page PS: render page N (1-based) |
| `--timeout SEC` | `30` | Wall-clock seconds before pure-Python aborts with a partial result (0 disables) |
| `--max-ops N` | `5,000,000` | Hard cap on PostScript operator dispatches in pure-Python mode |
| `--dpi N` | `96` | Resolution hint to the converter |
| `--no-strip-bg` | — | Skip white-background-rect removal post-processing |
| `--backend NAME` | auto | Force backend prefix: `pure`, `inkscape`, or `ghostscript` |
| `-v` / `--verbose` | — | Show backend commands and diagnostics |
| `--diagnose` | — | Show which backends are available and exit |
| `--split` | — | Split into one SVG per detected icon (pure-Python backend only). See "Icon splitting" below. |
| `--pad PT` | `2` | Padding around each icon's viewBox in `--split` mode |
| `--min-icons N` | `2` | Below this, `--split` falls back to a single unsplit SVG |
| `--max-icons N` | `500` | Above this, `--split` falls back |
| `--name-pattern PATTERN` | `{stem}-{index:03d}.svg` | Output naming for `--split`; placeholders `{stem}`, `{index}`, `{row}`, `{col}` |
| `--force` | — | Allow `--split` to write into a non-empty output dir |

### Examples

```bash
# Simple
eps2svg logo.eps

# Force pure-Python, see what was rendered
eps2svg logo.eps --backend pure -v

# Multi-page PS, pick page 3
eps2svg report.ps --page 3 -o page3.svg

# Batch a folder, force Ghostscript pipeline
eps2svg C:/icons/ -d converted/ --backend ghostscript

# Higher DPI hint for complex gradients
eps2svg diagram.eps --dpi 150

# Strict 5-second budget for sanity-checking unknown input
eps2svg suspect.ps --timeout 5
```

## What the pure-Python backend supports

| ✓ Works | ⚠ Limited |
|---|---|
| Path ops: `moveto`, `lineto`, `curveto`, `arc`, `closepath`, `r*` variants | Text/font rendering (parsed without crashing, not painted) |
| Painting: `fill`, `eofill`, `stroke`, `rectfill` / `rectstroke` | Patterns, gradients, shading |
| Colors: `setgray`, `setrgbcolor`, `setcmykcolor`, `sethsbcolor` | Custom color spaces (DeviceN, ICC profiles) |
| Transforms: `translate`, `scale`, `rotate`, `concat`, matrix ops | Embedded raster images via `image` operator (detects JPEGs and base64-embeds them as `<image>` elements) |
| Control flow: `if`, `ifelse`, `for`, `repeat`, `loop`, `exit`, `stopped` | Adobe Illustrator AGM color management (modern AI files render structure correctly but lose color fidelity) |
| Procedures: `def`, `bind`, `gsave`/`grestore`, full dict stack | |
| Adobe shorthand: `m`/`l`/`c`/`f`/`S`/`b`/`rg`/`RG`/`k`/`K`/`RGB`/… | |
| PS multi-page (`showpage` tracking, `setpagedevice`) | |
| ASCII85 string literals (`<~ ... ~>`) | |
| EPSF binary header (auto-stripped) | |

## Transparency notes

- When the EPS has no background, the pure-Python backend produces an SVG with no fill — naturally transparent.
- Inkscape backend passes `--export-background-opacity=0` to keep the canvas transparent.
- If the source explicitly draws a white background rectangle, `eps2svg` strips it in a post-processing pass. Use `--no-strip-bg` to keep it.

## Findings from hardening against real-world PS files

The pure-Python backend was iteratively hardened against pathological PS / EPS inputs, particularly Adobe Distiller output and Getty Images stock files. The bugs found and fixed:

| # | Bug | Cause | Fix |
|---|---|---|---|
| 1 | **Infinite loop on stray `)`** | A separator that no branch handled (e.g. unmatched closing paren) reached the word-scan branch, where `j == i` produced an empty token and `i` never advanced. | Detect `j == i` in word branch and `i += 1` |
| 2 | **O(n²) tokenize on ASCII85 / hex data** | Files using Adobe Distiller's `<~ ... ~>` ASCII85 encoding triggered hex-string parsing on every `<` char. Each call sliced + regex'd + `bytes.fromhex` against a huge body. | Added `<~ ... ~>` recognition with one `find()`. Pre-check hex bodies are actually hex before paying for `fromhex`. |
| 3 | **Char-by-char string scanner** | `while src[j] not in "()\\"` is Python-level, ~50× slower than C-side regex | Pre-compiled `re.compile(r"[()\\]")` for bulk-skip via `Pattern.search(string, pos, endpos)` |
| 4 | **Char-by-char word scanner** | Same problem for token boundaries | Pre-compiled `re.compile(r"[ \t\r\n\f\0()<>\[\]{}/%]")` |
| 5 | **Crash on `\8` / `\9` octal escape** | `int(oct_str, 8)` raised `ValueError` on non-octal digits — possible because the previous code used `str.isdigit()` instead of `0–7` | Restrict octal digits to `0`–`7` and catch `ValueError` defensively |
| 6 | **No global op/time budget** | Per-loop caps were per-loop. Nested `loop` / `for` / `repeat` could compound to 10¹⁰ ops without ever being "infinite" | Added `_Budget` (op count + wall-clock deadline) checked every 4–8K ops |
| 7 | **`op_stopped` swallowed `_ExitException`** | `exit` inside a `stopped` block didn't propagate to the enclosing loop, so a loop's exit condition could be silently lost | Re-raise `_ExitException` and `_BudgetExhausted`; only catch genuine runtime errors |
| 8 | **No recursion guard on `_exec_proc`** | Self-recursive procs hit Python's recursion limit with an ugly traceback | Hard cap `_MAX_PROC_DEPTH = 256`, raise `_BudgetExhausted` instead |
| 9 | **Tokenize had no budget check** | Pathological inputs could spin in `tokenize()` before ever reaching the interpreter, so the interpreter budget was useless | Thread the same `_Budget` through `tokenize()`; check every 16K chars |
| 10 | **No partial render on budget exhaustion** | When budget ran out, the SVG was empty | Catch `_BudgetExhausted` and emit whatever was rendered so far, with `PARTIAL (reason)` in the status |
| 11 | **No ASCII85 awareness** | `<~` was interpreted as the start of a hex string, leading to nonsensical decoding and the O(n²) issue above | Recognise the full `<~ ... ~>` envelope, emit an empty placeholder string (we don't decode ASCII85 payloads), advance past `~>` |

### Performance after fixes

Tested against 18 real Getty Images PostScript files (Adobe Illustrator and Distiller output):

| File size | Before fixes | After fixes |
|---|---|---|
| 1.7 MB (Adobe Distiller PS) | **hung indefinitely** (no budget check fired) | 0.66 s |
| 12 MB (Distiller PS with ASCII85) | **hung indefinitely** | 0.74 s |
| 5.7 MB (Adobe Illustrator EPS) | 0.8 s | 0.7 s |
| Simple test EPS | 0.05 s | 0.05 s |

All 18 production files (single shape EPS up to 12 MB Distiller PS with embedded raster) convert in under 1 second on the pure-Python backend.

### What the budget enforces

The hard ceiling is genuinely hard. If a file would burn the budget, the converter:

1. Stops processing where it is
2. Renders the SVG with whatever was collected so far
3. Tags the status with `PARTIAL (operation budget exhausted)` or `PARTIAL (time budget exhausted)`
4. Returns exit 0 (the SVG is usable — it's just incomplete)

If the partial output is unacceptable, raise the limits with `--timeout 120 --max-ops 50000000`, or install a system backend (`winget install GhostScript.GhostScript`) which the CLI will automatically prefer for files that exceed the pure-Python limits.

## Project layout

```
eps2svg/
├── eps2svg.py          # CLI, backend selection, glob/dir expansion
├── eps2svg_pure.py     # Pure-Python PS tokenizer + interpreter (~1500 lines)
├── pyproject.toml      # Registers `eps2svg` console script
└── README.md
```

The pure-Python module exposes:

- `convert_eps_to_svg(src, dst, dpi=96, page=None, max_ops=5_000_000, timeout=30.0)` — the entry point
- `count_pages(src)` — quick page counter using `%%Pages` or `showpage` heuristic
- `parse_bbox`, `parse_page_size`, `strip_eps_binary_header`, `extract_jpegs` — file inspection helpers
- `tokenize(src, budget=None)` — standalone PS tokenizer
- `Interpreter` — the stack machine itself
