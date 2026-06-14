"""Inline vector icons for the GUI.

The toolbar/utility buttons are icon-only; each icon is drawn from an inline
SVG string (rendered via ``PySide6.QtSvg``, already a dependency) so there are
no binary asset files to ship and the icons stay crisp at any DPI.

Strokes use the application palette's ``ButtonText`` colour, so the icons follow
the active light/dark theme. Icons are cached per (name, colour); a palette
change after first render keeps the original colour (acceptable — the GUI does
not switch themes at runtime).
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

# Sizes rendered into each QIcon — covers 1x/1.5x/2x for the 16-20-24 px range
# the toolbar and status bar use.
_RENDER_SIZES = (16, 20, 24, 32, 40, 48)

# Each value is a 24x24 viewBox SVG with a ``{stroke}`` placeholder for colour.
_SVG: dict[str, str] = {
    # Document with a folded corner and a plus — "Add Files".
    "add_files": """
        <path d="M13 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V8z"/>
        <path d="M13 3v5h5"/>
        <path d="M12 12v6"/>
        <path d="M9 15h6"/>
    """,
    # Trash can — "Remove" selected files from the queue.
    "remove": """
        <path d="M4 7h16"/>
        <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
        <path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/>
        <path d="M10 11v6"/>
        <path d="M14 11v6"/>
    """,
    # Folder with a plus — "Add Folder".
    "add_folder": """
        <path d="M3 7a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>
        <path d="M12 11v6"/>
        <path d="M9 14h6"/>
    """,
    # Plain folder — "Change…" output destination.
    "folder": """
        <path d="M3 7a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>
    """,
    # Four panes — "Split…".
    "split": """
        <rect x="4" y="4" width="7" height="7" rx="1"/>
        <rect x="13" y="4" width="7" height="7" rx="1"/>
        <rect x="4" y="13" width="7" height="7" rx="1"/>
        <rect x="13" y="13" width="7" height="7" rx="1"/>
    """,
    # Presentation screen on a stand with a bar chart — "Export PPTX".
    "pptx": """
        <rect x="3" y="4" width="18" height="12" rx="1"/>
        <path d="M12 16v4"/>
        <path d="M8 20h8"/>
        <path d="M8 12v-2"/>
        <path d="M12 12V8"/>
        <path d="M16 12v-3"/>
    """,
    # Corner brackets — "Fit to view".
    "fit": """
        <path d="M4 9V5a1 1 0 0 1 1-1h4"/>
        <path d="M20 9V5a1 1 0 0 0-1-1h-4"/>
        <path d="M4 15v4a1 1 0 0 0 1 1h4"/>
        <path d="M20 15v4a1 1 0 0 1-1 1h-4"/>
    """,
    # "1:1" rendered as line-art numerals — actual size.
    "one_to_one": """
        <path d="M6 9l2-2v10"/>
        <path d="M6.5 17H10"/>
        <path d="M16 9l2-2v10"/>
        <path d="M16.5 17H20"/>
        <circle cx="12" cy="9" r="0.7" fill="{stroke}" stroke="none"/>
        <circle cx="12" cy="14" r="0.7" fill="{stroke}" stroke="none"/>
    """,
    # Magic wand with sparkles — "Auto-detect grid".
    "auto_detect": """
        <path d="M5 19 15 9"/>
        <path d="M13 7l4 4"/>
        <path d="M18 4l.5 1.5L20 6l-1.5.5L18 8l-.5-1.5L16 6z" fill="{stroke}" stroke="none"/>
        <path d="M5 6l.4 1.1L6.6 7.5l-1.2.4L5 9l-.4-1.1L3.4 7.5l1.2-.4z" fill="{stroke}" stroke="none"/>
    """,
    # Scissors — "Auto-split now".
    "scissors": """
        <circle cx="6" cy="6" r="2.5"/>
        <circle cx="6" cy="18" r="2.5"/>
        <path d="M8 7.5 20 16"/>
        <path d="M8 16.5 20 8"/>
    """,
    # Arrow into a tray — "Extract" (write cells to disk).
    "extract": """
        <path d="M12 3v10"/>
        <path d="M8 9l4 4 4-4"/>
        <path d="M5 17v2a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2"/>
    """,
    # Two opposing arrows — "Convert" (transform EPS→SVG).
    "convert": """
        <path d="M4 8h11"/>
        <path d="M12 5l3 3-3 3"/>
        <path d="M20 16H9"/>
        <path d="M12 19l-3-3 3-3"/>
    """,
    # Magnifier with a plus — "Zoom in".
    "zoom_in": """
        <circle cx="10.5" cy="10.5" r="6.5"/>
        <path d="M20 20l-4.8-4.8"/>
        <path d="M10.5 7.5v6"/>
        <path d="M7.5 10.5h6"/>
    """,
    # Magnifier with a minus — "Zoom out".
    "zoom_out": """
        <circle cx="10.5" cy="10.5" r="6.5"/>
        <path d="M20 20l-4.8-4.8"/>
        <path d="M7.5 10.5h6"/>
    """,
}

_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{stroke}" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round">{body}</svg>'
)

_cache: dict[tuple[str, str], QIcon] = {}


def _stroke_color() -> str:
    """The palette ButtonText colour as a hex string, with a neutral fallback."""
    app = QApplication.instance()
    if app is not None:
        return app.palette().color(QPalette.ColorRole.ButtonText).name()
    return "#3c3c3c"


def _render(svg: str, size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return pm


def icon(name: str) -> QIcon:
    """Return the cached QIcon for ``name`` (see ``_SVG`` for the catalogue)."""
    stroke = _stroke_color()
    key = (name, stroke)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    svg = _TEMPLATE.format(stroke=stroke, body=_SVG[name].format(stroke=stroke))
    ic = QIcon()
    for size in _RENDER_SIZES:
        ic.addPixmap(_render(svg, size))
    _cache[key] = ic
    return ic
