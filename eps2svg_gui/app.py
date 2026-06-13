"""QApplication bootstrap and the `eps2svg-gui` entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from eps2svg_gui.main_window import MainWindow


def build_window() -> MainWindow:
    """Construct the main window (separated from main() so it is testable)."""
    return MainWindow()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("eps2svg")
    app.setApplicationDisplayName("eps2svg — EPS/PS → SVG")
    window = build_window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
