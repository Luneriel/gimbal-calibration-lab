from PySide6.QtGui import QColor, QFont, QPalette
from pathlib import Path


def apply_theme(app):
    app.setStyle("Fusion")
    app.setFont(QFont("Noto Sans CJK SC", 10))
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, "#18212e"), (QPalette.ColorRole.WindowText, "#dce5f2"),
        (QPalette.ColorRole.Base, "#111a27"), (QPalette.ColorRole.AlternateBase, "#1d2939"),
        (QPalette.ColorRole.Text, "#dce5f2"), (QPalette.ColorRole.Button, "#202d3e"),
        (QPalette.ColorRole.ButtonText, "#dce5f2"), (QPalette.ColorRole.Highlight, "#293e60"),
        (QPalette.ColorRole.HighlightedText, "#a9c8ff"), (QPalette.ColorRole.Light, "#35465d"),
        (QPalette.ColorRole.Midlight, "#2b3b51"), (QPalette.ColorRole.Dark, "#0d1420"),
        (QPalette.ColorRole.Mid, "#2e3e54"), (QPalette.ColorRole.Shadow, "#080e17"),
        (QPalette.ColorRole.PlaceholderText, "#7c8ea8"),
        (QPalette.ColorRole.ToolTipBase, "#293b53"), (QPalette.ColorRole.ToolTipText, "#e4edf9"),
        (QPalette.ColorRole.Link, "#8bb5ff"),
    ):
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#71839d"))
    app.setPalette(palette)
    app.setStyleSheet("""
        QWidget { color: #dce5f2; font-size: 12px; }
        QMainWindow, QDialog { background: #101722; }
        QFrame#Header { background: #151e2b; border-bottom: 1px solid #2b394d; }
        QFrame#Navigation { background: #151e2b; border-bottom: 1px solid #2b394d; }
        QFrame#Panel, QFrame#Card { background: #18212e; border: 1px solid #2b394d; border-radius: 9px; }
        QFrame#PanelHeader { background: #1b2737; border-bottom: 1px solid #2b394d; }
        QLabel { background: transparent; }
        QLabel#Brand { font-size: 19px; font-weight: 700; color: #edf3fd; }
        QLabel#Title { font-size: 22px; font-weight: 700; color: #edf3fd; }
        QLabel#Section { font-size: 13px; font-weight: 700; color: #dce6f5; }
        QLabel#Muted { color: #94a5be; font-size: 11px; }
        QLabel#Eyebrow { color: #94a5be; font-size: 10px; font-weight: 600; }
        QLabel#Feedback { color: #9db8dc; font-size: 11px; }
        QLabel#Feedback[has_error="true"] { color: #ff9b9b; }
        QLabel#Badge { color: #e3bf7f; background: #30291f; border: 1px solid #5d4a30; border-radius: 5px; padding: 4px 9px; font-size: 11px; }
        QLabel#Notice { background: #1d2c44; color: #abc5ec; border: 1px solid #354c70; border-radius: 6px; padding: 9px; font-size: 11px; }
        QLabel#Warning { background: #30291f; color: #e3bf7f; border: 1px solid #5d4a30; border-radius: 6px; padding: 8px; font-size: 11px; }
        QLabel#Metric { font-size: 24px; font-weight: 600; color: #a6bbd8; }
        QPushButton, QToolButton { background: #202d3e; border: 1px solid #35465e; border-radius: 6px; padding: 7px 13px; min-height: 16px; }
        QPushButton:hover, QToolButton:hover { border-color: #6487bc; background: #293c56; }
        QPushButton:pressed, QToolButton:pressed { background: #314b6c; }
        QPushButton:focus, QToolButton:focus { border-color: #80abff; }
        QPushButton:disabled, QToolButton:disabled { background: #1a2636; color: #7e91ad; border-color: #2b3a50; }
        QPushButton#Primary { background: #4277e6; color: white; border-color: #568af7; font-weight: 600; }
        QPushButton#Primary:hover { background: #5488f4; }
        QPushButton#Primary:disabled { background: #223654; border-color: #344e76; color: #8ca7cf; }
        QPushButton#Nav { border: none; border-radius: 6px; padding: 9px 19px; font-size: 13px; color: #a1b0c8; }
        QPushButton#Nav:checked { color: #a9c8ff; background: #293e60; font-weight: 700; }
        QPushButton#Nav:hover { background: #22334b; }
        QToolButton#Fold { border: none; text-align: left; padding: 7px 0; font-size: 12px; font-weight: 600; color: #9eb6d7; }
        QToolButton#Fold:hover { background: transparent; color: #a9c8ff; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #111a27; border: 1px solid #34445b; border-radius: 5px; padding: 5px 7px; min-height: 20px; selection-background-color: #354e78; selection-color: #edf3fd; color: #dce6f5; }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #80abff; background: #162235; }
        QLineEdit[invalid="true"] { border-color: #dc7b89; background: #33232e; }
        QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { color: #71839d; background: #1a2332; }
        QAbstractSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 16px; border-left: 1px solid #34445b; border-bottom: 1px solid #34445b; border-top-right-radius: 4px; background: #202d3e; }
        QAbstractSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 16px; border-left: 1px solid #34445b; border-bottom-right-radius: 4px; background: #202d3e; }
        QAbstractSpinBox::up-arrow { image: url(ASSET_DIR/chevron-up.svg); width: 9px; height: 9px; }
        QAbstractSpinBox::down-arrow { image: url(ASSET_DIR/chevron-down.svg); width: 9px; height: 9px; }
        QComboBox::drop-down { border: none; width: 22px; }
        QComboBox::down-arrow { image: url(ASSET_DIR/chevron-down.svg); width: 12px; height: 12px; }
        QComboBox QAbstractItemView { background: #1c293b; border: 1px solid #3d516e; padding: 4px; selection-background-color: #293e60; selection-color: #a9c8ff; }
        QCheckBox { spacing: 7px; }
        QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #526784; border-radius: 3px; background: #111a27; }
        QCheckBox::indicator:checked { background: #588bf5; border-color: #588bf5; image: url(ASSET_DIR/check.svg); }
        QCheckBox:disabled { color: #71839d; }
        QTreeWidget { background: #18212e; border: none; outline: 0; padding: 6px; }
        QTreeWidget::item { min-height: 35px; padding: 0 4px; border-radius: 5px; }
        QTreeWidget::item:selected { background: #293e60; color: #a9c8ff; }
        QTreeWidget::item:hover:!selected { background: #22334b; }
        QTreeWidget::branch { background: transparent; }
        QTreeWidget::branch:has-children:closed { image: url(ASSET_DIR/chevron-right.svg); }
        QTreeWidget::branch:has-children:open { image: url(ASSET_DIR/chevron-down.svg); }
        QScrollArea { border: none; background: transparent; }
        QScrollBar:vertical { width: 7px; background: transparent; margin: 3px 0; }
        QScrollBar::handle:vertical { background: #3a4d68; min-height: 30px; border-radius: 3px; }
        QScrollBar::handle:vertical:hover { background: #59769e; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        QSlider::groove:horizontal { height: 4px; border-radius: 2px; background: #33445f; }
        QSlider::sub-page:horizontal { background: #739ef5; border-radius: 2px; }
        QSlider::handle:horizontal { background: #8cb4ff; border: 3px solid #263d60; width: 12px; height: 12px; margin: -7px 0; border-radius: 9px; }
        QSlider::handle:horizontal:disabled { background: #52647f; border-color: #27374e; }
        QSlider::sub-page:horizontal:disabled { background: #33445f; }
        QSplitter::handle { background: transparent; }
        QSplitter::handle:hover { background: #344e75; }
        QStatusBar { background: #151e2b; border-top: 1px solid #2b394d; }
        QStatusBar::item { border: none; }
        QTabWidget::pane { border: 1px solid #2b394d; background: #18212e; border-radius: 6px; }
        QTabBar::tab { padding: 9px 19px; color: #94a5be; background: transparent; border-bottom: 2px solid transparent; }
        QTabBar::tab:selected { color: #a9c8ff; border-bottom: 2px solid #80abff; }
        QPlainTextEdit { background: #111a27; color: #c3d3eb; border: none; padding: 12px; font-family: monospace; font-size: 11px; }
        QMenu { background: #1c293b; border: 1px solid #3d516e; padding: 5px; }
        QMenu::item { padding: 8px 25px 8px 12px; border-radius: 4px; }
        QMenu::item:selected { background: #293e60; color: #a9c8ff; }
        QProgressBar { background: #2b3b54; border: none; border-radius: 3px; min-height: 6px; max-height: 6px; }
        QProgressBar::chunk { background: #739ef5; border-radius: 3px; }
        QToolTip { background: #293b53; color: #e4edf9; border: 1px solid #486184; padding: 7px; }
    """.replace("ASSET_DIR", str(Path(__file__).resolve().parents[1] / "assets")))

