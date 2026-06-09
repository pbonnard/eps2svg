"""
Pure-Python EPS to SVG converter.

Implements a minimal PostScript interpreter sufficient for typical vector EPS
files: paths, strokes, fills, colors, transforms, basic procedures, common
arithmetic. Handles photo-style EPS (Getty/iStock) by detecting and embedding
the underlying JPEG raster data directly as base64 in the SVG.

NOT a full PostScript engine — complex font rendering, advanced filters, and
unusual control flow may be ignored or approximated. For maximum fidelity on
arbitrary EPS, install Inkscape or Ghostscript.
"""

from __future__ import annotations

import base64
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class PathMeta:
    """Per-path metadata captured at emit time for the split feature.

    The list `Interpreter.path_metadata` is a flat list across all pages of
    the document. Not every entry in `Interpreter.pages[i]` has a
    corresponding `PathMeta` — only painted paths (op_fill / op_eofill /
    op_stroke) are recorded; explicit SVG fragments such as embedded image
    elements are not. Consumers that need a per-page view should bucket
    these records themselves; the split feature only operates on documents
    with a single page.

    Fields:
      svg_index — index into the current page's svg-fragment list at the
                  time this PathMeta was appended. Only meaningful for
                  single-page documents.
      bbox      — (x0, y0, x1, y1) in PostScript device coordinates,
                  after the CTM has been applied to all path points
                  (including cubic Bezier control points).
      group_id  — the structural group this path belongs to (see
                  Interpreter.op_gsave / op_grestore). None for paths
                  emitted while gsave-depth is 0.
    """
    svg_index: int
    bbox: tuple[float, float, float, float]
    group_id: int | None


# ---------------------------------------------------------------------------
# Execution budget — global safety net against runaway processing
# ---------------------------------------------------------------------------

class _BudgetExhausted(Exception):
    """Raised when the interpreter exceeds its op or time budget.

    The interpreter unwinds cleanly so the caller can still emit a partial
    SVG with whatever was rendered before the budget ran out.
    """
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _Budget:
    """Hard ceiling on operator dispatches and wall-clock time."""

    __slots__ = ("ops_remaining", "deadline", "_tick", "_check_every",
                 "exhausted_reason")

    def __init__(self, max_ops: int = 5_000_000, max_seconds: float = 30.0):
        self.ops_remaining = max_ops
        self.deadline = time.monotonic() + max_seconds if max_seconds else None
        self._check_every = 8192   # check wall-clock every N ops (cheap)
        self._tick = 0
        self.exhausted_reason = ""

    def consume(self) -> None:
        self.ops_remaining -= 1
        if self.ops_remaining <= 0:
            self.exhausted_reason = "operation budget exhausted"
            raise _BudgetExhausted(self.exhausted_reason)
        self._tick += 1
        if self._tick >= self._check_every:
            self._tick = 0
            if self.deadline is not None and time.monotonic() > self.deadline:
                self.exhausted_reason = "time budget exhausted"
                raise _BudgetExhausted(self.exhausted_reason)


# ---------------------------------------------------------------------------
# Graphics state
# ---------------------------------------------------------------------------

class GState:
    """PostScript graphics state."""

    __slots__ = (
        "ctm", "fill_color", "stroke_color",
        "line_width", "line_cap", "line_join", "miter_limit",
        "dash_array", "dash_offset",
    )

    def __init__(self):
        self.ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]   # a b c d e f
        self.fill_color = (0.0, 0.0, 0.0)
        self.stroke_color = (0.0, 0.0, 0.0)
        self.line_width = 1.0
        self.line_cap = 0      # 0 butt, 1 round, 2 square
        self.line_join = 0     # 0 miter, 1 round, 2 bevel
        self.miter_limit = 10.0
        self.dash_array: list[float] = []
        self.dash_offset = 0.0

    def copy(self) -> "GState":
        g = GState()
        g.ctm = list(self.ctm)
        g.fill_color = self.fill_color
        g.stroke_color = self.stroke_color
        g.line_width = self.line_width
        g.line_cap = self.line_cap
        g.line_join = self.line_join
        g.miter_limit = self.miter_limit
        g.dash_array = list(self.dash_array)
        g.dash_offset = self.dash_offset
        return g


# ---------------------------------------------------------------------------
# PostScript token / object classes
# ---------------------------------------------------------------------------

class PSName:
    __slots__ = ("name", "literal")

    def __init__(self, name: str, literal: bool = False):
        self.name = name
        self.literal = literal

    def __repr__(self):
        return f"/{self.name}" if self.literal else self.name


class PSProc:
    __slots__ = ("body",)

    def __init__(self, body: list[Any]):
        self.body = body

    def __repr__(self):
        return f"{{ {len(self.body)} ops }}"


class PSMark:
    pass


MARK = PSMark()


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")
_RADIX_RE = re.compile(r"^(\d+)#([0-9a-zA-Z]+)$")

# Pre-compiled scanners for bulk-skip inside string literals.
# str.find can only match a single substring, so we use regex for "any of".
_STRING_INTERESTING_RE = re.compile(r"[()\\]")
_WORD_END_RE = re.compile(r"[ \t\r\n\f\0()<>\[\]{}/%]")


def _parse_number(tok: str):
    if _NUM_RE.match(tok):
        try:
            i = int(tok)
            return i
        except ValueError:
            return float(tok)
    m = _RADIX_RE.match(tok)
    if m:
        base = int(m.group(1))
        if 2 <= base <= 36:
            try:
                return int(m.group(2), base)
            except ValueError:
                pass
    return None


