from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout, QWidget, QSpinBox

from gimbal_lab.domain.models import MOUNTS, NAMES
from gimbal_lab.domain.rigid import euler_zyx_deg_from_rotation, rotation_from_euler_zyx_deg
from gimbal_lab.gui.widgets import Collapsible, icon, label, panel, scroll, spin


class PropertyEditor(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setMinimumWidth(270)
        self.bindings = []
        self.warnings = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = panel()
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QWidget()
        head = QHBoxLayout(header)
        head.setContentsMargins(16, 12, 16, 8)
        head.addWidget(label("对象属性", "Section"))
        head.addStretch()
        head.addWidget(label("mm / °", "Muted"))
        layout.addWidget(header)
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(16, 6, 16, 14)
        self.body.setSpacing(13)
        self.area = scroll(self.content)
        layout.addWidget(self.area, 1)
        outer.addWidget(self.frame)
        state.selection_changed.connect(self.rebuild)
        state.scene_changed.connect(self.scene_changed)
        state.project_changed.connect(self.rebuild)
        self.rebuild()

    def clear(self):
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.bindings.clear()
        self.warnings.clear()

    def rebuild(self, *_):
        self.clear()
        key = self.state.selected
        title = QWidget()
        row = QHBoxLayout(title)
        row.setContentsMargins(0, 5, 0, 4)
        image = label("")
        image.setPixmap(icon(key).pixmap(30, 30))
        row.addWidget(image)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(NAMES[key], "Section"))
        desc = {"world": "WORLD · 固定参考", "base": "BASE · 固定部件", "yaw": "JOINT 01 · 父节点：底座", "pitch": "JOINT 02 · 父节点：Yaw", "camera": "CAMERA · OpenCV 光学坐标系", "imu": "IMU · 本体坐标系", "board": "BOARD · 固定于世界"}
        text.addWidget(label(desc[key], "Muted"))
        row.addLayout(text, 1)
        self.body.addWidget(title)
        if key == "world":
            self.body.addWidget(label("右手世界坐标系", "Section"))
            self.body.addWidget(label("X 向前 · Y 向左 · Z 向上\n原点固定为 (0, 0, 0) mm。", "Muted", True))
            self.body.addWidget(label("T_A_B 将 B 中坐标转换到 A。\n内部长度统一为 mm。", "Notice", True))
            self.body.addWidget(label("B = 固定底座 · T = 标定板\nA 与 W 原点重合，方向可配置。", "Muted", True))
            self.gimbal_advanced = Collapsible("Gimbal 参考系 G")
            self.gimbal_advanced.setObjectName("gimbal_advanced")
            self.add_combo("固定于", lambda p: p.scene.gimbal.parent,
                           lambda p, v: setattr(p.scene.gimbal, "parent", v), self.gimbal_advanced.content,
                           [(NAMES[m], m) for m in MOUNTS], name="gimbal_parent")
            self.add_pose(lambda p: p.scene.gimbal.installation, self.gimbal_advanced.content, prefix="gimbal")
            model = label("", "Notice", True)
            self.gimbal_advanced.content.addWidget(model)
            self.warnings.append(lambda: model.setText(self.state.geometry.fixed_extrinsics.message))
            self.body.addWidget(self.gimbal_advanced)
        elif key == "base":
            self.add_pose(lambda p: p.scene.base, self.body)
        elif key in ("yaw", "pitch"):
            get_joint = lambda p, k=key: getattr(p.scene, k)
            self.add_scalar("当前关节角 · °", lambda p: get_joint(p).angle_deg,
                            lambda p, v: setattr(get_joint(p), "angle_deg", v), self.body,
                            -180, 180, reason="scene:joint", name=f"property_{key}_angle")
            self.add_vector("旋转轴心 · 父坐标系 / mm", lambda p: get_joint(p).installation.position_mm, self.body, name="axis_origin")
            self.add_vector("旋转轴方向 · 安装坐标系", lambda p: get_joint(p).axis, self.body,
                            minimum=-100000, maximum=100000, decimals=3, name="axis_direction")
            advanced = Collapsible("安装姿态与关节限位")
            self.add_vector("安装角 · °", lambda p: get_joint(p).installation.euler_zyx_deg, advanced.content,
                            labels=("Yaw", "Pitch", "Roll"), minimum=-360, maximum=360, name="joint_install")
            self.add_vector("可用角度范围 · °", lambda p: get_joint(p).limits_deg, advanced.content,
                            labels=("下限", "上限"), minimum=-180, maximum=180, name="joint_limits")
            zero = Collapsible("子部件零位安装")
            zero.setObjectName(f"{key}_zero_advanced")
            self.add_pose(lambda p: get_joint(p).child_zero, zero.content, prefix=f"{key}_zero")
            zero.content.addWidget(label("T_J_L_zero 在关节转动后应用；轴心由上方安装位姿单独定义。", "Muted", True))
            advanced.content.addWidget(zero)
            self.body.addWidget(advanced)
            self.body.addWidget(label("轴方向在核心计算时归一化。轴心偏移在关节转动前应用。", "Muted", True))
        elif key in ("camera", "imu"):
            get_sensor = lambda p, k=key: getattr(p.scene, k)
            self.add_combo("挂载对象", lambda p: get_sensor(p).parent,
                           lambda p, v: setattr(get_sensor(p), "parent", v), self.body,
                           [(NAMES[m], m) for m in MOUNTS], reason="scene:mount")
            self.add_pose(lambda p: get_sensor(p).installation, self.body)
            warning = label("", "Warning", True)
            self.body.addWidget(warning)
            def update_warning():
                if key == "imu":
                    message = self.state.geometry.imu_limitation_message
                else:
                    status = self.state.geometry.fixed_extrinsics
                    message = status.message if not status.is_fixed else ""
                warning.setText(message)
                warning.setVisible(bool(message))
            self.warnings.append(update_warning)
            if key == "camera":
                self.add_pair_int("图像分辨率 · px", ("宽", "高"), ("width", "height"), self.body, 64, 8192)
                advanced = Collapsible("相机内参与畸变")
                for attribute, text in (("fx", "fx · px"), ("fy", "fy · px"), ("cx", "cx · px"), ("cy", "cy · px")):
                    self.add_scalar(text, lambda p, a=attribute: getattr(p.scene.camera, a),
                                    lambda p, v, a=attribute: setattr(p.scene.camera, a, v), advanced.content, 0, 100000)
                advanced.content.addWidget(label("当前成像只支持零畸变；非零畸变配置不能生成图像。", "Muted", True))
                for index, text in enumerate(("k1", "k2", "p1", "p2", "k3")):
                    self.add_scalar(text, lambda p, i=index: p.scene.camera.distortion[i],
                                    lambda p, v, i=index: p.scene.camera.distortion.__setitem__(i, v), advanced.content, -10, 10, 5)
                self.body.addWidget(advanced)
                query = Collapsible("真实几何位姿")
                pose_text = label("", "Notice", True)
                query.content.addWidget(pose_text)
                def update_camera_query():
                    world_position = self.state.geometry.T_W_C[:3, 3]
                    gimbal_position = self.state.geometry.T_G_C[:3, 3]
                    fmt = lambda values: ", ".join(f"{value:.3f}" for value in values)
                    pose_text.setText(f"t_W_C · mm\n{fmt(world_position)}\nt_G_C · mm\n{fmt(gimbal_position)}\n" + self.state.geometry.fixed_extrinsics.message)
                self.warnings.append(update_camera_query)
                self.body.addWidget(query)
            else:
                self.body.addWidget(label("姿态方向：R_A_I（I → A）\nR_A_I = R_A_W · R_W_I\n四元数顺序：w x y z · Hamilton", "Notice", True))
                self.imu_advanced = Collapsible("姿态参考与四元数")
                self.imu_advanced.setObjectName("imu_advanced")
                self.add_reference_rotation(self.imu_advanced.content)
                quaternion = label("", "Notice", True)
                quaternion.setObjectName("imu_quaternion")
                quaternion.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.imu_advanced.content.addWidget(quaternion)
                def update_quaternion():
                    w, x, y, z = self.state.geometry.quaternion_wxyz
                    quaternion.setText(f"q_A_I · w x y z\nw {w:+.6f}    x {x:+.6f}\ny {y:+.6f}    z {z:+.6f}")
                self.warnings.append(update_quaternion)
                self.imu_advanced.content.addWidget(label("R_A_W 是 W → A 的旋转；A 与 W 共原点。欧拉角为矩阵的显示表示，奇异点采用 Roll=0 的等价解。", "Muted", True))
                self.body.addWidget(self.imu_advanced)
        elif key == "board":
            self.body.addWidget(label("类型：棋盘格 / chessboard", "Muted"))
            self.add_pair_int("内角点数量", ("列", "行"), ("columns", "rows"), self.body, 2, 30, target="board")
            self.add_scalar("角点间距 · mm", lambda p: p.scene.board.spacing_mm,
                            lambda p, v: setattr(p.scene.board, "spacing_mm", v), self.body, 1, 500)
            self.add_pose(lambda p: p.scene.board.installation, self.body)
            self.body.addWidget(label("原点位于第一内角点。列方向为 +X_T，行方向为 +Y_T；角点按行编号，列索引先变化。", "Notice", True))
        if key != "world":
            self.body.addWidget(label("安装角顺序 Yaw / Pitch / Roll\nR = Rz(Y) · Ry(P) · Rx(R)", "Muted", True))
        self.body.addStretch()
        self.refresh()

    def scene_changed(self, reason):
        if reason == "scene:reset":
            self.rebuild()
        else:
            self.refresh()

    def refresh(self):
        for widget, getter in self.bindings:
            with QSignalBlocker(widget):
                value = getter(self.state.project)
                if isinstance(widget, QComboBox):
                    widget.setCurrentIndex(widget.findData(value))
                else:
                    widget.setValue(value)
        for update in self.warnings:
            update()

    def commit(self, mutator, reason="scene:property"):
        if not self.state.edit(mutator, reason):
            self.refresh()

    def add_pose(self, getter, layout, prefix=""):
        self.add_vector("安装位置 · mm", lambda p: getter(p).position_mm, layout, name=f"{prefix}_position" if prefix else "position")
        self.add_vector("安装姿态 · °", lambda p: getter(p).euler_zyx_deg, layout,
                        labels=("Yaw", "Pitch", "Roll"), minimum=-360, maximum=360, name=f"{prefix}_euler" if prefix else "euler")

    def add_reference_rotation(self, layout):
        layout.addWidget(label("R_A_W 的 Yaw / Pitch / Roll · °", "Section"))
        row = QHBoxLayout()
        row.setSpacing(5)
        def get_angles(project):
            return euler_zyx_deg_from_rotation(project.scene.imu.reference_rotation_aw)
        def set_angle(project, index, value):
            angles = get_angles(project)
            angles[index] = value
            project.scene.imu.reference_rotation_aw = rotation_from_euler_zyx_deg(angles).tolist()
        for index, text in enumerate(("Yaw", "Pitch", "Roll")):
            column = QVBoxLayout()
            column.addWidget(label(text, "Muted"))
            widget = spin(get_angles(self.state.project)[index], -360, 360, 2)
            widget.setObjectName(f"imu_reference_{index}")
            widget.valueChanged.connect(lambda value, i=index: self.commit(lambda p: set_angle(p, i, value)))
            self.bindings.append((widget, lambda p, i=index: get_angles(p)[i]))
            column.addWidget(widget)
            row.addLayout(column, 1)
        layout.addLayout(row)

    def add_vector(self, title, getter, layout, labels=("X", "Y", "Z"), minimum=-100000, maximum=100000, decimals=1, name="vector"):
        group = QWidget()
        stack = QVBoxLayout(group)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(5)
        stack.addWidget(label(title, "Section"))
        row = QHBoxLayout()
        row.setSpacing(5)
        for index, text in enumerate(labels):
            cell = QVBoxLayout()
            cell.setSpacing(3)
            cell.addWidget(label(text, "Muted"))
            widget = spin(getter(self.state.project)[index], minimum, maximum, decimals)
            widget.setObjectName(f"{name}_{index}")
            widget.setAccessibleName(title + " " + text)
            widget.valueChanged.connect(lambda value, i=index: self.commit(lambda p: getter(p).__setitem__(i, value)))
            self.bindings.append((widget, lambda p, i=index: getter(p)[i]))
            cell.addWidget(widget)
            row.addLayout(cell, 1)
        stack.addLayout(row)
        layout.addWidget(group)

    def add_scalar(self, title, getter, setter, layout, minimum=-100000, maximum=100000, decimals=1, reason="scene:property", name=""):
        group = QWidget()
        stack = QVBoxLayout(group)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(5)
        stack.addWidget(label(title, "Section"))
        widget = spin(getter(self.state.project), minimum, maximum, decimals)
        widget.setObjectName(name)
        widget.setAccessibleName(title)
        widget.valueChanged.connect(lambda value: self.commit(lambda p: setter(p, value), reason))
        self.bindings.append((widget, getter))
        stack.addWidget(widget)
        layout.addWidget(group)

    def add_combo(self, title, getter, setter, layout, choices, reason="scene:property", name="mount_selector"):
        layout.addWidget(label(title, "Section"))
        widget = QComboBox()
        widget.setObjectName(name)
        for text, data in choices:
            widget.addItem(text, data)
        widget.setCurrentIndex(widget.findData(getter(self.state.project)))
        widget.currentIndexChanged.connect(lambda _: self.commit(lambda p: setter(p, widget.currentData()), reason))
        self.bindings.append((widget, getter))
        layout.addWidget(widget)

    def add_pair_int(self, title, labels, attributes, layout, minimum, maximum, target="camera"):
        layout.addWidget(label(title, "Section"))
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(7)
        for text, attr in zip(labels, attributes):
            row.addWidget(label(text, "Muted"))
            widget = QSpinBox()
            widget.setRange(minimum, maximum)
            widget.setKeyboardTracking(False)
            widget.setValue(getattr(getattr(self.state.project.scene, target), attr))
            widget.setAccessibleName(title + text)
            widget.valueChanged.connect(lambda value, a=attr: self.commit(lambda p: setattr(getattr(p.scene, target), a, value)))
            self.bindings.append((widget, lambda p, a=attr: getattr(getattr(p.scene, target), a)))
            row.addWidget(widget, 1)
        layout.addWidget(row_widget)

