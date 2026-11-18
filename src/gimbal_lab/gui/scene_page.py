from PySide6.QtCore import Qt, QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QMessageBox, QSlider,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from gimbal_lab.domain.models import NAMES
from gimbal_lab.gui.properties import PropertyEditor
from gimbal_lab.gui.widgets import button, icon, label, panel, spin
from gimbal_lab.rendering.viewport import SceneViewport


class JointControl(QWidget):
    def __init__(self, state, key):
        super().__init__()
        self.state = state
        self.key = key
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(label(key.capitalize(), "Section"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName(f"{key}_slider")
        self.slider.setAccessibleName(key + " 关节角滑块")
        self.slider.setMinimumWidth(90)
        row.addWidget(self.slider, 1)
        self.value = spin(0, -180, 180, 1, "°")
        self.value.setObjectName(f"{key}_value")
        self.value.setAccessibleName(key + " 精确角度")
        self.value.setFixedWidth(88)
        row.addWidget(self.value)
        self.slider.valueChanged.connect(lambda value: state.set_joint(key, value / 10))
        self.value.valueChanged.connect(lambda value: state.set_joint(key, value))
        state.scene_changed.connect(self.sync)
        self.sync()

    def sync(self, *_):
        joint = getattr(self.state.project.scene, self.key)
        with QSignalBlocker(self.slider), QSignalBlocker(self.value):
            self.slider.setRange(round(joint.limits_deg[0] * 10), round(joint.limits_deg[1] * 10))
            self.value.setRange(*joint.limits_deg)
            self.slider.setValue(round(joint.angle_deg * 10))
            self.value.setValue(joint.angle_deg)


class ScenePage(QWidget):
    preview_requested = Signal()

    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)
        title = QWidget()
        title_layout = QHBoxLayout(title)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.addStretch()
        title_layout.addWidget(label("场景预设", "Muted"))
        self.presets = QComboBox()
        self.presets.setObjectName("scene_presets")
        self.presets.addItems(["理想双轴云台", "Pitch 轴心偏移", "相机安装偏置", "采样示例（宽视场）", "自定义场景"])
        self.presets.setMinimumWidth(175)
        self.presets.currentTextChanged.connect(self.choose_preset)
        title_layout.addWidget(self.presets)
        layout.addWidget(title)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(9)
        self.splitter.setChildrenCollapsible(False)
        tree_panel = panel()
        tree_panel.setMinimumWidth(175)
        tree_layout = QVBoxLayout(tree_panel)
        tree_layout.setContentsMargins(0, 0, 0, 12)
        tree_layout.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(14, 12, 14, 5)
        head.addWidget(label("场景对象", "Section"))
        head.addStretch()
        head.addWidget(label("7 个", "Muted"))
        tree_layout.addLayout(head)
        self.tree = QTreeWidget()
        self.tree.setObjectName("scene_tree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(15)
        self.tree.setMinimumWidth(165)
        self.tree.setColumnCount(1)
        self.tree.currentItemChanged.connect(self.tree_selected)
        tree_layout.addWidget(self.tree, 1)
        explain = label("对象随父节点运动\n标定板固定于世界", "Muted", True)
        explain.setContentsMargins(14, 0, 10, 4)
        tree_layout.addWidget(explain)
        self.splitter.addWidget(tree_panel)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)
        self.viewport = SceneViewport(state)
        center_layout.addWidget(self.viewport, 1)
        tools = QHBoxLayout()
        tools.setContentsMargins(3, 0, 3, 0)
        self.axes_check = QCheckBox("坐标系")
        self.axes_check.setChecked(True)
        self.axes_check.toggled.connect(self.viewport.set_axes)
        self.frustum_check = QCheckBox("相机视锥")
        self.frustum_check.setChecked(True)
        self.frustum_check.toggled.connect(self.viewport.set_frustum)
        tools.addWidget(self.axes_check)
        tools.addWidget(self.frustum_check)
        tools.addStretch()
        self.gimbal_status = label("", "Muted")
        tools.addWidget(self.gimbal_status)
        center_layout.addLayout(tools)
        self.splitter.addWidget(center)
        self.properties = PropertyEditor(state)
        self.splitter.addWidget(self.properties)
        self.splitter.setSizes([205, 940, 300])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        layout.addWidget(self.splitter, 1)
        controls = panel()
        controls.setObjectName("Card")
        row = QHBoxLayout(controls)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(22)
        self.yaw_control = JointControl(state, "yaw")
        self.pitch_control = JointControl(state, "pitch")
        row.addWidget(self.yaw_control, 1)
        row.addWidget(self.pitch_control, 1)
        row.addWidget(button("归零", self.reset_joints))
        row.addWidget(button("相机预览  →", self.preview_requested.emit))
        layout.addWidget(controls)
        state.scene_changed.connect(self.scene_changed)
        state.selection_changed.connect(self.sync_selection)
        self.rebuild_tree()
        self.update_gimbal_status()

    def scene_changed(self, reason):
        self.update_gimbal_status()
        with QSignalBlocker(self.presets):
            self.presets.setCurrentText(self.state.project.scene.preset)
        if reason in ("scene:mount", "scene:reset"):
            self.rebuild_tree()

    def update_gimbal_status(self):
        names = {"pitch": "Pitch", "yaw": "Yaw", "base": "Base"}
        status = self.state.geometry.fixed_extrinsics
        self.gimbal_status.setText(f"G → {names[self.state.project.scene.gimbal.parent]} · {'固定外参' if status.is_fixed else '逐帧外参'}")
        self.gimbal_status.setToolTip(status.message + " 在世界坐标系属性的高级设置中配置 G。")

    def rebuild_tree(self):
        with QSignalBlocker(self.tree):
            self.tree.clear()
            self.items = {}
            parents = {"world": None, "base": "world", "yaw": "base", "pitch": "yaw", "camera": self.state.project.scene.camera.parent,
                       "imu": self.state.project.scene.imu.parent, "board": "world"}
            for key, parent in parents.items():
                item = QTreeWidgetItem([NAMES[key]])
                item.setData(0, Qt.ItemDataRole.UserRole, key)
                item.setIcon(0, icon(key))
                if parent is None:
                    self.tree.addTopLevelItem(item)
                else:
                    self.items[parent].addChild(item)
                self.items[key] = item
            self.tree.expandAll()
            self.tree.setCurrentItem(self.items[self.state.selected])

    def tree_selected(self, current, previous):
        if current:
            self.state.select(current.data(0, Qt.ItemDataRole.UserRole))

    def sync_selection(self, key):
        with QSignalBlocker(self.tree):
            self.tree.setCurrentItem(self.items[key])

    def reset_joints(self):
        def update(project):
            for key in ("yaw", "pitch"):
                joint = getattr(project.scene, key)
                joint.angle_deg = min(joint.limits_deg[1], max(joint.limits_deg[0], 0.0))
        self.state.edit(update, "scene:joint")

    def choose_preset(self, name):
        if name == self.state.project.scene.preset:
            return
        if name == "自定义场景":
            self.state.edit(lambda p: setattr(p.scene, "preset", name), "scene:property")
            return
        if self.state.dirty:
            answer = QMessageBox.question(self, "切换场景预设", "将替换当前场景中的机械与传感器参数。采样设置和路径将保留。是否继续？")
            if answer != QMessageBox.StandardButton.Yes:
                with QSignalBlocker(self.presets):
                    self.presets.setCurrentText(self.state.project.scene.preset)
                return
        self.state.apply_preset(name)