def tokenize(src: str, budget: _Budget | None = None) -> list[Any]:
    """Tokenize PostScript source into a flat list of Python objects.
    Procedures { ... } and arrays [ ... ] are preserved as nested structures.

    If `budget` is provided, the tokenizer checks it periodically and raises
    _BudgetExhausted when out of time, allowing the caller to recover with
    whatever tokens were collected so far.
    """
    tokens: list[Any] = []
    i, n = 0, len(src)
    proc_stack: list[list[Any]] = []
    # Budget check throttle — every N characters consumed
    next_budget_check = i + 16384

    def emit(obj):
        if proc_stack:
            proc_stack[-1].append(obj)
        else:
            tokens.append(obj)

    while i < n:
        if budget is not None and i >= next_budget_check:
            budget.consume()         # raises _BudgetExhausted if expired
            next_budget_check = i + 16384
        c = src[i]

        # Whitespace
        if c in " \t\r\n\f\0":
            i += 1
            continue

        # Comment — skip to end of line. Capture %%BoundingBox etc. via caller.
        if c == "%":
            j = src.find("\n", i)
            if j < 0:
                break
            i = j + 1
            continue

        # String (...)
        # Performance: scan in chunks with str.find for the next interesting
        # char (one of `()\\`). Char-by-char in Python is ~50x slower.
        if c == "(":
            depth = 1
            i += 1
            buf: list[str] = []
            # Safety cap: PostScript strings >4MB are almost certainly the
            # result of an unmatched `(` in raw binary data.
            string_cap = min(n, i + 4_000_000)
            while i < string_cap and depth > 0:
                # Jump to next interesting char using a regex (bulk C scan).
                m = _STRING_INTERESTING_RE.search(src, i, string_cap)
                if m is None:
                    buf.append(src[i:string_cap])
                    i = string_cap
                    break
                j = m.start()
                if j > i:
                    buf.append(src[i:j])
                i = j
                ch = src[i]
                if ch == "\\":
                    if i + 1 >= n:
                        i += 1; break
                    nxt = src[i + 1]
                    if nxt == "n":   buf.append("\n"); i += 2; continue
                    if nxt == "r":   buf.append("\r"); i += 2; continue
                    if nxt == "t":   buf.append("\t"); i += 2; continue
                    if nxt == "b":   buf.append("\b"); i += 2; continue
                    if nxt == "f":   buf.append("\f"); i += 2; continue
                    if nxt == "\\":  buf.append("\\"); i += 2; continue
                    if nxt == "(":   buf.append("(");  i += 2; continue
                    if nxt == ")":   buf.append(")");  i += 2; continue
                    if "0" <= nxt <= "7":   # octal escape: 1–3 digits, 0–7
                        k = i + 1
                        oct_str = ""
                        while k < n and len(oct_str) < 3 and "0" <= src[k] <= "7":
                            oct_str += src[k]; k += 1
                        try:
                            buf.append(chr(int(oct_str, 8)))
                        except ValueError:
                            pass
                        i = k; continue
                    # Unknown escape: skip backslash, keep next char literal
                    i += 2; continue
                if ch == "(":
                    depth += 1; buf.append("("); i += 1; continue
                # ch == ")"
                depth -= 1
                if depth == 0:
                    break
                buf.append(")"); i += 1
            i += 1  # consume final )
            emit("".join(buf))
            continue

        # `<<`  dict-mark
        # `<~...~>`  ASCII85 string (Adobe Distiller / image data)
        # `<hex>`    hex string
        if c == "<":
            nxt = src[i + 1] if i + 1 < n else ""
            if nxt == "<":
                emit(PSName("<<")); i += 2; continue
            if nxt == "~":
                # ASCII85 — scan for ~> terminator (single bulk find)
                j = src.find("~>", i + 2)
                if j < 0:
                    # Unterminated ASCII85 — drop the rest as garbage
                    break
                emit("")           # we don't decode ASCII85; emit empty placeholder
                i = j + 2
                continue
            # Hex string. Cap the scan to avoid pathological O(n²) when `<`
            # appears in non-hex data without a matching `>`.
            scan_limit = min(n, i + 1 + 1_000_000)
            j = src.find(">", i + 1, scan_limit)
            if j < 0:
                # No `>` within the cap — treat as a stray `<` and move past it
                i += 1
                continue
            # Validate that the content is actually hex before paying for fromhex.
            body = src[i + 1:j]
            # Cheap pre-check: all chars must be hex digits or whitespace
            ok = True
            for hc in body:
                if hc not in "0123456789abcdefABCDEF \t\r\n\f":
                    ok = False; break
            if ok:
                hex_str = re.sub(r"\s+", "", body)
                if len(hex_str) % 2:
                    hex_str += "0"
                try:
                    emit(bytes.fromhex(hex_str).decode("latin-1"))
                except ValueError:
                    emit("")
            else:
                # Not a hex string — skip the `<` and continue tokenizing.
                # This handles stray `<` chars (e.g. in raw ASCII85 payloads).
                i += 1
                continue
            i = j + 1
            continue

        if c == ">":
            if i + 1 < n and src[i + 1] == ">":
                emit(PSName(">>")); i += 2; continue
            i += 1; continue

        # Procedure
        if c == "{":
            proc_stack.append([])
            i += 1
            continue
        if c == "}":
            if proc_stack:
                body = proc_stack.pop()
                emit(PSProc(body))
            i += 1
            continue

        # Array
        if c == "[":
            emit(PSName("["))
            i += 1
            continue
        if c == "]":
            emit(PSName("]"))
            i += 1
            continue

        # Literal /name or //name
        if c == "/":
            i += 1
            if i < n and src[i] == "/":
                i += 1
            j = i
            while j < n and src[j] not in " \t\r\n\f\0()<>[]{}/%":
                j += 1
            emit(PSName(src[i:j], literal=True))
            i = j
            continue

        # Number or name — bulk-scan to next separator
        m = _WORD_END_RE.search(src, i)
        j = m.start() if m else n
        if j == i:
            # Stray separator that no earlier branch handled (e.g. a `)`
            # outside any string). Skip it so we always make progress.
            i += 1
            continue
        tok = src[i:j]
        i = j
        num = _parse_number(tok)
        if num is not None:
            emit(num)
        else:
            emit(PSName(tok))

    return tokens


# ---------------------------------------------------------------------------
# Interpreter
# ---------------------------------------------------------------------------

class PSError(Exception):
    pass


