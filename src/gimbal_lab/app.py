from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

from gimbal_lab.bootstrap import configure_environment
from gimbal_lab import __version__


def setup_logging() -> Path:
    state_root = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    directory = state_root / "gimbal-calibration-lab"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "app.log"
    handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[handler, logging.StreamHandler()])
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Gimbal Calibration Lab — reproducible calibration experiments")
    parser.add_argument("--project", type=Path, help="打开已保存的实验项目")
    parser.add_argument("--size", default="1480x900", help="初始窗口尺寸，如 1366x768")
    args = parser.parse_args()
    try:
        width, height = [int(x) for x in args.size.lower().split("x")]
        if width < 1100 or height < 700:
            raise ValueError
    except ValueError:
        parser.error("窗口尺寸至少为 1100x700")
    configure_environment()
    from PySide6.QtWidgets import QApplication
    from gimbal_lab.gui.theme import apply_theme
    from gimbal_lab.gui.main_window import MainWindow
    log_path = setup_logging()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Gimbal Calibration Lab")
    app.setOrganizationName("GimbalLab")
    app.setApplicationVersion(__version__)
    apply_theme(app)
    window = MainWindow(log_path)
    window.resize(width, height)
    if args.project:
        try:
            window.state.load(args.project)
        except (OSError, ValueError) as exc:
            window.show_message(f"无法加载启动项目：{exc}", True)
    original_hook = sys.excepthook
    def exception_hook(kind, value, traceback):
        logging.error("Unhandled application exception", exc_info=(kind, value, traceback))
        window.show_message(f"应用错误：{value}（详见日志）", True)
        original_hook(kind, value, traceback)
    sys.excepthook = exception_hook
    window.show()
    logging.info("App started; Qt platform=%s", app.platformName())
    return app.exec()

