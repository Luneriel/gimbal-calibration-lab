"""Replay uses its own scene and viewport, never the editing AppState."""
from copy import deepcopy

import cv2
import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QSizePolicy, QSlider, QSplitter, QVBoxLayout, QWidget

from gimbal_lab.gui.widgets import button, label
from gimbal_lab.rendering.viewport import SceneViewport


class ImageView(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(160, 130)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("color: #9bb1d1; font-size: 14px; background: #101c2d;")
        self.master = None
        self.zoom = 1.0
        self.pan = QPointF()
        self._drag = None
        self.setToolTip("滚轮缩放 · 拖动平移 · 双击适应窗口；只改变显示，不改变相机参数或导出图片。")

    def show_array(self, array):
        array = np.ascontiguousarray(array)
        height, width = array.shape[:2]
        fmt = QImage.Format.Format_Grayscale8 if array.ndim == 2 else QImage.Format.Format_BGR888
        image = QImage(array.data, width, height, int(array.strides[0]), fmt).copy()
        self.master = QPixmap.fromImage(image)
        self.clear()
        self._fit()

    def show_message(self, text):
        self.master = None
        self.zoom, self.pan = 1.0, QPointF()
        self.clear()
        self.setText(text)

    def _fit(self):
        if self.master is not None:
            scale = self._scale()
            dx = max(0.0, (self.master.width() * scale - self.width()) / 2)
            dy = max(0.0, (self.master.height() * scale - self.height()) / 2)
            self.pan = QPointF(float(np.clip(self.pan.x(), -dx, dx)), float(np.clip(self.pan.y(), -dy, dy)))
        self.setCursor(Qt.CursorShape.OpenHandCursor if self.zoom > 1 else Qt.CursorShape.ArrowCursor)
        self.update()

    def _scale(self):
        return min(self.width() / self.master.width(), self.height() / self.master.height()) * self.zoom

    def fit_image(self):
        self.zoom, self.pan = 1.0, QPointF()
        self._fit()

    def actual_size(self):
        if self.master is not None:
            self.zoom = max(1.0, 1 / min(self.width() / self.master.width(), self.height() / self.master.height()))
            self.pan = QPointF()
            self._fit()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.master is not None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            scale = self._scale()
            size = self.master.size().toSizeF() * scale
            centre = QRectF(self.rect()).center() + self.pan
            painter.drawPixmap(QRectF(centre.x() - size.width() / 2, centre.y() - size.height() / 2,
                                     size.width(), size.height()), self.master, QRectF(self.master.rect()))
            painter.end()

    def wheelEvent(self, event):
        if self.master is None:
            return super().wheelEvent(event)
        previous = self.zoom
        self.zoom = float(np.clip(previous * 1.25 ** (event.angleDelta().y() / 120), 1, 12))
        centre = QRectF(self.rect()).center()
        self.pan = (self.pan + centre - event.position()) * (self.zoom / previous) + event.position() - centre
        self._fit()
        event.accept()

    def mousePressEvent(self, event):
        if self.master is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            self.pan += event.position() - self._drag
            self._drag = event.position()
            self._fit()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag = None
        self._fit()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.fit_image()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class ReplaySceneState(QObject):
    scene_changed = Signal(str)
    selection_changed = Signal(str)

    def __init__(self, dataset):
        super().__init__()
        self.project = deepcopy(dataset.project)
        self.geometry = dataset.engine.solve()
        self.selected = "camera"

    def select(self, key):
        self.selected = key
        self.selection_changed.emit(key)

    def show_item(self, item):
        self.geometry = item.state
        self.project.scene.yaw.angle_deg = item.state.angles_deg.yaw_deg
        self.project.scene.pitch.angle_deg = item.state.angles_deg.pitch_deg
        self.scene_changed.emit("scene:joint")


class ReplayController(QObject):
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dataset = None
        self.state = None
        self.active = False
        self.kind = "valid"
        self.index = 0
        self.item = None

    def attach(self, dataset):
        self.dataset = dataset
        self.state = ReplaySceneState(dataset)
        self.kind = "valid" if dataset.valid_records else "failure"
        self.index = 0
        self.select(0)

    def count(self):
        if self.dataset is None:
            return 0
        return len(self.dataset.valid_records if self.kind == "valid" else self.dataset.failure_records)

    def select(self, index, kind=None):
        if kind is not None:
            self.kind = kind
        if self.count() == 0:
            self.item = None
            self.active = True
            self.changed.emit(None)
            return
        self.index = max(0, min(index, self.count() - 1))
        item = self.dataset.frame(self.index) if self.kind == "valid" else self.dataset.failure(self.index)
        self.item = item
        self.active = True
        self.state.show_item(item)
        self.changed.emit(item)


class ReplayDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("实验 3D 回放 · 独立场景快照")
        self.resize(1200, 760)
        self.setMinimumSize(900, 600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.viewport = SceneViewport(controller.state, overview_angle_deg=40)
        split.addWidget(self.viewport)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.image = ImageView()
        right_layout.addWidget(self.image, 1)
        self.info = label("", "Notice", True)
        right_layout.addWidget(self.info)
        split.addWidget(right)
        split.setSizes([720, 430])
        layout.addWidget(split, 1)
        row = QHBoxLayout()
        row.addWidget(button("上一帧", lambda: controller.select(controller.index - 1)))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(controller.select)
        row.addWidget(self.slider, 1)
        row.addWidget(button("下一帧", lambda: controller.select(controller.index + 1)))
        layout.addLayout(row)
        layout.addWidget(label("此视图只读取实验快照；当前正在编辑的场景保持独立。", "Muted"))
        controller.changed.connect(self.update_item)
        self.update_item(controller.item)

    def update_item(self, item):
        with QSignalBlocker(self.slider):
            self.slider.setRange(0, max(0, self.controller.count() - 1))
            self.slider.setValue(self.controller.index)
        if item is None:
            self.image.show_message("此实验没有可回放记录")
            return
        if item.image is None:
            self.image.show_message("失败姿态未导出 JPG\n" + item.record["reason_text"])
        else:
            self.image.show_array(item.image)
        angles = item.state.angles_deg
        q = "未导出 TXT" if item.quaternion is None else "wxyz: " + " ".join(f"{v:+.7f}" for v in item.quaternion)
        self.info.setText(f"计划 #{item.record['plan_id']} · 导出 #{item.record['export_id'] or '—'}\nYaw {angles.yaw_deg:+.2f}°  Pitch {angles.pitch_deg:+.2f}°\n{q}\n{item.record['reason_text'] or '实际 JPG/TXT，几何与视觉检测有效'}")

    def closeEvent(self, event):
        self.viewport.shutdown()
        event.accept()