class Interpreter:
    # Hard cap on Python recursion depth via _exec_proc — independent of
    # Python's recursion limit (which produces unfriendly RecursionError).
    _MAX_PROC_DEPTH = 256

    def __init__(self, bbox: tuple[float, float, float, float],
                 budget: _Budget | None = None):
        self.stack: list[Any] = []
        self.dict_stack: list[dict[str, Any]] = [{}]
        self.gstate = GState()
        self.gstate_stack: list[GState] = []
        self.bbox = bbox
        self.budget = budget or _Budget()
        self._proc_depth = 0

        # Current path: list of subpaths. Each subpath is a list of segments.
        # Segment: ("M", x, y), ("L", x, y), ("C", x1,y1,x2,y2,x3,y3), ("Z",)
        self.path: list[list[tuple]] = []
        self.current_point: tuple[float, float] | None = None

        # Output SVG drawing elements, grouped per page.
        # pages[i] is the list of SVG fragments emitted for page (i+1).
        self.pages: list[list[str]] = [[]]

        # Per-path metadata captured at emit time for the split feature.
        # Parallels self.pages[-1] entries that are painting ops (fill/stroke).
        self.path_metadata: list[PathMeta] = []
        self._next_group_id: int = 0
        self.current_group_id: int | None = None

        # PageSize seen via setpagedevice (if any) — updates bbox if no
        # %%BoundingBox was provided.
        self.detected_page_size: tuple[float, float] | None = None

        # Counters for unrecognized operators (for diagnostics)
        self.unknown_ops: dict[str, int] = {}

        self._install_operators()

    # -- operator installation ------------------------------------------------

    def _install_operators(self):
        d = self.dict_stack[0]
        ops: dict[str, Callable[[], None]] = {
            # Stack
            "dup":   self.op_dup,
            "pop":   self.op_pop,
            "exch":  self.op_exch,
            "copy":  self.op_copy,
            "index": self.op_index,
            "roll":  self.op_roll,
            "clear": lambda: self.stack.clear(),
            "count": lambda: self.stack.append(len(self.stack)),
            "mark":  lambda: self.stack.append(MARK),
            "cleartomark": self.op_cleartomark,
            "counttomark": self.op_counttomark,

            # Math
            "add": lambda: self._binop(lambda a, b: a + b),
            "sub": lambda: self._binop(lambda a, b: a - b),
            "mul": lambda: self._binop(lambda a, b: a * b),
            "div": lambda: self._binop(lambda a, b: a / b if b else 0.0),
            "idiv": lambda: self._binop(lambda a, b: int(a) // int(b) if b else 0),
            "mod":  lambda: self._binop(lambda a, b: a % b if b else 0),
            "neg":  lambda: self.stack.append(-self._pop_num()),
            "abs":  lambda: self.stack.append(abs(self._pop_num())),
            "sqrt": lambda: self.stack.append(math.sqrt(self._pop_num())),
            "sin":  lambda: self.stack.append(math.sin(math.radians(self._pop_num()))),
            "cos":  lambda: self.stack.append(math.cos(math.radians(self._pop_num()))),
            "atan": self.op_atan,
            "exp":  lambda: self._binop(lambda a, b: a ** b),
            "ln":   lambda: self.stack.append(math.log(self._pop_num())),
            "log":  lambda: self.stack.append(math.log10(self._pop_num())),
            "round": lambda: self.stack.append(round(self._pop_num())),
            "floor": lambda: self.stack.append(math.floor(self._pop_num())),
            "ceiling": lambda: self.stack.append(math.ceil(self._pop_num())),
            "truncate": lambda: self.stack.append(int(self._pop_num())),
            "cvi": lambda: self.stack.append(int(self._pop_num())),
            "cvr": lambda: self.stack.append(float(self._pop_num())),

            # Comparison/logic
            "eq": lambda: self._binop(lambda a, b: a == b),
            "ne": lambda: self._binop(lambda a, b: a != b),
            "lt": lambda: self._binop(lambda a, b: a < b),
            "le": lambda: self._binop(lambda a, b: a <= b),
            "gt": lambda: self._binop(lambda a, b: a > b),
            "ge": lambda: self._binop(lambda a, b: a >= b),
            "and": lambda: self._binop(lambda a, b: (a & b) if isinstance(a, int) else (a and b)),
            "or":  lambda: self._binop(lambda a, b: (a | b) if isinstance(a, int) else (a or b)),
            "not": lambda: self.stack.append(not self.stack.pop()),
            "true":  lambda: self.stack.append(True),
            "false": lambda: self.stack.append(False),

            # Dict / variable
            "def":  self.op_def,
            "bind": self.op_bind,
            "load": self.op_load,
            "where": self.op_where,
            "dict": self.op_dict,
            "begin": self.op_begin,
            "end":   self.op_end,
            "store": self.op_def,         # close enough for our use
            "currentdict": lambda: self.stack.append(self.dict_stack[-1]),
            "userdict": lambda: self.stack.append(self.dict_stack[0]),
            "globaldict": lambda: self.stack.append(self.dict_stack[0]),
            "systemdict": lambda: self.stack.append(self.dict_stack[0]),
            "readonly":   lambda: None,
            "noaccess":   lambda: None,
            "executeonly": lambda: None,

            # Graphics state
            "gsave":    self.op_gsave,
            "grestore": self.op_grestore,
            "save":     lambda: self.stack.append(("save", self.op_gsave_silent())),
            "restore":  self.op_restore,
            "initgraphics": self.op_initgraphics,
            "setlinewidth": self.op_setlinewidth,
            "setlinecap":   self.op_setlinecap,
            "setlinejoin":  self.op_setlinejoin,
            "setmiterlimit": self.op_setmiterlimit,
            "setdash":      self.op_setdash,
            "setgray":      self.op_setgray,
            "setrgbcolor":  self.op_setrgbcolor,
            "setcmykcolor": self.op_setcmykcolor,
            "sethsbcolor":  self.op_sethsbcolor,
            "setcolor":     self.op_setrgbcolor,
            "setcolorspace": self.op_pop,    # ignore
            "currentgray":  lambda: self.stack.append(0.0),
            "currentrgbcolor": lambda: self.stack.extend(self.gstate.fill_color),
            "currentlinewidth": lambda: self.stack.append(self.gstate.line_width),

            # Path
            "newpath":   self.op_newpath,
            "moveto":    self.op_moveto,
            "lineto":    self.op_lineto,
            "curveto":   self.op_curveto,
            "rmoveto":   self.op_rmoveto,
            "rlineto":   self.op_rlineto,
            "rcurveto":  self.op_rcurveto,
            "closepath": self.op_closepath,
            "arc":       self.op_arc,
            "arcn":      self.op_arcn,
            "arcto":     self.op_arcto,
            "currentpoint": self.op_currentpoint,
            "clip":      lambda: None,     # no-op
            "eoclip":    lambda: None,
            "clippath":  lambda: None,
            "pathbbox":  self.op_pathbbox,

            # Painting
            "stroke":    self.op_stroke,
            "fill":      self.op_fill,
            "eofill":    self.op_eofill,
            "rectfill":  self.op_rectfill,
            "rectstroke": self.op_rectstroke,
            "rectclip":  self.op_rectclip,

            # Transforms
            "translate": self.op_translate,
            "scale":     self.op_scale,
            "rotate":    self.op_rotate,
            "concat":    self.op_concat,
            "matrix":    self.op_matrix,
            "identmatrix": self.op_matrix,
            "currentmatrix": self.op_currentmatrix,
            "setmatrix":    self.op_setmatrix,
            "defaultmatrix": self.op_matrix,
            "transform":    self.op_transform,
            "itransform":   self.op_itransform,
            "dtransform":   self.op_dtransform,
            "idtransform":  self.op_idtransform,

            # Control flow
            "if":      self.op_if,
            "ifelse":  self.op_ifelse,
            "for":     self.op_for,
            "repeat":  self.op_repeat,
            "loop":    self.op_loop,
            "exit":    self.op_exit,
            "exec":    self.op_exec,
            "stopped": self.op_stopped,
            "stop":    self.op_exit,

            # Arrays / strings — minimal
            "array":   self.op_array,
            "aload":   self.op_aload,
            "astore":  self.op_astore,
            "length":  self.op_length,
            "get":     self.op_get,
            "put":     self.op_put,
            "getinterval": self.op_getinterval,
            "putinterval": lambda: (self.stack.pop(), self.stack.pop(), self.stack.pop()),
            "forall":  self.op_forall,
            "string":  lambda: self.stack.append(" " * int(self.stack.pop())),

            # Text — we don't render text, but parse without crashing
            "show":      self.op_pop,
            "ashow":     lambda: [self.stack.pop() for _ in range(3)],
            "widthshow": lambda: [self.stack.pop() for _ in range(4)],
            "awidthshow": lambda: [self.stack.pop() for _ in range(6)],
            "kshow":     lambda: [self.stack.pop() for _ in range(2)],
            "stringwidth": self.op_stringwidth,
            "charpath":  self.op_pop,
            "findfont":  lambda: self.stack.append({"FontName": self.stack.pop()}),
            "scalefont": lambda: self.stack.pop(),  # leaves font on stack
            "selectfont": lambda: (self.stack.pop(), self.stack.pop()),
            "setfont":   self.op_pop,
            "currentfont": lambda: self.stack.append({}),

            # showpage / EOF
            "showpage":     self.op_showpage,
            "erasepage":    lambda: None,
            "copypage":     lambda: None,
            "setpagedevice": self.op_setpagedevice,
            "currentpagedevice": lambda: self.stack.append({}),
            "null":      lambda: self.stack.append(None),
            "nulldevice": lambda: None,

            # Image — handled separately, but consume args
            "image":      self.op_image_skip,
            "imagemask":  self.op_image_skip,
            "colorimage": self.op_image_skip,

            # Misc / no-ops
            "%%BeginProlog": lambda: None,
            "%%EndProlog":   lambda: None,
            "bind":          self.op_bind,
        }
        d.update({k: v for k, v in ops.items()})

    # -- helpers --------------------------------------------------------------

    def _pop_num(self) -> float:
        v = self.stack.pop()
        if isinstance(v, bool):
            return float(v)
        if isinstance(v, (int, float)):
            return float(v)
        raise PSError(f"expected number, got {type(v).__name__}")

    def _binop(self, fn: Callable[[Any, Any], Any]):
        b = self.stack.pop()
        a = self.stack.pop()
        self.stack.append(fn(a, b))

    def _resolve(self, name: str):
        for d in reversed(self.dict_stack):
            if name in d:
                return d[name]
        return None

    # -- transform helpers ----------------------------------------------------

    def _apply_ctm(self, x: float, y: float) -> tuple[float, float]:
        a, b, c, d, e, f = self.gstate.ctm
        return a * x + c * y + e, b * x + d * y + f

    def _premul_ctm(self, m: list[float]):
        # CTM' = m * CTM
        a, b, c, d, e, f = m
        a2, b2, c2, d2, e2, f2 = self.gstate.ctm
        self.gstate.ctm = [
            a * a2 + b * c2,
            a * b2 + b * d2,
            c * a2 + d * c2,
            c * b2 + d * d2,
            e * a2 + f * c2 + e2,
            e * b2 + f * d2 + f2,
        ]

    # -- operator implementations --------------------------------------------

    def op_dup(self):    self.stack.append(self.stack[-1])
    def op_pop(self):    self.stack.pop()
    def op_exch(self):   self.stack[-1], self.stack[-2] = self.stack[-2], self.stack[-1]

    def op_copy(self):
        n = int(self.stack.pop())
        if n <= 0: return
        self.stack.extend(self.stack[-n:])

    def op_index(self):
        n = int(self.stack.pop())
        self.stack.append(self.stack[-n - 1])

    def op_roll(self):
        j = int(self.stack.pop())
        n = int(self.stack.pop())
        if n <= 0: return
        seg = self.stack[-n:]
        j %= n
        self.stack[-n:] = seg[-j:] + seg[:-j]

    def op_cleartomark(self):
        while self.stack and not isinstance(self.stack[-1], PSMark):
            self.stack.pop()
        if self.stack: self.stack.pop()

    def op_counttomark(self):
        for i in range(len(self.stack) - 1, -1, -1):
            if isinstance(self.stack[i], PSMark):
                self.stack.append(len(self.stack) - i - 1); return
        self.stack.append(len(self.stack))

    def op_atan(self):
        den = self._pop_num()
        num = self._pop_num()
        a = math.degrees(math.atan2(num, den))
        if a < 0: a += 360
        self.stack.append(a)

    def op_def(self):
        val = self.stack.pop()
        key = self.stack.pop()
        if isinstance(key, PSName):
            self.dict_stack[-1][key.name] = val
        elif isinstance(key, str):
            self.dict_stack[-1][key] = val

    def op_bind(self):
        # Just leave the proc on the stack (or do nothing if no proc)
        return

    def op_load(self):
        key = self.stack.pop()
        if isinstance(key, PSName):
            v = self._resolve(key.name)
            self.stack.append(v if v is not None else key)
        else:
            self.stack.append(key)

    def op_where(self):
        key = self.stack.pop()
        if isinstance(key, PSName) and self._resolve(key.name) is not None:
            self.stack.append(self.dict_stack[-1])
            self.stack.append(True)
        else:
            self.stack.append(False)

    def op_dict(self):
        self.stack.pop()  # capacity
        self.stack.append({})

    def op_begin(self):
        d = self.stack.pop()
        if isinstance(d, dict):
            self.dict_stack.append(d)

    def op_end(self):
        if len(self.dict_stack) > 1:
            self.dict_stack.pop()

    # Graphics state
    def op_gsave(self):
        self.gstate_stack.append(self.gstate.copy())

    def op_gsave_silent(self):
        self.gstate_stack.append(self.gstate.copy())
        return len(self.gstate_stack)

    def op_grestore(self):
        if self.gstate_stack:
            self.gstate = self.gstate_stack.pop()

    def op_restore(self):
        token = self.stack.pop()
        if self.gstate_stack:
            self.gstate = self.gstate_stack.pop()

    def op_initgraphics(self):
        self.gstate = GState()

    def op_setlinewidth(self):
        self.gstate.line_width = self._pop_num()

    def op_setlinecap(self):
        self.gstate.line_cap = int(self._pop_num())

    def op_setlinejoin(self):
        self.gstate.line_join = int(self._pop_num())

    def op_setmiterlimit(self):
        self.gstate.miter_limit = self._pop_num()

    def op_setdash(self):
        offset = self._pop_num()
        arr = self.stack.pop()
        if isinstance(arr, list):
            self.gstate.dash_array = [float(x) for x in arr]
        else:
            self.gstate.dash_array = []
        self.gstate.dash_offset = offset

    def op_setgray(self):
        g = max(0.0, min(1.0, self._pop_num()))
        self.gstate.fill_color = (g, g, g)
        self.gstate.stroke_color = (g, g, g)

    def op_setrgbcolor(self):
        b = max(0.0, min(1.0, self._pop_num()))
        g = max(0.0, min(1.0, self._pop_num()))
        r = max(0.0, min(1.0, self._pop_num()))
        self.gstate.fill_color = (r, g, b)
        self.gstate.stroke_color = (r, g, b)

    def op_setcmykcolor(self):
        k = self._pop_num()
        y = self._pop_num()
        m = self._pop_num()
        c = self._pop_num()
        r = (1 - c) * (1 - k)
        g = (1 - m) * (1 - k)
        b = (1 - y) * (1 - k)
        self.gstate.fill_color = (r, g, b)
        self.gstate.stroke_color = (r, g, b)

    def op_sethsbcolor(self):
        v = self._pop_num()
        s = self._pop_num()
        h = self._pop_num()
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        self.gstate.fill_color = (r, g, b)
        self.gstate.stroke_color = (r, g, b)

    # Path construction
    def op_newpath(self):
        self.path = []
        self.current_point = None

    def op_moveto(self):
        y = self._pop_num(); x = self._pop_num()
        self.current_point = (x, y)
        self.path.append([("M", x, y)])

    def op_lineto(self):
        y = self._pop_num(); x = self._pop_num()
        if self.path:
            self.path[-1].append(("L", x, y))
        else:
            self.path.append([("M", x, y)])
        self.current_point = (x, y)

    def op_curveto(self):
        y3 = self._pop_num(); x3 = self._pop_num()
        y2 = self._pop_num(); x2 = self._pop_num()
        y1 = self._pop_num(); x1 = self._pop_num()
        if self.path:
            self.path[-1].append(("C", x1, y1, x2, y2, x3, y3))
            self.current_point = (x3, y3)

    def op_rmoveto(self):
        dy = self._pop_num(); dx = self._pop_num()
        if self.current_point:
            x, y = self.current_point
            self.current_point = (x + dx, y + dy)
            self.path.append([("M", x + dx, y + dy)])

    def op_rlineto(self):
        dy = self._pop_num(); dx = self._pop_num()
        if self.current_point:
            x, y = self.current_point
            nx, ny = x + dx, y + dy
            if self.path:
                self.path[-1].append(("L", nx, ny))
            self.current_point = (nx, ny)

    def op_rcurveto(self):
        dy3 = self._pop_num(); dx3 = self._pop_num()
        dy2 = self._pop_num(); dx2 = self._pop_num()
        dy1 = self._pop_num(); dx1 = self._pop_num()
        if self.current_point:
            x, y = self.current_point
            x1, y1 = x + dx1, y + dy1
            x2, y2 = x + dx2, y + dy2
            x3, y3 = x + dx3, y + dy3
            if self.path:
                self.path[-1].append(("C", x1, y1, x2, y2, x3, y3))
            self.current_point = (x3, y3)

    def op_closepath(self):
        if self.path and self.path[-1]:
            self.path[-1].append(("Z",))
            # Move current point to start of subpath
            first = self.path[-1][0]
            if first[0] == "M":
                self.current_point = (first[1], first[2])

    def op_arc(self):
        a2 = self._pop_num(); a1 = self._pop_num()
        r  = self._pop_num()
        cy = self._pop_num(); cx = self._pop_num()
        self._arc_to_path(cx, cy, r, a1, a2, ccw=True)

    def op_arcn(self):
        a2 = self._pop_num(); a1 = self._pop_num()
        r  = self._pop_num()
        cy = self._pop_num(); cx = self._pop_num()
        self._arc_to_path(cx, cy, r, a1, a2, ccw=False)

    def op_arcto(self):
        # ignore tangent arc; just consume args
        for _ in range(5): self._pop_num()
        self.stack.extend([0.0, 0.0, 0.0, 0.0])

    def _arc_to_path(self, cx, cy, r, a1, a2, ccw=True):
        a1r = math.radians(a1)
        a2r = math.radians(a2)
        if ccw and a2 < a1: a2 += 360
        if not ccw and a2 > a1: a2 -= 360
        # Approximate arc with cubic Beziers — 90deg segments
        sx = cx + r * math.cos(a1r); sy = cy + r * math.sin(a1r)
        if not self.path or not self.path[-1]:
            self.path.append([("M", sx, sy)])
        else:
            self.path[-1].append(("L", sx, sy))
        steps = max(1, int(math.ceil(abs(a2 - a1) / 90.0)))
        delta = (a2 - a1) / steps
        for k in range(steps):
            t1 = math.radians(a1 + delta * k)
            t2 = math.radians(a1 + delta * (k + 1))
            alpha = math.tan((t2 - t1) / 2) * 4.0 / 3.0
            x1 = cx + r * math.cos(t1); y1 = cy + r * math.sin(t1)
            x4 = cx + r * math.cos(t2); y4 = cy + r * math.sin(t2)
            x2 = x1 - alpha * r * math.sin(t1); y2 = y1 + alpha * r * math.cos(t1)
            x3 = x4 + alpha * r * math.sin(t2); y3 = y4 - alpha * r * math.cos(t2)
            self.path[-1].append(("C", x2, y2, x3, y3, x4, y4))
        self.current_point = (cx + r * math.cos(math.radians(a2)),
                              cy + r * math.sin(math.radians(a2)))

    def op_currentpoint(self):
        if self.current_point:
            self.stack.extend(self.current_point)
        else:
            self.stack.extend([0.0, 0.0])

    def op_pathbbox(self):
        xs, ys = [], []
        for sub in self.path:
            for seg in sub:
                if seg[0] in ("M", "L"):
                    xs.append(seg[1]); ys.append(seg[2])
                elif seg[0] == "C":
                    xs.extend([seg[1], seg[3], seg[5]])
                    ys.extend([seg[2], seg[4], seg[6]])
        if xs:
            self.stack.extend([min(xs), min(ys), max(xs), max(ys)])
        else:
            self.stack.extend([0, 0, 0, 0])

    # Painting — emit SVG
    def _path_to_svg_d(self) -> str:
        out = []
        for sub in self.path:
            for seg in sub:
                if seg[0] == "M":
                    x, y = self._apply_ctm(seg[1], seg[2])
                    out.append(f"M{x:.3f} {y:.3f}")
                elif seg[0] == "L":
                    x, y = self._apply_ctm(seg[1], seg[2])
                    out.append(f"L{x:.3f} {y:.3f}")
                elif seg[0] == "C":
                    x1, y1 = self._apply_ctm(seg[1], seg[2])
                    x2, y2 = self._apply_ctm(seg[3], seg[4])
                    x3, y3 = self._apply_ctm(seg[5], seg[6])
                    out.append(f"C{x1:.3f} {y1:.3f} {x2:.3f} {y2:.3f} {x3:.3f} {y3:.3f}")
                elif seg[0] == "Z":
                    out.append("Z")
        return " ".join(out)

    def _path_to_svg_d_with_bbox(self) -> tuple[str, tuple[float, float, float, float] | None]:
        """Like _path_to_svg_d but also returns the device-coord bbox.
        Returns (d_string, bbox) where bbox is (x0, y0, x1, y1) or None
        if the path is empty."""
        out = []
        xs: list[float] = []
        ys: list[float] = []
        for sub in self.path:
            for seg in sub:
                if seg[0] == "M":
                    x, y = self._apply_ctm(seg[1], seg[2])
                    xs.append(x); ys.append(y)
                    out.append(f"M{x:.3f} {y:.3f}")
                elif seg[0] == "L":
                    x, y = self._apply_ctm(seg[1], seg[2])
                    xs.append(x); ys.append(y)
                    out.append(f"L{x:.3f} {y:.3f}")
                elif seg[0] == "C":
                    x1, y1 = self._apply_ctm(seg[1], seg[2])
                    x2, y2 = self._apply_ctm(seg[3], seg[4])
                    x3, y3 = self._apply_ctm(seg[5], seg[6])
                    xs.extend([x1, x2, x3]); ys.extend([y1, y2, y3])
                    out.append(f"C{x1:.3f} {y1:.3f} {x2:.3f} {y2:.3f} {x3:.3f} {y3:.3f}")
                elif seg[0] == "Z":
                    out.append("Z")
        bbox = (min(xs), min(ys), max(xs), max(ys)) if xs else None
        return " ".join(out), bbox

    def _color_hex(self, rgb) -> str:
        r, g, b = rgb
        return "#{:02x}{:02x}{:02x}".format(int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))

    def op_stroke(self):
        d, bbox = self._path_to_svg_d_with_bbox()
        if d:
            # Effective stroke width: PS line width × CTM scale (avg of |a| and |d|)
            a, b, c, dd = self.gstate.ctm[:4]
            sx = math.hypot(a, b)
            sy = math.hypot(c, dd)
            w = self.gstate.line_width * (sx + sy) / 2.0
            attrs = [
                f'd="{d}"',
                'fill="none"',
                f'stroke="{self._color_hex(self.gstate.stroke_color)}"',
                f'stroke-width="{max(w, 0.1):.3f}"',
            ]
            if self.gstate.line_cap:
                attrs.append(f'stroke-linecap="{["butt","round","square"][self.gstate.line_cap]}"')
            if self.gstate.line_join:
                attrs.append(f'stroke-linejoin="{["miter","round","bevel"][self.gstate.line_join]}"')
            if self.gstate.dash_array:
                attrs.append(f'stroke-dasharray="{",".join(f"{x:.3f}" for x in self.gstate.dash_array)}"')
            self.pages[-1].append("<path " + " ".join(attrs) + "/>")
            if bbox is not None:
                self.path_metadata.append(PathMeta(
                    svg_index=len(self.pages[-1]) - 1,
                    bbox=bbox,
                    group_id=self.current_group_id,
                ))
        self.op_newpath()

    def op_fill(self):
        d, bbox = self._path_to_svg_d_with_bbox()
        if d:
            self.pages[-1].append(
                f'<path d="{d}" fill="{self._color_hex(self.gstate.fill_color)}" '
                f'fill-rule="nonzero" stroke="none"/>'
            )
            if bbox is not None:
                self.path_metadata.append(PathMeta(
                    svg_index=len(self.pages[-1]) - 1,
                    bbox=bbox,
                    group_id=self.current_group_id,
                ))
        self.op_newpath()

    def op_eofill(self):
        d, bbox = self._path_to_svg_d_with_bbox()
        if d:
            self.pages[-1].append(
                f'<path d="{d}" fill="{self._color_hex(self.gstate.fill_color)}" '
                f'fill-rule="evenodd" stroke="none"/>'
            )
            if bbox is not None:
                self.path_metadata.append(PathMeta(
                    svg_index=len(self.pages[-1]) - 1,
                    bbox=bbox,
                    group_id=self.current_group_id,
                ))
        self.op_newpath()

    def op_rectfill(self):
        h = self._pop_num(); w = self._pop_num()
        y = self._pop_num(); x = self._pop_num()
        self.op_newpath()
        self.stack.extend([x, y]);          self.op_moveto()
        self.stack.extend([x + w, y]);      self.op_lineto()
        self.stack.extend([x + w, y + h]);  self.op_lineto()
        self.stack.extend([x, y + h]);      self.op_lineto()
        self.op_closepath()
        self.op_fill()

    def op_rectstroke(self):
        h = self._pop_num(); w = self._pop_num()
        y = self._pop_num(); x = self._pop_num()
        self.op_newpath()
        self.stack.extend([x, y]);          self.op_moveto()
        self.stack.extend([x + w, y]);      self.op_lineto()
        self.stack.extend([x + w, y + h]);  self.op_lineto()
        self.stack.extend([x, y + h]);      self.op_lineto()
        self.op_closepath()
        self.op_stroke()

    def op_rectclip(self):
        for _ in range(4): self._pop_num()

    # Transforms
    def op_translate(self):
        ty = self._pop_num(); tx = self._pop_num()
        self._premul_ctm([1, 0, 0, 1, tx, ty])

    def op_scale(self):
        sy = self._pop_num(); sx = self._pop_num()
        self._premul_ctm([sx, 0, 0, sy, 0, 0])

    def op_rotate(self):
        a = math.radians(self._pop_num())
        c, s = math.cos(a), math.sin(a)
        self._premul_ctm([c, s, -s, c, 0, 0])

    def op_concat(self):
        m = self.stack.pop()
        if isinstance(m, list) and len(m) == 6:
            self._premul_ctm([float(x) for x in m])

    def op_matrix(self):
        self.stack.append([1.0, 0.0, 0.0, 1.0, 0.0, 0.0])

    def op_currentmatrix(self):
        m = self.stack.pop()
        if isinstance(m, list) and len(m) == 6:
            for i in range(6):
                m[i] = self.gstate.ctm[i]
            self.stack.append(m)
        else:
            self.stack.append(list(self.gstate.ctm))

    def op_setmatrix(self):
        m = self.stack.pop()
        if isinstance(m, list) and len(m) == 6:
            self.gstate.ctm = [float(x) for x in m]

    def op_transform(self):
        # x y [matrix] transform → x' y'
        m = self.stack[-1] if isinstance(self.stack[-1], list) else None
        if m:
            self.stack.pop()
            a, b, c, d, e, f = m
        else:
            a, b, c, d, e, f = self.gstate.ctm
        y = self._pop_num(); x = self._pop_num()
        self.stack.append(a * x + c * y + e)
        self.stack.append(b * x + d * y + f)

    def op_itransform(self):
        m = self.stack[-1] if isinstance(self.stack[-1], list) else None
        if m:
            self.stack.pop()
            a, b, c, d, e, f = m
        else:
            a, b, c, d, e, f = self.gstate.ctm
        y = self._pop_num(); x = self._pop_num()
        det = a * d - b * c
        if det == 0:
            self.stack.extend([x, y]); return
        x -= e; y -= f
        self.stack.append((d * x - c * y) / det)
        self.stack.append((-b * x + a * y) / det)

    def op_dtransform(self):
        m = self.stack[-1] if isinstance(self.stack[-1], list) else None
        if m: self.stack.pop()
        a, b, c, d = (m[0], m[1], m[2], m[3]) if m else self.gstate.ctm[:4]
        y = self._pop_num(); x = self._pop_num()
        self.stack.append(a * x + c * y)
        self.stack.append(b * x + d * y)

    def op_idtransform(self):
        m = self.stack[-1] if isinstance(self.stack[-1], list) else None
        if m: self.stack.pop()
        a, b, c, d = (m[0], m[1], m[2], m[3]) if m else self.gstate.ctm[:4]
        y = self._pop_num(); x = self._pop_num()
        det = a * d - b * c
        if det == 0:
            self.stack.extend([x, y]); return
        self.stack.append((d * x - c * y) / det)
        self.stack.append((-b * x + a * y) / det)

    # Control flow
    def op_if(self):
        proc = self.stack.pop()
        cond = self.stack.pop()
        if cond and isinstance(proc, PSProc):
            self._exec_proc(proc)

    def op_ifelse(self):
        p2 = self.stack.pop()
        p1 = self.stack.pop()
        cond = self.stack.pop()
        target = p1 if cond else p2
        if isinstance(target, PSProc):
            self._exec_proc(target)

    # Per-loop caps. Even with these, the global op budget is the real
    # safety net — nested loops compound and only the global counter sees
    # the total cost.
    _LOOP_CAP = 50_000

    def op_for(self):
        proc = self.stack.pop()
        limit = self._pop_num()
        incr = self._pop_num()
        init = self._pop_num()
        if incr == 0:  # would never terminate
            return
        i = init
        steps = 0
        while ((incr > 0 and i <= limit) or (incr < 0 and i >= limit)):
            self.stack.append(i)
            if isinstance(proc, PSProc):
                try:
                    self._exec_proc(proc)
                except _ExitException:
                    return
            i += incr
            steps += 1
            if steps > self._LOOP_CAP:
                return  # local cap; global budget is the hard limit

    def op_repeat(self):
        proc = self.stack.pop()
        n = int(self._pop_num())
        for _ in range(min(n, self._LOOP_CAP)):
            if isinstance(proc, PSProc):
                try:
                    self._exec_proc(proc)
                except _ExitException:
                    return

    def op_loop(self):
        proc = self.stack.pop()
        if not isinstance(proc, PSProc): return
        for _ in range(self._LOOP_CAP):
            try:
                self._exec_proc(proc)
            except _ExitException:
                return

    def op_exit(self):
        raise _ExitException()

    def op_exec(self):
        obj = self.stack.pop()
        if isinstance(obj, PSProc):
            self._exec_proc(obj)

    def op_stopped(self):
        proc = self.stack.pop()
        if isinstance(proc, PSProc):
            try:
                self._exec_proc(proc)
                self.stack.append(False)
            except (_ExitException, _BudgetExhausted):
                # exit must propagate to the enclosing loop, and budget
                # exhaustion must always abort the whole conversion.
                raise
            except Exception:
                self.stack.append(True)
        else:
            self.stack.append(False)

    # Arrays
    def op_array(self):
        n = int(self._pop_num())
        self.stack.append([0] * n)

    def op_aload(self):
        a = self.stack.pop()
        if isinstance(a, list):
            self.stack.extend(a)
            self.stack.append(a)

    def op_astore(self):
        a = self.stack.pop()
        if isinstance(a, list):
            n = len(a)
            vals = [self.stack.pop() for _ in range(n)][::-1]
            for i, v in enumerate(vals): a[i] = v
            self.stack.append(a)

    def op_length(self):
        v = self.stack.pop()
        if isinstance(v, (list, dict, str)):
            self.stack.append(len(v))
        else:
            self.stack.append(0)

    def op_get(self):
        k = self.stack.pop()
        v = self.stack.pop()
        try:
            if isinstance(v, list):
                self.stack.append(v[int(k)])
            elif isinstance(v, dict):
                key = k.name if isinstance(k, PSName) else k
                self.stack.append(v.get(key, 0))
            elif isinstance(v, str):
                self.stack.append(ord(v[int(k)]))
            else:
                self.stack.append(0)
        except Exception:
            self.stack.append(0)

    def op_put(self):
        val = self.stack.pop()
        k = self.stack.pop()
        target = self.stack.pop()
        try:
            if isinstance(target, list):
                target[int(k)] = val
            elif isinstance(target, dict):
                key = k.name if isinstance(k, PSName) else k
                target[key] = val
        except Exception:
            pass

    def op_getinterval(self):
        n = int(self._pop_num())
        i = int(self._pop_num())
        v = self.stack.pop()
        if isinstance(v, (list, str)):
            self.stack.append(v[i:i + n])
        else:
            self.stack.append(v)

    def op_forall(self):
        proc = self.stack.pop()
        coll = self.stack.pop()
        if not isinstance(proc, PSProc): return
        if isinstance(coll, list):
            for v in coll:
                self.stack.append(v)
                try: self._exec_proc(proc)
                except _ExitException: return
        elif isinstance(coll, dict):
            for k, v in coll.items():
                self.stack.append(PSName(k, literal=True))
                self.stack.append(v)
                try: self._exec_proc(proc)
                except _ExitException: return
        elif isinstance(coll, str):
            for c in coll:
                self.stack.append(ord(c))
                try: self._exec_proc(proc)
                except _ExitException: return

    def op_stringwidth(self):
        self.stack.pop()  # string
        self.stack.extend([0.0, 0.0])

    def op_image_skip(self):
        # Best-effort: drop one stack arg (the dict or scanproc) — actual
        # raster data is detected via the separate image extractor.
        if self.stack:
            self.stack.pop()

    def op_showpage(self):
        """End the current page. Start a fresh page buffer and reset CTM/path."""
        # Only start a new page if the current one has content; otherwise this
        # is a redundant showpage at end-of-file.
        if self.pages[-1]:
            self.pages.append([])
        self.op_newpath()

    def op_setpagedevice(self):
        """Consume a dict argument. Extract PageSize if present."""
        d = self.stack.pop() if self.stack else None
        if isinstance(d, dict):
            ps = d.get("PageSize")
            if isinstance(ps, list) and len(ps) == 2:
                try:
                    self.detected_page_size = (float(ps[0]), float(ps[1]))
                except (TypeError, ValueError):
                    pass

    # -- execution ------------------------------------------------------------

    def _exec_proc(self, proc: PSProc):
        if self._proc_depth >= self._MAX_PROC_DEPTH:
            # Recursion too deep — treat like budget exhaustion
            raise _BudgetExhausted("procedure recursion depth exceeded")
        self._proc_depth += 1
        try:
            self._exec_tokens(proc.body)
        finally:
            self._proc_depth -= 1

    def _exec_tokens(self, tokens: list[Any]):
        consume = self.budget.consume
        i, n = 0, len(tokens)
        while i < n:
            consume()  # raises _BudgetExhausted when out of ops/time
            tok = tokens[i]
            i += 1
            if isinstance(tok, (int, float, str, bool)) or tok is None:
                self.stack.append(tok); continue
            if isinstance(tok, PSProc):
                self.stack.append(tok); continue
            if isinstance(tok, PSName):
                if tok.literal:
                    self.stack.append(tok); continue
                name = tok.name
                if name == "[":
                    self.stack.append(MARK); continue
                if name == "]":
                    arr = []
                    while self.stack and not isinstance(self.stack[-1], PSMark):
                        arr.append(self.stack.pop())
                    if self.stack: self.stack.pop()
                    arr.reverse()
                    self.stack.append(arr); continue
                v = self._resolve(name)
                if v is None:
                    self.unknown_ops[name] = self.unknown_ops.get(name, 0) + 1
                    continue
                if callable(v):
                    try:
                        v()
                    except (_ExitException, _BudgetExhausted):
                        raise
                    except Exception:
                        # Swallow per-operator failures to keep going
                        pass
                elif isinstance(v, PSProc):
                    self._exec_proc(v)
                else:
                    self.stack.append(v)
                continue


