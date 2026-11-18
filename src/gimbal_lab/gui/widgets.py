from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import (
    QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget,
)


COLORS = {"world": "#7d8aa3", "base": "#8a99b1", "yaw": "#6190f2", "pitch": "#9d8de9", "camera": "#36bfc3", "imu": "#efa956", "board": "#8796ab"}


def icon(key: str, size: int = 24) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24, size / 24)
    color = QColor(COLORS.get(key, "#4878ea"))
    painter.setPen(QPen(color, 1.8))
    painter.setBrush(QColor(color.red(), color.green(), color.blue(), 24))
    painter.drawRoundedRect(3, 3, 18, 18, 5, 5)
    if key == "camera":
        painter.drawRoundedRect(6, 8, 9, 8, 2, 2)
        painter.drawPolygon(QPolygonF([QPointF(15, 10), QPointF(19, 8), QPointF(19, 16), QPointF(15, 14)]))
    elif key == "board":
        for x, y in ((7, 7), (12, 12)):
            painter.fillRect(x, y, 5, 5, color)
    elif key in ("yaw", "pitch"):
        painter.drawArc(6, 6, 12, 12, 30 * 16, 290 * 16)
        painter.drawLine(16, 5, 18, 8)
    elif key == "imu":
        painter.drawRect(8, 8, 8, 8)
        painter.drawLine(6, 12, 18, 12)
    else:
        painter.drawLine(8, 16, 8, 7)
        painter.drawLine(8, 16, 17, 16)
        painter.drawLine(8, 16, 16, 8)
    painter.end()
    return QIcon(pix)


def label(text: str, role: str = "", wrap: bool = False) -> QLabel:
    result = QLabel(text)
    result.setObjectName(role)
    result.setWordWrap(wrap)
    return result


def button(text: str, callback=None, primary=False) -> QPushButton:
    result = QPushButton(text)
    if primary:
        result.setObjectName("Primary")
    if callback is not None:
        result.clicked.connect(callback)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    return result


def pending(widget: QWidget, stage: str, text: str) -> QWidget:
    widget.setEnabled(False)
    widget.setToolTip(f"{stage} 待实现：{text}")
    return widget


def panel() -> QFrame:
    result = QFrame()
    result.setObjectName("Panel")
    return result


def scroll(content: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(content)
    return area


def heading(title: str, subtitle: str) -> tuple[QWidget, QHBoxLayout]:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    text = QVBoxLayout()
    text.setSpacing(3)
    text.addWidget(label(title, "Title"))
    text.addWidget(label(subtitle, "Muted"))
    layout.addLayout(text)
    layout.addStretch()
    return row, layout


def spin(value: float, minimum=-100000.0, maximum=100000.0, decimals=1, suffix="") -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setSingleStep(1 if decimals < 3 else 0.01)
    widget.setValue(value)
    widget.setSuffix(suffix)
    widget.setKeyboardTracking(False)
    widget.setMinimumWidth(56)
    return widget


class Collapsible(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 0)
        layout.setSpacing(4)
        self.toggle = QToolButton()
        self.toggle.setObjectName("Fold")
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.body = QWidget()
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 5, 0, 5)
        self.content.setSpacing(9)
        self.body.setVisible(False)
        self.toggle.toggled.connect(self._expand)
        layout.addWidget(self.toggle)
        layout.addWidget(self.body)

    def _expand(self, checked: bool):
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.body.setVisible(checked)


class PathField(QWidget):
    changed = Signal(str)

    def __init__(self, title: str, kind: str, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        if title:
            layout.addWidget(label(title, "Section"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setClearButtonEnabled(True)
        self.browse_button = button("浏览…", self.browse)
        self.browse_button.setMinimumWidth(67)
        row.addWidget(self.edit, 1)
        row.addWidget(self.browse_button)
        layout.addLayout(row)
        self.edit.editingFinished.connect(self._edited)

    def _edited(self):
        value = self.edit.text().strip()
        self.changed.emit(value)
        self.validate_path()

    def set_path(self, value: str):
        self.edit.setText(value)
        self.validate_path()

    def validate_path(self) -> bool:
        text = self.edit.text().strip()
        path = Path(text).expanduser() if text else None
        valid = True
        if path is not None:
            if self.kind in ("input_dir", "output_dir"):
                valid = path.is_dir()
            elif self.kind == "config":
                valid = path.is_file()
            elif self.kind == "yaml":
                valid = path.suffix.lower() in (".yaml", ".yml") and path.parent.is_dir() and not path.is_dir()
        self.edit.setProperty("invalid", not valid)
        self.edit.setToolTip(text if valid else "路径无效：输入目录/文件须存在；输出 YAML 须位于已有目录并使用 .yaml/.yml 后缀")
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)
        return valid

    def browse(self):
        initial = self.edit.text() or str(Path.home())
        if self.kind in ("input_dir", "output_dir"):
            value = QFileDialog.getExistingDirectory(self, self.title or "选择目录", initial)
        elif self.kind == "yaml":
            value, _ = QFileDialog.getSaveFileName(self, "选择结果 YAML 保存位置", initial, "YAML 文件 (*.yaml *.yml)")
            if value and Path(value).suffix.lower() not in (".yaml", ".yml"):
                value += ".yaml"
        else:
            value, _ = QFileDialog.getOpenFileName(self, "选择相机与标定板配置", initial, "配置文件 (*.yaml *.yml *.json);;所有文件 (*)")
        if value:
            self.edit.setText(value)
            self._edited()

