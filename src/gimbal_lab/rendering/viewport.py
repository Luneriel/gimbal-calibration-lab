from __future__ import annotations

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from vtkmodules.vtkRenderingCore import vtkPropPicker

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout

from gimbal_lab.domain.models import NAMES
from gimbal_lab.gui.widgets import button, label


class SceneViewport(QFrame):
    def __init__(self, state, parent=None, *, overview_angle_deg=25):
        super().__init__(parent)
        self.state = state
        self.overview_angle_deg = overview_angle_deg
        self.setObjectName("SceneView")
        self.setMinimumSize(360, 260)
        self.setStyleSheet("QFrame#SceneView { background: #101e31; border: 1px solid #24374e; border-radius: 9px; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(12, 7, 12, 7)
        header.addStretch()
        for text, mode in (("总览", "overview"), ("正视", "front"), ("俯视", "top")):
            control = button(text, lambda checked=False, m=mode: self.set_view(m))
            control.setStyleSheet("QPushButton { background: #1d3049; color: #b8cbe9; border: 1px solid #314763; padding: 3px 9px; font-size: 11px; } QPushButton:hover { background: #2a4363; }")
            header.addWidget(control)
        layout.addLayout(header)
        self.plotter = QtInteractor(self, auto_update=False, multi_samples=4, line_smoothing=True)
        self.plotter.setMinimumSize(100, 180)
        self.plotter.set_background("#13243a", top="#0d192b")
        self.plotter.camera.up = (0, 0, 1)
        self.plotter.enable_trackball_style()
        self.plotter.interactor.installEventFilter(self)
        layout.addWidget(self.plotter.interactor, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(15, 6, 15, 9)
        self.selection_label = label("")
        self.selection_label.setStyleSheet("color: #8fa9cf; font-size: 10px;")
        footer.addWidget(self.selection_label)
        footer.addStretch()
        help_text = label("拖动旋转  ·  Shift 平移  ·  滚轮缩放")
        help_text.setStyleSheet("color: #7d96b9; font-size: 10px;")
        footer.addWidget(help_text)
        layout.addLayout(footer)
        self.bindings = []
        self.object_actors = {}
        self.actor_objects = {}
        self.axes_actors = []
        self.frustum_actors = []
        self.axes_visible = True
        self.frustum_visible = True
        self._press = None
        self._pending_reason = None
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._flush_scene)
        self.build_scene()
        state.scene_changed.connect(self.queue_scene)
        state.selection_changed.connect(self.highlight)
        QTimer.singleShot(200, lambda: self.set_view("overview"))

    def _add(self, mesh, color, frame="world", obj=None, **kwargs):
        actor = self.plotter.add_mesh(
            mesh, color=color, reset_camera=False, render=False, show_scalar_bar=False,
            pickable=obj is not None, smooth_shading=kwargs.pop("smooth_shading", True),
            ambient=0.27, specular=0.32, specular_power=30, **kwargs,
        )
        self.bindings.append((actor, frame))
        if obj:
            self.object_actors.setdefault(obj, []).append(actor)
            self.actor_objects[actor.GetAddressAsString("")] = obj
        return actor

    def build_scene(self):
        previous_camera = self.plotter.camera_position if self.bindings else None
        self.plotter.clear()
        self.bindings.clear()
        self.object_actors.clear()
        self.actor_objects.clear()
        self.axes_actors.clear()
        self.frustum_actors.clear()
        scene = self.state.project.scene
        geometry = self.state.geometry
        # Floor is a world reference, not a selectable or moving component.
        self._add(pv.Plane(center=(430, 0, -3), direction=(0, 0, 1), i_size=2000, j_size=1300), "#192e46", lighting=False)
        for x in range(-500, 1501, 100):
            self._add(pv.Line((x, -650, -2), (x, 650, -2)), "#2a405a", line_width=1, lighting=False)
        for y in range(-600, 601, 100):
            self._add(pv.Line((-500, y, -2), (1500, y, -2)), "#2a405a", line_width=1, lighting=False)
        # Fixed plate and yaw motor. All dimensions here are mm.
        self._add(pv.Cube(center=(0, 0, 13), x_length=190, y_length=210, z_length=26), "#72849b", "base", "base")
        self._add(pv.Cylinder(center=(0, 0, 55), direction=(0, 0, 1), radius=49, height=58, resolution=48), "#445e7c", "base", "base")
        for x in (-75, 75):
            for y in (-85, 85):
                self._add(pv.Cylinder(center=(x, y, 28), direction=(0, 0, 1), radius=5, height=4), "#b0bfd0", "base", "base")
        # Yaw yoke, rotating in the yaw frame.
        yaw_axis = geometry.joint_axes_local["yaw"]
        self._add(pv.Cylinder(center=yaw_axis * 4, direction=yaw_axis, radius=54, height=18, resolution=48), "#6591de", "yaw_moving", "yaw")
        self._add(pv.Cube(center=(0, 0, 22), x_length=65, y_length=212, z_length=22), "#537cc4", "yaw", "yaw")
        for side in (-1, 1):
            # Supports are a visual schematic; pivot positions follow the actual installation.
            end = (geometry.transform("yaw", "pitch_home") @ np.r_[geometry.joint_axes_local["pitch"] * side * 96, 1])[:3]
            start = np.array([0, side * 95, 25])
            self._add(pv.Line(start, end).tube(radius=11, n_sides=8), "#759be1", "yaw", "yaw")
        self._add(pv.Cube(center=(0, 0, 0), x_length=58, y_length=180, z_length=32), "#887acb", "pitch", "pitch")
        for side in (-1, 1):
            direction = geometry.joint_axes_local["pitch"]
            center = direction * side * 96
            self._add(pv.Cylinder(center=center, direction=direction, radius=30, height=24, resolution=40), "#b0a1ef", "pitch_moving", "pitch")
        # Camera geometry uses optical coordinates (+Z is forward).
        self._add(pv.Cube(center=(0, 0, -32), x_length=75, y_length=56, z_length=64), "#39b8bb", "camera", "camera")
        self._add(pv.Cube(center=(0, 22, -30), x_length=66, y_length=5, z_length=48), "#26868e", "camera", "camera")
        self._add(pv.Cylinder(center=(0, 0, 5), direction=(0, 0, 1), radius=24, height=24, resolution=48), "#233b4d", "camera", "camera")
        self._add(pv.Disc(center=(0, 0, 18), inner=0, outer=19, normal=(0, 0, 1), c_res=48), "#67d7ed", "camera", "camera", opacity=0.85)
        # IMU body uses its own frame with local Z as the board normal.
        self._add(pv.Cube(center=(0, 0, 0), x_length=45, y_length=36, z_length=14), "#ecae57", "imu", "imu")
        self._add(pv.Cube(center=(0, 0, 9), x_length=15, y_length=15, z_length=5), "#66503b", "imu", "imu")
        board = geometry.board
        center = np.mean(board.outer_vertices_local_mm, axis=0) + [0, 0, 6]
        width, height, _ = np.ptp(board.outer_vertices_local_mm, axis=0)
        self._add(pv.Cube(center=center, x_length=width + 16, y_length=height + 16, z_length=10), "#60718a", "board", "board")
        for parity, color in ((0, "#e7edf6"), (1, "#17263b")):
            squares = board.squares_local_mm[board.square_is_dark == bool(parity)]
            points = squares.reshape(-1, 3)
            faces = np.column_stack((np.full(len(squares), 4), np.arange(len(points)).reshape(-1, 4))).ravel()
            self._add(pv.PolyData(points, faces), color, "board", "board", smooth_shading=False, lighting=False)
        # Axis lines are defined before the corresponding joint's rotation.
        for joint_id, color, extent in (("yaw", "#719fff", 190), ("pitch", "#c2abff", 150)):
            direction = geometry.joint_axes_local[joint_id]
            self._add(pv.Line(-direction * extent * 0.7, direction * extent), color, joint_id + "_home", line_width=3, lighting=False)
        # Coordinates and the pinhole frustum use exactly the same transforms as the scene.
        coordinate_frames = [("world", 110), ("yaw", 68), ("pitch", 68), ("camera", 82), ("imu", 60), ("board", 70)]
        if not np.allclose(geometry.transform(scene.gimbal.parent, "G"), np.eye(4), atol=1e-14, rtol=0):
            coordinate_frames.append(("gimbal", 100))
        if not np.allclose(geometry.world_pose("A"), np.eye(4), atol=1e-14, rtol=0):
            coordinate_frames.append(("absolute_reference", 140))
        for frame, length in coordinate_frames:
            for direction, color in zip(np.eye(3), ("#f5797c", "#7bd9a0", "#77a8ff")):
                actor = self._add(pv.Arrow(direction=direction, scale=length, tip_length=0.18, tip_radius=0.04, shaft_radius=0.012), color, frame, "world" if frame == "world" else None, lighting=False)
                self.axes_actors.append(actor)
        frustum_points = geometry.camera_frustum(570)
        lines = np.array([2, 0, 1, 2, 0, 2, 2, 0, 3, 2, 0, 4, 5, 1, 2, 3, 4, 1])
        actor = self._add(pv.PolyData(frustum_points, lines=lines), "#46aeb7", "camera", line_width=1, opacity=0.5, lighting=False)
        self.frustum_actors.append(actor)
        self.plotter.add_axes(viewport=(0, 0, 0.16, 0.22), color="#b8cee8", line_width=2)
        self.update_transforms()
        self.set_axes(self.axes_visible)
        self.set_frustum(self.frustum_visible)
        if previous_camera is not None:
            self.plotter.camera_position = previous_camera
        self.highlight(self.state.selected)

    def queue_scene(self, reason):
        # Coalesce slider events. Rebuild only when shape/installation changes.
        if self._pending_reason is None or reason != "scene:joint":
            self._pending_reason = reason
        self._render_timer.start(16)

    def _flush_scene(self):
        reason = self._pending_reason
        self._pending_reason = None
        if reason == "scene:joint":
            self.update_transforms()
            self.plotter.render()
        else:
            self.build_scene()

    def update_transforms(self):
        self.frames = self.state.geometry.frames
        for actor, frame in self.bindings:
            actor.user_matrix = self.frames[frame]
        self.plotter.reset_camera_clipping_range()

    def highlight(self, selected):
        for key, actors in self.object_actors.items():
            for actor in actors:
                actor.prop.show_edges = key == selected
                actor.prop.edge_color = "#85e5ff"
                actor.prop.line_width = 2
        self.selection_label.setText(f"选中：{NAMES[selected]}   /   单位 mm")
        self.plotter.render()

    def set_axes(self, visible):
        self.axes_visible = visible
        for actor in self.axes_actors:
            actor.visibility = visible
        self.plotter.render()

    def set_frustum(self, visible):
        self.frustum_visible = visible
        for actor in self.frustum_actors:
            actor.visibility = visible
        self.plotter.render()

    def set_view(self, mode):
        if mode == "overview":
            self.plotter.camera_position = [(-400, -1450, 850), (440, 0, 160), (0, 0, 1)]
        elif mode == "front":
            self.plotter.camera_position = [(450, -2200, 360), (450, 0, 210), (0, 0, 1)]
        elif mode == "top":
            self.plotter.camera_position = [(450, 0, 2300), (450, 0, 0), (1, 0, 0)]
        self.plotter.camera.view_angle = self.overview_angle_deg if mode == "overview" else 30
        self.plotter.reset_camera_clipping_range()
        self.plotter.render()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
        elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            current = event.position().toPoint()
            if self._press is not None and (current - self._press).manhattanLength() < 5 and event.modifiers() == Qt.KeyboardModifier.NoModifier:
                self.pick_at(current.x(), current.y())
            self._press = None
        return super().eventFilter(watched, event)

    def pick_at(self, x, y):
        width, height = self.plotter.render_window.GetSize()
        widget = self.plotter.interactor
        picker = vtkPropPicker()
        picker.Pick(x * width / max(widget.width(), 1), (widget.height() - y - 1) * height / max(widget.height(), 1), 0, self.plotter.renderer)
        actor = picker.GetActor()
        if actor is not None:
            key = self.actor_objects.get(actor.GetAddressAsString(""))
            if key:
                self.state.select(key)
                return key
        return None

    def shutdown(self):
        self._render_timer.stop()
        self.plotter.close()