class _ExitException(Exception):
    pass


# ---------------------------------------------------------------------------
# EPS file parsing — bounding box + embedded JPEG detection
# ---------------------------------------------------------------------------

_BBOX_RE = re.compile(rb"%%(?:HiRes)?BoundingBox:\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)")
_JPEG_SOI = b"\xff\xd8\xff"
_JPEG_EOI = b"\xff\xd9"


def parse_bbox(data: bytes) -> tuple[float, float, float, float] | None:
    """Find a %%BoundingBox: comment. Prefers %%HiResBoundingBox."""
    hires = re.search(rb"%%HiResBoundingBox:\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", data)
    if hires:
        return tuple(float(x) for x in hires.groups())  # type: ignore
    m = _BBOX_RE.search(data)
    if m:
        return tuple(float(x) for x in m.groups())  # type: ignore
    return None


# Standard PostScript paper sizes in points (1pt = 1/72 inch)
_PAPER_SIZES: dict[str, tuple[float, float]] = {
    "letter":    (612.0,  792.0),
    "legal":     (612.0, 1008.0),
    "tabloid":   (792.0, 1224.0),
    "ledger":   (1224.0,  792.0),
    "executive": (522.0,  756.0),
    "a3": (841.890,  1190.551),
    "a4": (595.276,   841.890),
    "a5": (419.528,   595.276),
    "a6": (297.638,   419.528),
    "b4": (708.661,  1000.630),
    "b5": (498.898,   708.661),
}


