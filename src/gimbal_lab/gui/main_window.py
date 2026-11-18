from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker, Signal, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFrame,
    QHBoxLayout, QInputDialog, QMainWindow, QMenu, QMessageBox, QStackedWidget,
    QVBoxLayout, QWidget, QSizePolicy,
)

from gimbal_lab import __version__
from gimbal_lab.gui.calibration_page import CalibrationPage
from gimbal_lab.gui.data_page import DataPage
from gimbal_lab.gui.scene_page import ScenePage
from gimbal_lab.gui.state import AppState
from gimbal_lab.gui.widgets import button, icon, label


class MainWindow(QMainWindow):
    def __init__(self, log_path: Path | None = None):
        super().__init__()
        self.state = AppState()
        self.log_path = log_path
        self._close_approved = False
        self.setWindowTitle("Gimbal Calibration Lab")
        self.setWindowIcon(icon("camera"))
        self.setMinimumSize(1100, 700)
        self.resize(1480, 900)
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("Header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(23, 10, 23, 10)
        header_layout.setSpacing(12)
        header_layout.addWidget(label("Gimbal Calibration Lab", "Brand"))
        header_layout.addStretch()
        header_layout.addSpacing(5)
        project_button = button("项目")
        self.project_menu = QMenu(project_button)
        for text, callback, shortcut in (("新建项目", self.new_project, "Ctrl+N"), ("打开项目…", self.open_project, "Ctrl+O"),
                                         ("另存为…", lambda: self.save_project(True), "Ctrl+Shift+S"),
                                         ("重命名项目…", self.rename_project, ""), ("恢复初始场景…", self.restore_scene, "")):
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
                self.addAction(action)
            action.triggered.connect(callback)
            self.project_menu.addAction(action)
        project_button.setMenu(self.project_menu)
        header_layout.addWidget(project_button)
        header_layout.addWidget(button("保存", self.save_project))
        save_action = QAction("保存项目", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(lambda: self.save_project())
        self.addAction(save_action)
        header_layout.addWidget(button("设置", self.show_settings))
        root_layout.addWidget(header)
        navigation = QFrame()
        navigation.setObjectName("Navigation")
        nav_layout = QHBoxLayout(navigation)
        nav_layout.setContentsMargins(21, 6, 23, 6)
        nav_layout.setSpacing(6)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = []
        for index, name in enumerate(("场景搭建", "模拟数据生成", "标定验证")):
            tab = button(f"0{index + 1}   {name}")
            tab.setObjectName("Nav")
            tab.setCheckable(True)
            tab.setToolTip(f"Ctrl+{index + 1}")
            self.nav_group.addButton(tab, index)
            self.nav_buttons.append(tab)
            nav_layout.addWidget(tab)
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda i=index: self.set_page(i))
        nav_layout.addStretch()
        root_layout.addWidget(navigation)
        self.pages = QStackedWidget()
        self.scene_page = ScenePage(self.state)
        self.data_page = DataPage(self.state)
        self.calibration_page = CalibrationPage(self.state)
        self.pages.addWidget(self.scene_page)
        self.pages.addWidget(self.data_page)
        self.pages.addWidget(self.calibration_page)
        root_layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)
        self.nav_group.idClicked.connect(self.set_page)
        self.scene_page.preview_requested.connect(lambda: self.set_page(1))
        status = self.statusBar()
        status.setSizeGripEnabled(True)
        self.project_status = label("")
        self.project_status.setContentsMargins(18, 4, 13, 4)
        status.addWidget(self.project_status)
        self.feedback = label("● 就绪 · 可编辑场景")
        self.feedback.setObjectName("Feedback")
        self.feedback.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        status.addWidget(self.feedback, 1)
        version = label(f"v{__version__}", "Muted")
        version.setContentsMargins(0, 0, 12, 0)
        status.addPermanentWidget(version)
        self.state.dirty_changed.connect(self.update_project_status)
        self.state.project_changed.connect(self.update_project_status)
        self.state.message.connect(self.show_message)
        self.update_project_status()
        self.set_page(0)
        self.show_message("就绪，可编辑场景、生成模拟数据或配置标定实验。", False)

    def set_page(self, index):
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        if index == 0:
            self.scene_page.viewport.plotter.render()

    def update_project_status(self, *_):
        suffix = " · 未保存" if self.state.dirty else ""
        self.project_status.setText(self.state.project.name + suffix)
        self.project_status.setToolTip(str(self.state.path) if self.state.path else "尚未保存的项目")
        self.setWindowTitle(f"{'* ' if self.state.dirty else ''}{self.state.project.name} — Gimbal Calibration Lab")
        if self.feedback.property("has_error"):
            self.show_message("参数已更新", False)

    def show_message(self, text, error=False):
        self.feedback.setProperty("has_error", error)
        self.feedback.setText(("● " if not error else "! ") + text)
        self.feedback.setToolTip(text)
        self.feedback.style().unpolish(self.feedback)
        self.feedback.style().polish(self.feedback)
        timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
        self.calibration_page.log_view.appendPlainText(f"[{timestamp}] {'错误' if error else '应用'}  {text}")
        (logging.error if error else logging.info)(text)

    def save_project(self, save_as=False):
        path = self.state.path
        if save_as or path is None:
            path_text, _ = QFileDialog.getSaveFileName(self, "保存实验项目", str(path or Path.home() / "experiment.gimbal.json"), "实验项目 (*.gimbal.json *.json)")
            if not path_text:
                return False
            path = Path(path_text)
            if path.suffix.lower() != ".json":
                path = path.with_name(path.name + ".gimbal.json")
        try:
            self.state.save(path)
            return True
        except (OSError, ValueError) as exc:
            self.show_message(f"保存失败：{exc}", True)
            QMessageBox.critical(self, "无法保存项目", str(exc))
            return False

    def confirm_unsaved(self):
        if not self.state.dirty:
            return True
        answer = QMessageBox.warning(self, "项目尚未保存", "是否保存当前场景和实验设置？", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def open_project(self):
        if not self.confirm_unsaved():
            return
        path, _ = QFileDialog.getOpenFileName(self, "打开实验项目", str(self.state.path.parent if self.state.path else Path.home()), "实验项目 (*.gimbal.json *.json)")
        if path:
            try:
                self.state.load(Path(path))
                self.update_project_status()
            except (OSError, ValueError) as exc:
                self.show_message(f"加载失败，当前项目已保留：{exc}", True)
                QMessageBox.critical(self, "无法加载项目", str(exc))

    def new_project(self):
        if self.confirm_unsaved():
            self.state.new()

    def rename_project(self):
        text, accepted = QInputDialog.getText(self, "重命名项目", "项目名称", text=self.state.project.name)
        if accepted and self.state.edit(lambda p: setattr(p, "name", text.strip())):
            self.update_project_status()

    def restore_scene(self):
        answer = QMessageBox.question(self, "恢复初始场景", "恢复理想双轴云台的所有场景参数？采样设置和路径将保留。")
        if answer == QMessageBox.StandardButton.Yes:
            self.state.apply_preset("理想双轴云台")

    def show_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("显示与坐标约定")
        dialog.setMinimumWidth(470)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        layout.addWidget(label("显示与坐标约定", "Title"))
        axes = QCheckBox("显示对象坐标系")
        axes.setChecked(self.scene_page.axes_check.isChecked())
        axes.toggled.connect(self.scene_page.axes_check.setChecked)
        frustum = QCheckBox("显示相机视锥")
        frustum.setChecked(self.scene_page.frustum_check.isChecked())
        frustum.toggled.connect(self.scene_page.frustum_check.setChecked)
        layout.addWidget(axes)
        layout.addWidget(frustum)
        gimbal_parent = self.state.project.scene.gimbal.parent
        layout.addWidget(label(f"长度：mm    角度：°    右手坐标系\n变换：T_A_B 将 B 中坐标转换到 A\n安装角：Yaw / Pitch / Roll\nR = Rz(Yaw) · Ry(Pitch) · Rx(Roll)\nIMU：R_A_I = R_A_W · R_W_I，四元数 w x y z\n求解参考系 G 固定于：{gimbal_parent}\nB = 固定底座，T = 标定板", "Notice", True))
        layout.addWidget(label("G 在世界坐标系的高级属性中设置；R_A_W 在 IMU 的高级属性中设置。\n完整说明见 docs/COORDINATES.md。", "Muted", True))
        log_label = label(f"应用日志：{self.log_path or '当前会话终端'}", "Muted", True)
        log_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(log_label)
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(dialog.reject)
        layout.addWidget(close_buttons)
        dialog.exec()

    def closeEvent(self, event: QCloseEvent):
        if not self._close_approved and not self.confirm_unsaved():
            event.ignore()
            return
        self._close_approved = True
        if not self.calibration_page.shutdown() or not self.data_page.shutdown():
            event.ignore()
            QTimer.singleShot(500, self.close)
            return
        self.scene_page.viewport.shutdown()
        event.accept()

