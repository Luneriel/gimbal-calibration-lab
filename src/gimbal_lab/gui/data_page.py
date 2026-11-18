"""Data generation page: async live camera, frozen jobs and isolated replay."""
from copy import deepcopy
import json
import logging
import os
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt, QSignalBlocker, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QMessageBox,
    QPlainTextEdit, QProgressBar, QSlider, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from gimbal_lab.domain.camera import RenderSettings, check_camera_model
from gimbal_lab.domain.datasets import ManualSession, generate_dataset, reserve_experiment_path, scene_signature
from gimbal_lab.domain.replay import Dataset
from gimbal_lab.domain.sampling import validate_sampling
from gimbal_lab.gui.data_tasks import DatasetJob, PreviewTask
from gimbal_lab.gui.replay_view import ImageView, ReplayController, ReplayDialog
from gimbal_lab.gui.widgets import Collapsible, PathField, button, heading, label, panel, pending, scroll, spin


class DataPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.bindings = []
        self.last_preview = None
        self.dataset = None
        self.manual_session = None
        self.replay = ReplayController(self)
        self.replay.changed.connect(self._show_replay)
        self.replay_dialog = None
        self._job = None
        self._closing = False
        self._cancel_manual_after_job = False
        self._task_state = "未配置"
        self._preview_revision = 0
        self._preview_busy = False
        self._preview_task = None
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._start_preview)
        self._build()
        state.project_changed.connect(self.refresh)
        state.scene_changed.connect(self.scene_updated)
        self.refresh()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(10)
        title, row = heading("模拟数据生成", "真实棋盘格成像、IMU 数据与实验快照")
        self.task_status = label("未配置", "Badge")
        row.addWidget(self.task_status)
        layout.addWidget(title)
        self.dataset_note = label("", "Notice", True)
        self.dataset_note.setMaximumHeight(48)
        self.dataset_note.hide()
        layout.addWidget(self.dataset_note)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(10)
        self.splitter.setChildrenCollapsible(False)
        options = panel()
        options.setMinimumWidth(270)
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        controls = QVBoxLayout(content)
        controls.setContentsMargins(18, 15, 18, 16)
        controls.setSpacing(10)
        controls.addWidget(label("采样参数", "Section"))
        self.mode = QComboBox()
        self.mode.addItems(["自动采样", "手动采样"])
        self.bind(self.mode, lambda p: p.sampling.mode, lambda p, v: setattr(p.sampling, "mode", v))
        controls.addWidget(self.mode)
        controls.addWidget(label("目标有效样本数", "Section"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(3, 10000)
        self.count_spin.setKeyboardTracking(False)
        self.count_spin.setSuffix(" 组")
        self.count_spin.setObjectName("sample_count")
        self.bind(self.count_spin, lambda p: p.sampling.count, lambda p, v: setattr(p.sampling, "count", v))
        controls.addWidget(self.count_spin)
        self.range_controls = []
        for key, text in (("yaw_range_deg", "Yaw 范围 · °"), ("pitch_range_deg", "Pitch 范围 · °")):
            controls.addWidget(label(text, "Section"))
            row = QHBoxLayout()
            for index in range(2):
                value = spin(0, -180, 180, 1)
                value.setAccessibleName(text + ("下限" if index == 0 else "上限"))
                self.bind(value, lambda p, k=key, i=index: getattr(p.sampling, k)[i],
                          lambda p, v, k=key, i=index: getattr(p.sampling, k).__setitem__(i, v))
                row.addWidget(value)
                self.range_controls.append(value)
                if index == 0:
                    row.addWidget(label("至", "Muted"))
            controls.addLayout(row)
        controls.addWidget(pending(QCheckBox("添加传感器噪声"), "后续扩展", "当前只支持理想、无噪声成像"))
        self.advanced = Collapsible("高级采样设置")
        self.advanced.content.addWidget(label("采样分布", "Section"))
        self.distribution = QComboBox()
        self.distribution.addItems(["分层均匀", "均匀随机"])
        self.bind(self.distribution, lambda p: p.sampling.distribution, lambda p, v: setattr(p.sampling, "distribution", v))
        self.advanced.content.addWidget(self.distribution)
        self.advanced.content.addWidget(label("随机种子", "Section"))
        self.seed = QSpinBox()
        self.seed.setRange(0, 2147483647)
        self.seed.setKeyboardTracking(False)
        self.bind(self.seed, lambda p: p.sampling.seed, lambda p, v: setattr(p.sampling, "seed", v))
        self.advanced.content.addWidget(self.seed)
        self.strict = QCheckBox("严格采样：失败姿态不替换")
        self.bind(self.strict, lambda p: p.sampling.strict, lambda p, v: setattr(p.sampling, "strict", v))
        self.advanced.content.addWidget(self.strict)
        self.advanced.content.addWidget(label("最大尝试次数 · 0 为自动预算", "Section"))
        self.attempts = QSpinBox()
        self.attempts.setRange(0, 200000)
        self.attempts.setKeyboardTracking(False)
        self.bind(self.attempts, lambda p: p.sampling.max_attempts, lambda p, v: setattr(p.sampling, "max_attempts", v))
        self.advanced.content.addWidget(self.attempts)
        self.advanced.content.addWidget(label("自动预算为 max(50,10×目标数)。失败均保留原因，实际覆盖单独报告。", "Muted", True))
        controls.addWidget(self.advanced)
        self.mode_hint = label("", "Notice", True)
        controls.addWidget(self.mode_hint)
        self.example_button = button("载入宽视场示例", self.load_example)
        controls.addWidget(self.example_button)
        controls.addStretch()
        options_layout.addWidget(scroll(content))
        self.splitter.addWidget(options)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        preview = panel()
        preview.setStyleSheet("QFrame#Panel { background: #122238; border: 1px solid #263b55; border-radius: 9px; }")
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(12, 10, 12, 10)
        header = QHBoxLayout()
        header.addWidget(label("虚拟相机", "Section"))
        self.resolution = label("", "Muted")
        header.addWidget(self.resolution)
        header.addStretch()
        self.open_button = button("打开实验…", self.open_dataset)
        self.three_d_button = button("3D 回放", self.open_3d)
        self.live_button = button("实时预览", self.exit_replay)
        self.diagnostics_button = button("诊断…", self.show_diagnostics)
        for control in (self.open_button, self.three_d_button, self.live_button, self.diagnostics_button):
            header.addWidget(control)
        preview_layout.addLayout(header)
        self.image_view = ImageView()
        self.image_view.show_message("正在准备相机预览…")
        preview_layout.addWidget(self.image_view, 1)
        footer = QHBoxLayout()
        self.pose_label = label("", "Muted")
        footer.addWidget(self.pose_label, 1)
        for text, action in (("适应", self.image_view.fit_image), ("1:1", self.image_view.actual_size)):
            control = button(text, action)
            control.setFixedWidth(48)
            control.setToolTip("只改变显示缩放；滚轮缩放、拖动平移、双击适应窗口。")
            footer.addWidget(control)
        self.corner_overlay = QCheckBox("检测角点")
        self.corner_overlay.toggled.connect(self.redraw_image)
        footer.addWidget(self.corner_overlay)
        preview_layout.addLayout(footer)
        self.quaternion_label = label("", "Muted")
        self.quaternion_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview_layout.addWidget(self.quaternion_label)
        right_layout.addWidget(preview, 1)
        quality = panel()
        quality_layout = QVBoxLayout(quality)
        quality_layout.setContentsMargins(14, 9, 14, 9)
        quality_layout.setSpacing(6)
        summary = QHBoxLayout()
        self.validity_label = label("等待实际图像检测", "Section")
        self.coverage_label = label("尚无实验样本", "Muted")
        summary.addWidget(self.validity_label, 1)
        summary.addWidget(self.coverage_label, 1)
        quality_layout.addLayout(summary)
        self.validity_hint = label("", "Muted", True)
        self.validity_hint.setMaximumHeight(32)
        quality_layout.addWidget(self.validity_hint)
        playback = QHBoxLayout()
        self.replay_kind = QComboBox()
        self.replay_kind.addItem("有效样本", "valid")
        self.replay_kind.addItem("失败记录", "failure")
        self.replay_kind.currentIndexChanged.connect(lambda _: self.select_replay(0, self.replay_kind.currentData()))
        playback.addWidget(self.replay_kind)
        self.previous_button = button("‹", lambda: self.select_replay(self.replay.index - 1))
        self.next_button = button("›", lambda: self.select_replay(self.replay.index + 1))
        self.replay_slider = QSlider(Qt.Orientation.Horizontal)
        self.replay_slider.valueChanged.connect(self.select_replay)
        playback.addWidget(self.previous_button)
        playback.addWidget(self.replay_slider, 1)
        playback.addWidget(self.next_button)
        self.sample_index = label("无样本", "Muted")
        playback.addWidget(self.sample_index)
        quality_layout.addLayout(playback)
        right_layout.addWidget(quality)
        self.splitter.addWidget(right)
        self.splitter.setSizes([300, 1100])
        self.splitter.setStretchFactor(1, 1)
        layout.addWidget(self.splitter, 1)
        output = panel()
        output_layout = QVBoxLayout(output)
        output_layout.setContentsMargins(17, 11, 17, 11)
        output_layout.setSpacing(9)
        path_row = QHBoxLayout()
        path_row.addWidget(label("输出父目录", "Section"))
        self.output = PathField("", "output_dir", "在此目录下新建 experiment_###，已有数据不会被覆盖")
        self.output.changed.connect(lambda value: self.update(lambda p: setattr(p.sampling, "output_dir", value)))
        path_row.addWidget(self.output, 1)
        output_layout.addLayout(path_row)
        actions = QHBoxLayout()
        self.generate_button = button("生成数据", self.generate, primary=True)
        self.manual_button = button("保存当前样本", self.save_manual)
        self.cancel_button = button("取消", self.cancel)
        for control in (self.generate_button, self.manual_button, self.cancel_button):
            actions.addWidget(control)
        self.statistics = label("有效 0 / 失败 0", "Muted")
        actions.addWidget(self.statistics)
        actions.addStretch()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(160)
        actions.addWidget(self.progress)
        output_layout.addLayout(actions)
        layout.addWidget(output)

    def bind(self, widget, getter, setter):
        self.bindings.append((widget, getter))
        signal = widget.currentTextChanged if isinstance(widget, QComboBox) else widget.toggled if isinstance(widget, QCheckBox) else widget.valueChanged
        signal.connect(lambda value: self.update(lambda p: setter(p, value)))

    def update(self, mutator):
        self.state.edit(mutator)
        self.refresh()

    def refresh(self):
        for widget, getter in self.bindings:
            with QSignalBlocker(widget):
                value = getter(self.state.project)
                if isinstance(widget, QComboBox):
                    widget.setCurrentText(value)
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(value)
                else:
                    widget.setValue(value)
        self.output.set_path(self.state.project.sampling.output_dir)
        manual = self.manual_session is not None or self.state.project.sampling.mode == "手动采样"
        self.mode_hint.setText("手动模式：在场景页调姿态，保存当前样本；完成后结束实验。重复姿态会记录并拒绝导出。" if manual else "默认自动补充有效姿态；严格模式只执行初始计划。覆盖不足会明确报告。")
        self._refresh_buttons()
        self.update_preview_info()

    def _configuration_error(self):
        try:
            check_camera_model(self.state.geometry, RenderSettings())
            if self.state.project.sampling.mode == "自动采样":
                validate_sampling(self.state.project.scene, self.state.project.sampling)
            parent = Path(self.state.project.sampling.output_dir).expanduser()
            if not self.state.project.sampling.output_dir or not parent.is_dir():
                return "请选择已有的输出父目录"
            if not os.access(parent, os.W_OK):
                return "输出父目录不可写"
            if (parent / "experiment.json").exists():
                return "所选路径是已有实验，请选择其父目录"
        except (ValueError, OSError) as exc:
            return str(exc)
        return ""

    def _refresh_buttons(self):
        busy = self._job is not None
        manual = self.manual_session is not None or self.state.project.sampling.mode == "手动采样"
        error = self._configuration_error()
        for widget, _ in self.bindings:
            widget.setEnabled(not busy)
        self.mode.setEnabled(not busy and self.manual_session is None)
        for widget in [self.count_spin, self.seed, self.strict, self.distribution, self.attempts, *self.range_controls]:
            widget.setEnabled(not busy and not manual)
        self.output.setEnabled(not busy and self.manual_session is None)
        self.example_button.setEnabled(not busy and self.manual_session is None)
        self.open_button.setEnabled(not busy and self.manual_session is None)
        self.generate_button.setText("结束手动实验" if self.manual_session is not None else "新建手动实验" if manual else "生成数据")
        self.generate_button.setEnabled(not busy and (self.manual_session is not None or not error))
        self.manual_button.setEnabled(not busy and manual and (self.manual_session is not None or not error))
        self.cancel_button.setEnabled(busy or self.manual_session is not None)
        self.generate_button.setToolTip(error)
        self.manual_button.setToolTip(error if self.manual_session is None else "保存到当前冻结场景的手动实验")
        has_dataset = self.dataset is not None
        for widget in (self.replay_kind, self.replay_slider, self.previous_button, self.next_button):
            widget.setEnabled(has_dataset and not busy and self.manual_session is None)
        self.three_d_button.setEnabled(has_dataset and self.replay.count() > 0 and not busy)
        self.live_button.setEnabled(self.replay.active and not busy)
        self.diagnostics_button.setEnabled(has_dataset or self.manual_session is not None)
        if self._task_state in ("未配置", "就绪"):
            self._task_state = "未配置" if error else "就绪"
        self.task_status.setText(self._task_state)
        self.task_status.setToolTip(error)

    def scene_updated(self, *_):
        self.update_preview_info()
        self._refresh_buttons()
        self.schedule_preview()
        self._update_dataset_note()

    def update_preview_info(self, *_):
        if not self.replay.active and self._job is None:
            scene = self.state.project.scene
            self.resolution.setText(f"{scene.camera.width} × {scene.camera.height} px")
            self.pose_label.setText(f"实时预览 · Yaw {scene.yaw.angle_deg:+.1f}°  Pitch {scene.pitch.angle_deg:+.1f}°")

    def showEvent(self, event):
        super().showEvent(event)
        self.schedule_preview()

    def schedule_preview(self):
        self._preview_revision += 1
        if not self._closing and not self.replay.active:
            self._preview_timer.start(120)

    def _start_preview(self):
        if self._closing or not self.isVisible() or self.replay.active or self._job is not None or self._preview_busy:
            return
        self._preview_busy = True
        task = PreviewTask(self._preview_revision, self.state.geometry)
        task.signals.done.connect(self._preview_done)
        self._preview_task = task
        self._pool.start(task)

    def _preview_done(self, revision, frame, error):
        self._preview_busy = False
        if self._closing:
            return
        if revision != self._preview_revision:
            if not self.replay.active:
                self._preview_timer.start(10)
            return
        if self.replay.active or self._job is not None:
            return
        if error:
            self._display_image = None
            self._display_corners = None
            self.image_view.show_message(error)
            self.validity_label.setText("预览配置无效")
            self.validity_hint.setText(error)
            self.quaternion_label.setText("")
            self.last_preview = None
        else:
            self.last_preview = frame
            self._display_frame(frame)
        self._refresh_buttons()

    def _display_frame(self, frame, prefix="实时预览"):
        self._display_image = frame.image
        self._display_corners = frame.aligned_corners
        self._display_pattern = (frame.state.board.columns, frame.state.board.rows)
        self.redraw_image()
        angles = frame.state.angles_deg
        self.resolution.setText(f"{frame.state.image_size[0]} × {frame.state.image_size[1]} px")
        self.pose_label.setText(f"{prefix} · Yaw {angles.yaw_deg:+.2f}°  Pitch {angles.pitch_deg:+.2f}°")
        self.quaternion_label.setText("q_A_I · wxyz  " + "  ".join(f"{value:+.7f}" for value in frame.state.quaternion_wxyz))
        self.validity_label.setText("几何可见 · 角点有效" if frame.valid else "当前姿态无效")
        if frame.valid:
            self.validity_hint.setText(f"{len(frame.aligned_corners)} 个角点 · 角点 RMSE {frame.metrics['corner_rmse_px']:.3f} px · 单帧 PnP 重投影 {frame.metrics['pnp_reprojection_rmse_px']:.3f} px")
        else:
            self.validity_hint.setText(frame.reason_text)
        self.validity_hint.setToolTip(frame.reason_text or "PnP 是单帧图像有效性检查，不是手眼标定误差。角点对称顺序按已知 GT 对齐，仅用于验证。")

    def redraw_image(self, *_):
        image = getattr(self, "_display_image", None)
        if image is None:
            return
        corners = getattr(self, "_display_corners", None)
        if self.corner_overlay.isChecked() and corners is not None:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            cv2.drawChessboardCorners(image, self._display_pattern, corners.astype("float32").reshape(-1, 1, 2), True)
        self.image_view.show_array(image)

    def _new_root(self):
        error = self._configuration_error()
        if error:
            raise ValueError(error)
        return reserve_experiment_path(self.state.project.sampling.output_dir)

    def _start_job(self, operation, action):
        if self._job is not None:
            return
        self._task_state = "加载中" if operation == "load" else "生成中"
        self._preview_revision += 1
        self._job = DatasetJob(operation, action, self)
        self._job.progress.connect(self._progress)
        self._job.finished.connect(self._job_finished)
        self.progress.setRange(0, 0)
        self._refresh_buttons()
        self._job.start()

    def generate(self):
        if self._job is not None:
            return
        if self.manual_session is not None:
            session = self.manual_session
            self._start_job("manual_finish", lambda cancel, report: {"kind": "dataset", "dataset": Dataset(session.finish(cancel_event=cancel))})
            return
        if self.state.project.sampling.mode == "手动采样":
            self._begin_manual(False)
            return
        try:
            root = self._new_root()
            project = deepcopy(self.state.project)
            self._job_target = project.sampling.count
            self.exit_replay()
            def run(cancel, report):
                result = generate_dataset(project, root, cancel_event=cancel, progress=report)
                return {"kind": "dataset", "dataset": Dataset(result)}
            self._start_job("auto", run)
            self.state.message.emit(f"开始生成：{root}（场景已冻结）", False)
        except (ValueError, OSError) as exc:
            self.state.message.emit(str(exc), True)

    def _begin_manual(self, add):
        try:
            root = self._new_root()
            project = deepcopy(self.state.project)
            scene = deepcopy(self.state.project.scene)
            self.exit_replay()
            def run(cancel, report):
                session = ManualSession(project, root)
                record, frame = session.add_pose(scene) if add else (None, None)
                return {"kind": "manual", "session": session, "record": record, "frame": frame}
            self._start_job("manual_add" if add else "manual_start", run)
        except (ValueError, OSError) as exc:
            self.state.message.emit(str(exc), True)

    def save_manual(self):
        if self._job is not None:
            return
        if self.manual_session is None:
            self._begin_manual(True)
            return
        scene, session = deepcopy(self.state.project.scene), self.manual_session
        def run(cancel, report):
            record, frame = session.add_pose(scene)
            return {"kind": "manual", "session": session, "record": record, "frame": frame}
        self._start_job("manual_add", run)

    def cancel(self):
        if self._job is not None:
            self._job.cancel_event.set()
            if self._job.operation.startswith("manual"):
                self._cancel_manual_after_job = True
            self.task_status.setText("正在取消…")
        elif self.manual_session is not None:
            session = self.manual_session
            self._start_job("manual_cancel", lambda cancel, report: {"kind": "dataset", "dataset": Dataset(session.finish(cancelled=True))})

    def _progress(self, record, frame, valid, failed):
        if self._closing:
            return
        self.statistics.setText(f"有效 {valid} / 失败 {failed} / 尝试 {record['plan_id']}")
        self._display_frame(frame, f"生成候选 #{record['plan_id']} · 冻结快照")
        self.progress.setRange(0, self._job_target)
        self.progress.setValue(valid)

    def _job_finished(self):
        job = self._job
        if job is None:
            return
        result, error, operation = job.result, job.error, job.operation
        self._job = None
        job.deleteLater()
        if self._closing:
            return
        self.progress.setRange(0, 100)
        if error:
            self._task_state = "失败"
            if self.manual_session is not None and self.manual_session.writer.document["status"] == "failed":
                session = self.manual_session
                self.manual_session = None
                try:
                    self.attach_dataset(Dataset(session.root))
                except (ValueError, OSError):
                    logging.exception("Failed manual dataset cannot be replayed")
            self.state.message.emit(error, True)
            self._refresh_buttons()
            return
        if operation == "load" and job.cancel_event.is_set():
            self._task_state = "已取消"
        elif result["kind"] == "manual":
            self.manual_session = result["session"]
            self._task_state = "手动实验中"
            writer = self.manual_session.writer
            self.statistics.setText(f"有效 {writer.valid_count} / 失败 {len(writer.records) - writer.valid_count}")
            if result["frame"] is not None:
                self._display_frame(result["frame"], "手动样本 · 冻结快照")
            if result["record"] is not None:
                record = result["record"]
                self.state.message.emit(f"已保存样本 #{record['export_id']}" if record["valid"] else record["reason_text"], not record["valid"])
            if self._cancel_manual_after_job:
                self._cancel_manual_after_job = False
                self.cancel()
                return
        else:
            self.manual_session = None
            self._cancel_manual_after_job = False
            self.attach_dataset(result["dataset"])
        self._refresh_buttons()
        self._update_dataset_note()

    def attach_dataset(self, dataset):
        if self.replay_dialog is not None:
            self.replay_dialog.close()
        self.dataset = dataset
        status_map = {"completed": "已完成", "cancelled": "已取消", "failed": "失败", "partial": "已完成（有效不足）"}
        self._task_state = status_map[dataset.status]
        d = dataset.document
        self.statistics.setText(f"有效 {d['valid_count']} / 失败 {d['failed_count']} / 尝试 {d['attempted_count']}")
        self.progress.setValue(100 if dataset.status == "completed" else min(100, int(100 * d['valid_count'] / max(1, dataset.project.sampling.count))))
        coverage = d["coverage"]
        ranges = coverage["actual_ranges"]
        if ranges:
            y, p = ranges["yaw_deg"], ranges["pitch_deg"]
            self.coverage_label.setText(f"实际 Yaw [{y[0]:.1f},{y[1]:.1f}]° · Pitch [{p[0]:.1f},{p[1]:.1f}]°")
        else:
            self.coverage_label.setText("无有效姿态覆盖")
        self.coverage_label.setToolTip("\n".join(coverage["warnings"]) or "实际跨度已记录；覆盖统计是启发式检查，不能保证标定可观测性。")
        self.replay.attach(dataset)
        with QSignalBlocker(self.replay_kind):
            self.replay_kind.setCurrentIndex(self.replay_kind.findData(self.replay.kind))
        self.state.message.emit(f"实验 {self._task_state}：{dataset.root}；有效 {d['valid_count']} / 失败 {d['failed_count']}", dataset.status == "failed")
        self._update_dataset_note()
        self._refresh_buttons()

    def open_dataset(self):
        path = QFileDialog.getExistingDirectory(self, "选择包含 experiment.json 的实验目录", self.state.project.sampling.output_dir or str(Path.home()))
        if path:
            self.load_dataset(path)

    def load_dataset(self, root):
        if self._job is not None or self.manual_session is not None:
            self.state.message.emit("请先结束或取消当前实验任务，再加载其他实验。", True)
            return
        self._start_job("load", lambda cancel, report: {"kind": "dataset", "dataset": Dataset(root)})

    def select_replay(self, index, kind=None):
        if self.dataset is None or self._job is not None:
            return
        try:
            self.replay.select(index, kind)
        except (ValueError, OSError, KeyError) as exc:
            self.state.message.emit(f"回放失败：{exc}", True)

    def _show_replay(self, item):
        with QSignalBlocker(self.replay_slider):
            self.replay_slider.setRange(0, max(0, self.replay.count() - 1))
            self.replay_slider.setValue(self.replay.index)
        self.sample_index.setText(f"{self.replay.index + 1} / {self.replay.count()}" if self.replay.count() else "无记录")
        if item is None:
            self._display_image = None
            self.image_view.show_message("实验没有可回放记录")
            self.pose_label.setText("回放 · 无样本")
            self.validity_label.setText("无可回放记录")
            self.validity_hint.setText("该实验尚未保存任何候选姿态或图片。")
            self.quaternion_label.setText("")
            return
        record, angles = item.record, item.state.angles_deg
        self.resolution.setText(f"{item.state.image_size[0]} × {item.state.image_size[1]} px")
        self.pose_label.setText(f"回放 · 计划 #{record['plan_id']} / 导出 #{record['export_id'] or '—'} · Yaw {angles.yaw_deg:+.2f}° Pitch {angles.pitch_deg:+.2f}°")
        self._display_image = item.image
        self._display_corners = None if record.get("aligned_detected_corners_px") is None else np.array(record["aligned_detected_corners_px"])
        self._display_pattern = (item.state.board.columns, item.state.board.rows)
        if item.image is None:
            self.image_view.show_message("失败姿态未导出 JPG\n" + record["reason_text"])
            self.quaternion_label.setText("未导出 TXT；3D 回放仍使用该候选的真实几何状态。")
        else:
            self.redraw_image()
            self.quaternion_label.setText("TXT · wxyz  " + "  ".join(f"{v:+.7f}" for v in item.quaternion))
        self.validity_label.setText("已导出 · 视觉检测有效" if record["valid"] else "失败记录 · 未导出")
        metrics = record.get("metrics", {})
        text = record["reason_text"]
        if record["valid"]:
            text = f"角点 RMSE {metrics['corner_rmse_px']:.3f} px · 单帧 PnP {metrics['pnp_reprojection_rmse_px']:.3f} px" if "corner_rmse_px" in metrics and "pnp_reprojection_rmse_px" in metrics else "该样本未记录角点/PnP 指标"
        self.validity_hint.setText(text)
        self._refresh_buttons()

    def exit_replay(self):
        if self.replay_dialog is not None:
            self.replay_dialog.close()
        self.replay.active = False
        self._display_image = None
        self.image_view.show_message("正在更新实时预览…")
        self.quaternion_label.setText("")
        self.update_preview_info()
        self.schedule_preview()
        self._refresh_buttons()

    def open_3d(self):
        if self.dataset is None or self.replay.count() == 0:
            return
        if not self.replay.active:
            self.select_replay(self.replay.index)
        if self.replay_dialog is None:
            self.replay_dialog = ReplayDialog(self.replay, self)
            self.replay_dialog.destroyed.connect(lambda: setattr(self, "replay_dialog", None))
        self.replay_dialog.show()
        self.replay_dialog.raise_()

    def _update_dataset_note(self):
        writer = self.manual_session.writer if self.manual_session is not None else None
        project = writer.project if writer else self.dataset.project if self.dataset is not None else None
        if project is None:
            self.dataset_note.hide()
            return
        root = writer.root if writer else self.dataset.root
        stale = scene_signature(project.scene) != scene_signature(self.state.project.scene)
        text = f"实验：{root}"
        if stale:
            text += " · 编辑场景已改变；已有数据继续使用原快照。"
        if self.dataset is not None and self.dataset.document["coverage"]["warnings"]:
            text += " · 存在覆盖或模型提示，请查看诊断。"
        self.dataset_note.setText(text)
        self.dataset_note.setToolTip(text)
        self.dataset_note.show()

    def show_diagnostics(self):
        document = self.manual_session.writer.document if self.manual_session is not None else self.dataset.document if self.dataset is not None else None
        if document is None:
            return
        summary = {"status": document["status"], "coverage": document.get("coverage"),
                   "failure_reasons": document.get("failure_reasons"),
                   "failures": [{"plan_id": r["plan_id"], "yaw_deg": r["yaw_deg"], "pitch_deg": r["pitch_deg"], "reason": r["reason_text"]} for r in document["candidates"] if not r["valid"]]}
        dialog = QDialog(self)
        dialog.setWindowTitle("采样覆盖与失败诊断")
        dialog.resize(760, 620)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(json.dumps(summary, ensure_ascii=False, indent=2))
        layout.addWidget(text)
        dialog.exec()

    def load_example(self):
        answer = QMessageBox.question(self, "载入宽视场示例", "将载入已验证的宽视场场景（fx=fy=520 px），保留当前采样草稿。是否替换编辑场景？")
        if answer == QMessageBox.StandardButton.Yes:
            self.state.apply_preset("采样示例（宽视场）")
            self.exit_replay()

    def shutdown(self):
        self._closing = True
        self._preview_timer.stop()
        if self._job is not None:
            self._job.cancel_event.set()
            if not self._job.wait(15000):
                return False
            result = self._job.result
            if result and result.get("kind") == "manual":
                self.manual_session = result["session"]
        if self.manual_session is not None and self.manual_session.writer.document["status"] == "generating":
            try:
                self.manual_session.finish(cancelled=True)
            except Exception:
                logging.exception("Closing manual session failed")
        self._pool.clear()
        if not self._pool.waitForDone(15000):
            return False
        if self.replay_dialog is not None:
            self.replay_dialog.close()
        return True