def parse_page_size(data: bytes) -> tuple[float, float] | None:
    """Find a page size for a PostScript file.

    Tries (in order):
      1. %%DocumentMedia: name width height ...
      2. %%PageBoundingBox: x0 y0 x1 y1
      3. setpagedevice <</PageSize [w h]>>
      4. <</PageSize [w h]>> setpagedevice
      5. Standard named size (e.g. letter, a4) via /letter, /a4 ...
    Returns (width, height) in points, or None.
    """
    m = re.search(rb"%%DocumentMedia:\s*\S+\s+([\d.]+)\s+([\d.]+)", data)
    if m:
        return float(m.group(1)), float(m.group(2))

    m = re.search(
        rb"%%PageBoundingBox:\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", data)
    if m:
        x0, y0, x1, y1 = (float(x) for x in m.groups())
        if x1 > x0 and y1 > y0:
            return x1 - x0, y1 - y0

    m = re.search(rb"/PageSize\s*\[\s*([\d.]+)\s+([\d.]+)\s*\]", data)
    if m:
        return float(m.group(1)), float(m.group(2))

    for name, size in _PAPER_SIZES.items():
        if re.search(rb"\b" + name.encode() + rb"\b\s+setpagedevice", data, re.IGNORECASE):
            return size

    return None


