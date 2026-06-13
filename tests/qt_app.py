"""Shared helper to obtain a headless QApplication for GUI tests.

Importing this module forces the offscreen platform plugin, so widget code can
run with no display. Always use QApplication (not QCoreApplication): unittest
runs every test in one process, and a QApplication cannot be created if a plain
QCoreApplication already exists.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def ensure_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
