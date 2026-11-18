"""Select the native X11 Qt backend required by VTK on Ubuntu/Wayland."""
import ctypes
import os
from pathlib import Path
import sys


def configure_environment() -> None:
    os.environ.setdefault("QT_API", "pyside6")
    if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    # Optional bundled Qt dependency, resolved relative to the application.
    library = Path(__file__).resolve().parents[2] / ".local-libs/usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0"
    if library.exists():
        ctypes.CDLL(str(library), mode=ctypes.RTLD_GLOBAL)