def extract_jpegs(data: bytes) -> list[bytes]:
    """Return any embedded JPEG byte streams found in the EPS."""
    found = []
    i = 0
    while True:
        s = data.find(_JPEG_SOI, i)
        if s < 0: break
        e = data.find(_JPEG_EOI, s)
        if e < 0: break
        found.append(data[s:e + 2])
        i = e + 2
    return found


def strip_eps_binary_header(data: bytes) -> bytes:
    """EPSF binary files (DOS) start with a 30-byte header pointing to the
    ASCII PostScript section. Strip it if present."""
    if data[:4] == b"\xc5\xd0\xd3\xc6":
        ps_offset = int.from_bytes(data[4:8], "little")
        ps_length = int.from_bytes(data[8:12], "little")
        return data[ps_offset:ps_offset + ps_length]
    return data


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_ADOBE_PROLOG = r"""
% Adobe Illustrator / generic EPS shorthand fallbacks.
% These are pre-defined so files that use them without redefining still render.
/bd { def } def
/bdef { def } def
/ld { def } def
/xdf { exch def } def
/m  { moveto } def
/M  { moveto } def
/L  { lineto } def
/l  { lineto } def
/C  { curveto } def
/V  { currentpoint 4 -2 roll 6 -2 roll curveto } def
/Y  { 2 copy curveto } def
/v  { currentpoint 6 2 roll curveto } def
/y  { 2 copy curveto } def
/H  { closepath } def
/h  { closepath } def
/N  { newpath } def
/n  { newpath } def
/F  { fill } def
/f  { closepath fill } def
/B  { gsave fill grestore stroke } def
/b  { closepath gsave fill grestore stroke } def
/S  { stroke } def
/s  { closepath stroke } def
/q  { gsave } def
/Q  { grestore } def
/w  { setlinewidth } def
/J  { setlinecap } def
/j  { setlinejoin } def
/MM { setmiterlimit } def
/Xa { setgray } def
/XA { setgray } def
/g  { setgray } def
/G  { setgray } def
/RGB { setrgbcolor } def
/Xx { setrgbcolor } def
/XX { setrgbcolor } def
/rg { setrgbcolor } def
/RG { setrgbcolor } def
/Xk { setcmykcolor } def
/XK { setcmykcolor } def
/k  { setcmykcolor } def
/K  { setcmykcolor } def
/cs { pop } def
/CS { pop } def
/sc { setrgbcolor } def
/SC { setrgbcolor } def
/scn { setrgbcolor } def
/SCN { setrgbcolor } def
/setoverprint { pop } def
/setflat { pop } def
/setflatness { pop } def
/setstrokeadjust { pop } def
/setsmoothness { pop } def
/i  { pop } def
/I  { pop } def
/d  { setdash } def
/D  { setdash } def
/d0 { pop pop } def
/d1 { pop pop pop pop pop pop } def
/Bd { } def
/Bn { } def
"""


def _detect_is_eps(data: bytes) -> bool:
    """An EPS file declares itself in the first line: %!PS-Adobe-X.Y EPSF-..."""
    head = data[:120]
    return b"EPSF" in head or b"%%BoundingBox" in data[:4096]


def convert_eps_to_svg(
    src: Path,
    dst: Path,
    dpi: int = 96,
    verbose: bool = False,
    page: int | None = None,
    max_ops: int = 5_000_000,
    timeout: float = 30.0,
) -> str:
    """Convert an EPS or PS file to SVG in pure Python.

    For multi-page PS files, renders page 1 by default. Use `page=N` to
    select a different page.

    Safety:
      * `max_ops`   — hard ceiling on operator dispatches (default 5M).
      * `timeout`   — wall-clock seconds (default 30). Pass 0 to disable.

    When a budget is hit, conversion stops gracefully and the SVG contains
    whatever was rendered up to that point, with a warning logged when
    verbose=True.

    Returns a short status string describing what was rendered."""
    raw = src.read_bytes()
    raw = strip_eps_binary_header(raw)

    is_eps = _detect_is_eps(raw)

    bbox = parse_bbox(raw)
    used_bbox_source = "%%BoundingBox" if bbox else None
    if bbox is None:
        page_size = parse_page_size(raw)
        if page_size:
            bbox = (0.0, 0.0, page_size[0], page_size[1])
            used_bbox_source = "page size"
        else:
            bbox = (0.0, 0.0, 612.0, 792.0)
            used_bbox_source = "default letter"

    bx0, by0, bx1, by1 = bbox
    width = max(1.0, bx1 - bx0)
    height = max(1.0, by1 - by0)

    text = raw.decode("latin-1", errors="replace")

    budget = _Budget(max_ops=max_ops, max_seconds=timeout)
    interp = Interpreter(bbox, budget=budget)
    budget_hit_reason = ""

    # Pre-load Adobe shorthand prolog. Use a separate, generous mini-budget
    # so the prolog doesn't eat the user's budget.
    prolog_budget = _Budget(max_ops=100_000, max_seconds=5.0)
    prolog_interp = interp
    prolog_interp.budget = prolog_budget
    try:
        prolog_interp._exec_tokens(tokenize(_ADOBE_PROLOG))
    except (_ExitException, _BudgetExhausted):
        pass
    interp.budget = budget  # restore main budget

    # Tokenize the file under the same budget so pathological inputs can't
    # spin in tokenize() without ever reaching the interpreter.
    try:
        tokens = tokenize(text, budget=budget)
    except _BudgetExhausted as e:
        budget_hit_reason = e.reason
        if verbose:
            import sys
            print(f"  warning: tokenize aborted ({e.reason}); rendering partial output",
                  file=sys.stderr)
        tokens = []
    except Exception as e:
        if verbose:
            import sys
            print(f"  tokenize error: {type(e).__name__}: {e}", file=sys.stderr)
        tokens = []

    try:
        interp._exec_tokens(tokens)
    except _ExitException:
        pass
    except _BudgetExhausted as e:
        budget_hit_reason = budget_hit_reason or e.reason
        if verbose:
            import sys
            print(f"  warning: {e.reason}; rendering partial output",
                  file=sys.stderr)

    # If setpagedevice gave a better page size and we didn't have a real bbox,
    # adopt it now.
    if interp.detected_page_size and used_bbox_source != "%%BoundingBox":
        width  = max(1.0, interp.detected_page_size[0])
        height = max(1.0, interp.detected_page_size[1])
        bx0, by0 = 0.0, 0.0
        bx1, by1 = width, height
        used_bbox_source = "setpagedevice"

    # Filter trailing empty page if showpage ran at EOF.
    pages = [p for p in interp.pages if p]
    if not pages:
        pages = [[]]
    page_count = len(pages)

    # Select which page to render
    selected_page_idx = 0
    if page is not None:
        if page < 1 or page > page_count:
            raise ValueError(
                f"page {page} out of range (file has {page_count} page(s))"
            )
        selected_page_idx = page - 1
    selected_page = pages[selected_page_idx]

    # Detect embedded JPEGs (Getty/iStock-style files)
    jpegs = extract_jpegs(raw)

    # Build SVG. PostScript Y-axis goes up; SVG Y-axis goes down.
    transform = f"translate({-bx0:.3f},{by1:.3f}) scale(1,-1)"

    parts = []
    parts.append('<?xml version="1.0" encoding="UTF-8" standalone="no"?>')
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {width:.3f} {height:.3f}" '
        f'width="{width:.3f}pt" height="{height:.3f}pt">'
    )
    parts.append(f'<g transform="{transform}">')

    rendered_vectors = len(selected_page)
    if rendered_vectors:
        parts.extend(selected_page)

    embedded_images = 0
    if jpegs and not rendered_vectors:
        biggest = max(jpegs, key=len)
        b64 = base64.b64encode(biggest).decode("ascii")
        parts.append(
            f'<g transform="translate({bx0:.3f},{by1:.3f}) scale(1,-1)">'
            f'<image x="0" y="0" width="{width:.3f}" height="{height:.3f}" '
            f'preserveAspectRatio="none" '
            f'xlink:href="data:image/jpeg;base64,{b64}"/>'
            f'</g>'
        )
        embedded_images = 1

    parts.append("</g>")
    parts.append("</svg>")

    dst.write_text("\n".join(parts), encoding="utf-8")

    file_kind = "EPS" if is_eps else "PS"
    page_info = ""
    if page_count > 1:
        shown = selected_page_idx + 1
        page_info = f", page {shown}/{page_count}"

    if rendered_vectors and embedded_images:
        body = f"{rendered_vectors} vector ops + {embedded_images} embedded image"
    elif rendered_vectors:
        body = f"{rendered_vectors} vector ops"
    elif embedded_images:
        body = f"embedded {embedded_images} JPEG"
    else:
        body = "empty (no recognizable content)"

    partial = f", PARTIAL ({budget_hit_reason})" if budget_hit_reason else ""
    status = f"pure-python {file_kind}: {body}{page_info}{partial} [{used_bbox_source}]"

    if verbose and interp.unknown_ops:
        top = sorted(interp.unknown_ops.items(), key=lambda kv: -kv[1])[:5]
        ops = ", ".join(f"{n}({c})" for n, c in top)
        import sys
        print(f"  Unknown PS operators ignored: {ops}", file=sys.stderr)

    return status


# Backwards-compatible alias for callers (and clearer intent for PS files)
def convert_postscript_to_svg(*args, **kwargs):
    return convert_eps_to_svg(*args, **kwargs)


def count_pages(src: Path) -> int:
    """Quick scan: count the number of pages in a PS/EPS file.
    Uses %%Pages: comment if present, otherwise counts non-trailing showpage."""
    raw = src.read_bytes()
    raw = strip_eps_binary_header(raw)
    m = re.search(rb"%%Pages:\s*(\d+)", raw)
    if m:
        n = int(m.group(1))
        if n > 0:
            return n
    text = raw.decode("latin-1", errors="replace")
    # Count showpage occurrences as a heuristic
    return max(1, len(re.findall(r"(?<!\w)showpage(?!\w)", text)))
