"""Existing calibration layout, driven exclusively by the shared experiment service."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import shlex

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLineEdit, QPlainTextEdit, QProgressBar, QSpinBox, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from gimbal_lab.experiments.evaluation import compare_run_records
from gimbal_lab.experiments.presets import baseline_preset
from gimbal_lab.experiments.schema import AdapterPreset, ExperimentRequest, SubsetSpec
from gimbal_lab.experiments.service import ExperimentService, load_run
from gimbal_lab.gui.adapter_dialog import AdapterDialog
from gimbal_lab.gui.experiment_tasks import ExperimentJob
from gimbal_lab.gui.widgets import Collapsible, PathField, button, heading, label, panel, scroll, spin


class CalibrationPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.service = ExperimentService()
        self._preset = None
        self._preset_key = ''
        self._job = None
        self._closing = False
        self._refreshing = False
        self.summary = None
        self.records = []
        self.current_record = None
        self.current_candidate = None
        self.comparison_dialogs = []
        self.registry = Path.home() / '.config/gimbal-calibration-lab/adapters'
        self._build()
        state.project_changed.connect(self.refresh)
        self.refresh()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(10)
        title, title_row = heading('标定验证', '运行外部程序，记录实际输入，并独立比较估计与 Ground Truth')
        self.status_label = label('未配置', 'Badge')
        title_row.addWidget(self.status_label)
        layout.addWidget(title)
        run_panel = panel()
        run_layout = QVBoxLayout(run_panel)
        run_layout.setContentsMargins(18, 10, 18, 10)
        run_layout.setSpacing(5)
        run_layout.addWidget(label('运行手眼标定', 'Section'))
        form = QFormLayout()
        form.setVerticalSpacing(5)
        form.setHorizontalSpacing(14)
        program_row = QWidget()
        row = QHBoxLayout(program_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.program = QComboBox()
        self.program.setObjectName('program_entry')
        self.program.currentIndexChanged.connect(self.choose_program)
        row.addWidget(self.program, 1)
        self.manage_button = button('管理预设', self.manage_preset)
        row.addWidget(self.manage_button)
        form.addRow(label('标定程序'), program_row)
        self.paths = {}
        for attr, title_text, kind, placeholder in (
            ('pictures_dir', '图片目录', 'input_dir', '选择连续或可重新编号的 JPG 目录'),
            ('quaternion_dir', 'TXT 目录', 'input_dir', '独立选择 wxyz 四元数 TXT 目录'),
            ('output_yaml', '输出 YAML', 'yaml', '保存规范结果；已有文件不会被覆盖'),
        ):
            field = PathField('', kind, placeholder)
            field.edit.setObjectName(attr)
            field.changed.connect(lambda value, key=attr: self.set_draft(key, value))
            self.paths[attr] = field
            form.addRow(label(title_text), field)
        run_layout.addLayout(form)
        self.advanced = Collapsible('高级设置')
        self.config = PathField('外部相机配置（可选）', 'config', '模拟数据目录自动读取相机参数，不向程序提供 Ground Truth')
        self.config.changed.connect(lambda value: self.set_draft('config_file', value))
        self.advanced.content.addWidget(self.config)
        self.entry_detail = label('', 'Muted', True)
        self.advanced.content.addWidget(self.entry_detail)
        extra = QFormLayout()
        self.kind = QComboBox()
        for text, value in (('单次运行', 'single'), ('相同输入重复运行', 'repeat'), ('不同随机子集比较', 'subsets')):
            self.kind.addItem(text, value)
        extra.addRow('实验类型', self.kind)
        self.repetitions = QSpinBox()
        self.repetitions.setRange(1, 20)
        self.repetitions.setValue(3)
        extra.addRow('重复/子集组数', self.repetitions)
        self.subset_mode = QComboBox()
        for text, value in (('全部有效样本', 'all'), ('固定种子随机子集', 'random'), ('指定原始有效编号', 'ids')):
            self.subset_mode.addItem(text, value)
        extra.addRow('样本子集', self.subset_mode)
        self.subset_count = QSpinBox()
        self.subset_count.setRange(1, 10000)
        self.subset_count.setValue(15)
        extra.addRow('随机子集数量', self.subset_count)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2147483647)
        self.seed.setValue(42)
        extra.addRow('子集随机种子', self.seed)
        self.ids = QLineEdit()
        self.ids.setPlaceholderText('例如 1,6,7；映射与顺序会保存')
        extra.addRow('指定编号', self.ids)
        self.range_check = QCheckBox('按实验记录中的关节范围过滤')
        extra.addRow('', self.range_check)
        self.angle_ranges = []
        for title in ('Yaw 范围 · °', 'Pitch 范围 · °'):
            row = QHBoxLayout()
            controls = [spin(-180, -180, 180), spin(180, -180, 180)]
            for widget in controls:
                row.addWidget(widget)
            extra.addRow(title, row)
            self.angle_ranges.extend(controls)
        self.timeout = spin(60, .1, 86400, 1, ' s')
        self.build_timeout = spin(120, .1, 86400, 1, ' s')
        extra.addRow('运行超时', self.timeout)
        extra.addRow('每个构建步骤超时', self.build_timeout)
        self.advanced.content.addLayout(extra)
        inputs = QHBoxLayout()
        self.stdin_edit = QLineEdit()
        self.stdin_edit.setPlaceholderText('交互预设可向程序 stdin 发送一行；程序原有窗口保留')
        self.stdin_button = button('发送输入', self.send_input)
        inputs.addWidget(self.stdin_edit, 1)
        inputs.addWidget(self.stdin_button)
        self.advanced.content.addLayout(inputs)
        tools = QHBoxLayout()
        tools.addWidget(button('使用当前模拟实验', self.use_current_dataset))
        self.load_button = button('打开实验记录…', self.open_record)
        tools.addWidget(self.load_button)
        self.compare_button = button('重复性 / 子集摘要', self.show_comparison)
        tools.addWidget(self.compare_button)
        self.raw_button = button('原始日志', self.show_raw_logs)
        tools.addWidget(self.raw_button)
        tools.addStretch()
        self.advanced.content.addLayout(tools)
        self.advanced.content.addWidget(label('执行前需确认实际参数与目录。B 类诊断依据声明的输入模型，不猜测未知程序的内部转换。', 'Notice', True))
        run_layout.addWidget(self.advanced)
        actions = QHBoxLayout()
        self.run_button = button('开始标定', self.start, primary=True)
        self.stop_button = button('停止', self.stop)
        actions.addWidget(self.run_button)
        actions.addWidget(self.stop_button)
        self.run_hint = label('选择预设及输入路径', 'Muted')
        actions.addWidget(self.run_hint, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(130)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        actions.addWidget(self.progress)
        run_layout.addLayout(actions)
        self.run_scroll = scroll(run_panel)
        self.run_scroll.setMinimumHeight(265)
        self.run_scroll.setMaximumHeight(280)
        layout.addWidget(self.run_scroll)
        metrics = QHBoxLayout()
        self.metric_values = []
        for title_text, unit in (('旋转误差', '°'), ('平移误差', 'mm'), ('标定板一致性 · 输入 B', '° / mm'), ('图像 / 运动状态', '')):
            metric = panel()
            metric_layout = QVBoxLayout(metric)
            metric_layout.setContentsMargins(15, 9, 15, 9)
            metric_layout.setSpacing(2)
            metric_layout.addWidget(label(title_text, 'Eyebrow'))
            row = QHBoxLayout()
            value = label('—', 'Metric')
            value.setStyleSheet('font-size: 21px; font-weight: 700;')
            self.metric_values.append(value)
            row.addWidget(value)
            row.addWidget(label(unit, 'Muted'))
            row.addStretch()
            metric_layout.addLayout(row)
            metrics.addWidget(metric, 1)
        layout.addLayout(metrics)
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(115)
        comparison = QWidget()
        comparison_layout = QVBoxLayout(comparison)
        comparison_layout.setContentsMargins(10, 8, 10, 8)
        row = QHBoxLayout()
        row.addWidget(label('关联运行'))
        self.record_selector = QComboBox()
        self.record_selector.currentIndexChanged.connect(self.select_record)
        row.addWidget(self.record_selector, 1)
        self.result_note = label('尚无结果', 'Muted')
        row.addWidget(self.result_note)
        comparison_layout.addLayout(row)
        self.results_table = QTableWidget(0, 6)
        self.results_table.setHorizontalHeaderLabels(['候选 / 算法', 'R / t 来源', '旋转误差 °', '平移误差 mm', '合法性 / 评价', '程序推荐（原始）'])
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setWordWrap(False)
        self.results_table.verticalHeader().setDefaultSectionSize(23)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results_table.itemSelectionChanged.connect(self.select_candidate)
        comparison_layout.addWidget(self.results_table, 1)
        self.tabs.addTab(comparison, '算法对比')
        view = QWidget()
        view_layout = QVBoxLayout(view)
        self.view_button = button('打开真值 / 估计外参 3D 对比', self.open_3d)
        view_layout.addWidget(self.view_button)
        self.matrix_view = QPlainTextEdit()
        self.matrix_view.setReadOnly(True)
        self.matrix_view.setPlaceholderText('选择合法候选后显示该运行的统一 T_G_C。动态外参模型不伪造全局真值。')
        view_layout.addWidget(self.matrix_view, 1)
        self.tabs.addTab(view, '3D 对比')
        self.frames_table = QTableWidget(0, 6)
        self.frames_table.setHorizontalHeaderLabels(['输入 / 原始 ID', 'PnP RMSE px', 'B/A 旋转差 °', 'B/A 平移差 mm', 'B 板平移离散 mm', '图像状态'])
        self.frames_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.frames_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.frames_table, '逐帧分析')
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(4000)
        self.tabs.addTab(self.log_view, '运行日志')
        layout.addWidget(self.tabs, 1)
        self.option_widgets = [self.kind, self.repetitions, self.subset_mode, self.subset_count, self.seed, self.ids, self.range_check, *self.angle_ranges, self.timeout, self.build_timeout]
        for widget in self.option_widgets:
            signal = widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.toggled if isinstance(widget, QCheckBox) else widget.textChanged if isinstance(widget, QLineEdit) else widget.valueChanged
            signal.connect(self.options_changed)

    def set_draft(self, key, value):
        self.state.edit(lambda p: setattr(p.calibration, key, value))
        self._refresh_buttons()

    def refresh(self):
        draft = self.state.project.calibration
        if draft.preset_path != self._preset_key:
            try:
                self._preset = baseline_preset() if draft.preset_path == 'builtin:opencv' else AdapterPreset.load(draft.preset_path) if draft.preset_path else None
                self._preset_key = draft.preset_path
            except (ValueError, OSError) as exc:
                self._preset = None
                self.entry_detail.setText('预设加载失败：' + str(exc))
        with QSignalBlocker(self.program):
            self.program.clear()
            self.program.addItems(['选择标定程序预设…', '选择已编译可执行文件…', '选择 CMake 工程…', '选择 C++ 源文件…', 'OpenCV 基准（已知双轴运动学）', '导入已有预设 JSON…'])
            if self._preset is not None:
                self.program.addItem(self._preset.name)
                self.program.setCurrentIndex(6)
        for key, field in self.paths.items():
            field.set_path(getattr(draft, key))
        self.config.set_path(draft.config_file)
        options = draft.run_options
        self._refreshing = True
        try:
            subset = options.get('subset', {})
            self.kind.setCurrentIndex(max(0, self.kind.findData(options.get('experiment_kind', 'single'))))
            self.repetitions.setValue(options.get('repetitions', 3))
            self.subset_mode.setCurrentIndex(max(0, self.subset_mode.findData(subset.get('mode', 'all'))))
            self.subset_count.setValue(subset.get('count', 15))
            self.seed.setValue(subset.get('seed', 42))
            self.ids.setText(','.join(str(v) for v in subset.get('ids', [])))
            self.range_check.setChecked(subset.get('yaw_range_deg') is not None or subset.get('pitch_range_deg') is not None)
            for widgets, key in ((self.angle_ranges[:2], 'yaw_range_deg'), (self.angle_ranges[2:], 'pitch_range_deg')):
                for widget, value in zip(widgets, subset.get(key) or [-180, 180]):
                    widget.setValue(value)
            self.timeout.setValue(options.get('timeout_s', 60))
            self.build_timeout.setValue(options.get('build_timeout_s', 120))
        finally:
            self._refreshing = False
        if self._preset is not None:
            self.entry_detail.setText(f'{self._preset.name} · 预设 {self._preset.preset_version} · {self._preset.entry_kind}\n{self._preset.entry_path}\n输入模型：{self._preset.input_model}；{self._preset.input_model_description or "未声明程序内部运动关系"}')
        elif draft.entry_path:
            self.entry_detail.setText('已选入口：' + draft.entry_path + '；请通过管理预设配置参数与输出规则。')
        self._refresh_buttons()

    def choose_program(self, index):
        if index in (0, 6) or self._job is not None:
            return
        if index == 4:
            self.set_preset(baseline_preset(), 'builtin:opencv')
        elif index == 5:
            path, _ = QFileDialog.getOpenFileName(self, '导入程序适配预设', str(self.registry), '预设 (*.json)')
            if path:
                try:
                    self.set_preset(AdapterPreset.load(path), path)
                except (ValueError, OSError) as exc:
                    self.state.message.emit(str(exc), True)
        else:
            kind = {1: 'executable', 2: 'cmake', 3: 'cpp'}[index]
            filters = {'executable': '所有文件 (*)', 'cmake': 'CMake 工程 (CMakeLists.txt)', 'cpp': 'C++ 源码 (*.cpp *.cc *.cxx)'}[kind]
            path, _ = QFileDialog.getOpenFileName(self, '选择标定程序入口', str(Path.home()), filters)
            if path:
                self.state.edit(lambda p: (setattr(p.calibration, 'entry_kind', kind), setattr(p.calibration, 'entry_path', path)))
                self.manage_preset(initial=AdapterPreset(entry_kind=kind, entry_path=path))
        self.refresh()

    def set_preset(self, preset, path):
        self._preset, self._preset_key = preset, path
        def mutate(project):
            project.calibration.preset_path = path
            project.calibration.entry_kind = preset.entry_kind
            project.calibration.entry_path = preset.entry_path
        self.state.edit(mutate)
        self.refresh()

    def manage_preset(self, checked=False, initial=None):
        draft = self.state.project.calibration
        preset = initial or self._preset or AdapterPreset(entry_path=draft.entry_path, entry_kind=draft.entry_kind or 'executable')
        dialog = AdapterDialog(preset, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.registry.mkdir(parents=True, exist_ok=True)
            path, _ = QFileDialog.getSaveFileName(self, '保存程序适配预设', str(self.registry / 'adapter.json'), '预设 (*.json)')
            if path:
                try:
                    dialog.value.save(path)
                    self.set_preset(dialog.value, path)
                except (ValueError, OSError) as exc:
                    self.state.message.emit('预设保存失败：' + str(exc), True)

    def options(self):
        ids = [int(part.strip()) for part in self.ids.text().split(',') if part.strip()]
        subset = SubsetSpec(mode=self.subset_mode.currentData(), count=self.subset_count.value(), seed=self.seed.value(), ids=ids,
                            yaw_range_deg=[w.value() for w in self.angle_ranges[:2]] if self.range_check.isChecked() else None,
                            pitch_range_deg=[w.value() for w in self.angle_ranges[2:]] if self.range_check.isChecked() else None)
        subset.validate()
        return {'experiment_kind': self.kind.currentData(), 'repetitions': self.repetitions.value(), 'subset': asdict(subset),
                'timeout_s': self.timeout.value(), 'build_timeout_s': self.build_timeout.value()}

    def options_changed(self, *_):
        if self._refreshing:
            return
        if self.kind.currentData() == 'subsets' and self.subset_mode.currentData() != 'random':
            with QSignalBlocker(self.subset_mode):
                self.subset_mode.setCurrentIndex(self.subset_mode.findData('random'))
        try:
            values = self.options()
            self.state.edit(lambda p: setattr(p.calibration, 'run_options', values))
        except ValueError:
            pass  # A partially typed ID remains visible and cannot be executed.
        self._refresh_buttons()

    def request(self):
        if self._preset is None:
            raise ValueError('请选择并配置程序预设')
        draft = self.state.project.calibration
        values = self.options()
        return ExperimentRequest(preset=self._preset.to_dict(), pictures_dir=draft.pictures_dir, quaternion_dir=draft.quaternion_dir,
                                 config_file=draft.config_file, output_parent=str(Path(draft.output_yaml).expanduser().resolve().parent),
                                 output_yaml=draft.output_yaml, subset=SubsetSpec(**values.pop('subset')), **values)

    def _refresh_buttons(self):
        busy = self._job is not None
        error = ''
        try:
            self.options()
            if self._preset is None:
                raise ValueError('请选择并配置标定程序预设')
            for key in ('pictures_dir', 'quaternion_dir'):
                if not Path(getattr(self.state.project.calibration, key)).is_dir() or not getattr(self.state.project.calibration, key):
                    raise ValueError('请选择已有图片和 TXT 目录')
            output = Path(self.state.project.calibration.output_yaml).expanduser()
            if not self.state.project.calibration.output_yaml or output.suffix.lower() not in ('.yaml', '.yml') or not output.parent.is_dir() or output.exists():
                raise ValueError('请选择尚不存在的输出 YAML；已有结果不会被覆盖')
        except (ValueError, OSError) as exc:
            error = str(exc)
        self.run_button.setEnabled(not busy and not error)
        self.run_button.setToolTip(error or '先准备实际执行计划，再显示命令确认')
        self.stop_button.setEnabled(busy)
        for widget in [self.program, self.manage_button, self.config, self.load_button, *self.paths.values(), *self.option_widgets]:
            widget.setEnabled(not busy)
        self.stdin_button.setEnabled(busy and self._job.mode == 'run' and self._preset is not None and self._preset.requires_interaction)
        self.stdin_edit.setEnabled(self.stdin_button.isEnabled())
        self.raw_button.setEnabled(self.current_record is not None)
        self.record_selector.setEnabled(not busy)
        self.compare_button.setEnabled(bool(self.records))
        self.view_button.setEnabled(self.current_candidate is not None and self.current_candidate.get('status') == 'valid' and self.current_record is not None and self.current_record.get('T_G_C_true') is not None)
        if not busy:
            self.run_hint.setText(error or '就绪 · 运行前检查并确认实际命令')
            if not self.records and self.status_label.text() in ('未配置', '就绪'):
                self.status_label.setText('未配置' if error else '就绪')

    def _start_job(self, mode, action):
        self._job = ExperimentJob(mode, action, self)
        self._job.event.connect(self._event)
        self._job.finished.connect(self._job_finished)
        self._refresh_buttons()
        self.progress.setRange(0, 0)
        self._job.start()

    def start(self):
        if self._job is not None:
            return
        try:
            request = self.request()
            self.status_label.setText('准备命令预览')
            self._start_job('plan', lambda cancel, event, stdin: self.service.plan(request))
        except (ValueError, OSError) as exc:
            self.state.message.emit(str(exc), True)

    def confirm_plan(self, plan):
        dialog = QDialog(self)
        dialog.setWindowTitle('确认本次构建与运行命令')
        dialog.resize(920, 670)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label('检查程序、实际参数、工作目录、样本编号和输出位置后执行。原始数据集不会作为工作目录；GT 不放入适配输入。', 'Notice', True))
        text = QPlainTextEdit()
        text.setReadOnly(True)
        lines = [f"数据内容 ID：{plan['source_content_id']}", f"预设 ID：{plan['preset_id']}", *plan['warnings']]
        for run in plan['runs']:
            lines += ['', '实验 ' + run['run_id'], '样本：' + str(run['sample_ids']), '工作目录：' + run['cwd'], '导出 YAML：' + str(run['export_yaml'])]
            lines += ['构建：' + shlex.join(c) for c in run['build_commands']]
            lines += ['运行：' + shlex.join(run['command'])]
        text.setPlainText('\n'.join(lines))
        layout.addWidget(text, 1)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText('确认执行')
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _job_finished(self):
        job = self._job
        if job is None:
            return
        self._job = None
        job.deleteLater()
        if self._closing:
            return
        if job.error:
            self.status_label.setText('失败')
            self.state.message.emit(job.error, True)
        elif job.mode == 'plan':
            if not job.cancel_event.is_set() and self.confirm_plan(job.result):
                plan = job.result
                self.status_label.setText('准备输入')
                self._start_job('run', lambda cancel, event, stdin: self.service.execute(plan, confirmed=True, confirmation_source='gui_command_dialog', cancel_event=cancel, event=event, stdin_queue=stdin))
                return
            self.status_label.setText('已取消')
        else:
            self.attach_summary(job.result)
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if self.records else 0)
        self._refresh_buttons()

    def _event(self, event):
        if self._closing:
            return
        if event['kind'] == 'log':
            self.log_view.appendPlainText(f"[{event.get('phase', '')}/{event['stream']}] " + event['text'].rstrip())
        elif event['kind'] == 'phase':
            state = event.get('status')
            titles = {'starting': '启动中', 'running': '运行中', 'waiting_interaction': '等待人工交互', 'succeeded': '解析与独立评价', 'failed': '程序异常退出', 'timed_out': '超时', 'cancelled': '已取消'}
            self.status_label.setText('构建中' if event.get('phase', '').startswith('build') and state in ('starting', 'running') else titles.get(state, state or '运行中'))
        elif event['kind'] == 'finished':
            self.log_view.appendPlainText(f"运行 {event['run_id']} → {event['status']}\n记录：{event['record_file']}")

    def stop(self):
        if self._job is not None:
            self._job.cancel_event.set()
            self.status_label.setText('正在停止…')

    def send_input(self):
        if self._job is not None:
            self._job.stdin_queue.put(self.stdin_edit.text())
            self.stdin_edit.clear()

    def attach_summary(self, summary):
        self.summary = summary
        self.records = summary.get('records', [])
        with QSignalBlocker(self.record_selector):
            self.record_selector.clear()
            for record in self.records:
                dataset_name = Path(record['dataset_root']).name if record.get('dataset_root') else '外部输入'
                self.record_selector.addItem(f"{record['run_id'][:10]} · {record['status']} · {len(record['sample_ids'])} 样本 · {dataset_name}")
        self.select_record(0)
        states = [r['status'] for r in self.records]
        self.status_label.setText('已取消' if 'cancelled' in states or summary.get('cancelled') else '已完成' if states and all(v == 'succeeded' for v in states) else '存在失败 / 不可评价')
        if states and all(v == 'succeeded' for v in states):
            evaluations = [c.get('evaluation', {}) for record in self.records for c in record.get('candidates', [])]
            if any(value.get('ground_truth_errors') is None for value in evaluations):
                self.status_label.setText('已完成（存在不可评价结果）')
            elif any(value.get('flags') for value in evaluations):
                self.status_label.setText('已完成（有诊断提示）')
        if self.records:
            self.state.message.emit(f"实验已记录：{self.records[-1]['record_file']}", any(v != 'succeeded' for v in states))
        self._refresh_buttons()

    def select_record(self, index):
        self.current_record = self.records[index] if 0 <= index < len(self.records) else None
        self.current_candidate = None
        candidates = self.current_record.get('candidates', []) if self.current_record else []
        self.results_table.setRowCount(0)
        self.results_table.setRowCount(len(candidates))
        for row, candidate in enumerate(candidates):
            evaluation = candidate.get('evaluation', {})
            errors = evaluation.get('ground_truth_errors') or {}
            values = [candidate['name'], candidate.get('rotation_source', '—') + ' / ' + candidate.get('translation_source', '—'),
                      fmt(errors.get('rotation_error_deg')), fmt(errors.get('translation_error_mm')),
                      candidate['status'] + ' / ' + evaluation.get('status', '未评价'), '是（不代表最佳）' if candidate.get('program_recommended') else '—']
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(json.dumps(candidate, ensure_ascii=False, indent=2))
                self.results_table.setItem(row, column, item)
        self.result_note.setText(self.current_record['status'] if self.current_record else '尚无结果')
        self.result_note.setToolTip(json.dumps({'record':self.current_record.get('record_file'), 'dataset':self.current_record.get('dataset_root'), 'preset':self.current_record.get('preset',{}).get('name'), 'warnings':self.current_record.get('warnings',[])}, ensure_ascii=False, indent=2) if self.current_record else '')
        if self.current_record is not None:
            self.log_view.setPlainText(self.record_logs(self.current_record))
        if candidates:
            self.results_table.selectRow(0)
        else:
            self.select_candidate()
        self._refresh_buttons()

    def select_candidate(self):
        row = self.results_table.currentRow()
        candidates = self.current_record.get('candidates', []) if self.current_record else []
        self.current_candidate = candidates[row] if 0 <= row < len(candidates) else None
        candidate = self.current_candidate or {}
        evaluation = candidate.get('evaluation', {})
        errors = evaluation.get('ground_truth_errors') or {}
        self.metric_values[0].setText(fmt(errors.get('rotation_error_deg')) if errors else '不适用' if self.current_record else '—')
        self.metric_values[1].setText(fmt(errors.get('translation_error_mm')) if errors else '不适用' if self.current_record else '—')
        board = evaluation.get('board_consistency_B_declared_input_motion') or {}
        self.metric_values[2].setText(f"{fmt(board.get('rotation_rms_deg'))} / {fmt(board.get('translation_rms_mm'))}" if board.get('status') == 'evaluated' else '无法重建' if self.current_record else '—')
        context = self.current_record.get('evaluation_context', {}) if self.current_record else {}
        observations = context.get('observations', [])
        motion = context.get('motion_condition', {}).get('status')
        motion_text = {'motion_sufficient_for_baseline': '基准条件充分', 'degenerate_motion': '运动退化', 'data_insufficient': '数据不足', 'coordinate_information_insufficient': '模型未知'}.get(motion, '未检查')
        self.metric_values[3].setText(f"{sum(o['status'] == 'valid' for o in observations)}/{len(observations)} · {motion_text}" if observations else '未评价' if self.current_record else '—')
        for widget in self.metric_values:
            widget.setToolTip(json.dumps({'evaluation': evaluation, 'motion_condition': context.get('motion_condition'), 'record': self.current_record.get('run_id') if self.current_record else None}, ensure_ascii=False, indent=2))
        self.matrix_view.setPlainText(json.dumps({'run_id': self.current_record.get('run_id') if self.current_record else None, 'candidate': candidate.get('name'), 'T_G_C_est_mm': candidate.get('T_G_C'), 'T_G_C_true_mm': self.current_record.get('T_G_C_true') if self.current_record else None, 'evaluation': evaluation}, ensure_ascii=False, indent=2))
        differences = {r['input_id']: r for r in context.get('per_frame_input_vs_truth', [])}
        mapping = {r['input_id']: r for r in self.current_record.get('input_mapping', [])} if self.current_record else {}
        self.frames_table.setRowCount(len(observations))
        board_displacements = iter(board.get('per_frame_translation_mm', []))
        for row, observation in enumerate(observations):
            item = mapping.get(row + 1, {})
            delta = differences.get(row + 1, {})
            displacement = next(board_displacements, None) if observation['status'] == 'valid' else None
            values = [f"{row + 1} / {item.get('source_id', '—')}", fmt(observation.get('reprojection_rmse_px')), fmt(delta.get('rotation_error_deg')), fmt(delta.get('translation_error_mm')), fmt(displacement), observation['status']]
            for column, value in enumerate(values):
                self.frames_table.setItem(row, column, QTableWidgetItem(value))
        self._refresh_buttons()

    def use_current_dataset(self):
        page = getattr(self.window(), 'data_page', None)
        dataset = page.dataset if page is not None else None
        if dataset is None:
            self.state.message.emit('请先在数据页生成或打开一个模拟实验。', True)
            return
        self.set_draft('pictures_dir', str(dataset.root / 'pictures'))
        self.set_draft('quaternion_dir', str(dataset.root / 'txt'))
        self.set_draft('config_file', '')
        self.refresh()

    def open_record(self):
        path, _ = QFileDialog.getOpenFileName(self, '打开 run.json 或 batch_*.json', str(Path(self.state.project.calibration.output_yaml).parent), '实验记录 (*.json)')
        if path:
            try:
                value = json.loads(Path(path).read_text(encoding='utf-8'))
                self.attach_summary(value if 'records' in value else {'records': [load_run(path)]})
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.state.message.emit('记录加载失败：' + str(exc), True)

    def show_comparison(self):
        if self.records:
            self.show_text('程序重复性 / 子集敏感性摘要', json.dumps(compare_run_records(self.records), ensure_ascii=False, indent=2))

    def show_raw_logs(self):
        if self.current_record is None:
            return
        self.show_text('原始标准输出 / 错误输出（每文件预览前 2 MB）', self.record_logs(self.current_record))

    def record_logs(self, record):
        root = Path(record['record_file']).parent
        blocks = ['关联运行：' + record['run_id'], str(root), record.get('error') or '']
        for process in record.get('processes', []):
            for key in ('stdout_file', 'stderr_file'):
                path = root / process[key]
                if path.is_file():
                    blocks.append('\n' + str(path) + '\n' + path.read_bytes()[:2_000_000].decode('utf-8', errors='replace'))
        if record.get('status') == 'parse_failed':
            result = Path(record.get('raw_result_file', ''))
            if result.is_file():
                blocks.append('\n原始结果：' + str(result) + '\n' + result.read_bytes()[:2_000_000].decode('utf-8', errors='replace'))
        return '\n'.join(blocks)

    def show_text(self, title, text):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        value = QPlainTextEdit()
        value.setReadOnly(True)
        value.setPlainText(text)
        layout.addWidget(value)
        dialog.exec()

    def open_3d(self):
        if self.current_record is None or self.current_candidate is None or self.current_record.get('T_G_C_true') is None:
            return
        from gimbal_lab.gui.result_view import ExtrinsicDialog
        dialog = ExtrinsicDialog(self.current_record['T_G_C_true'], self.current_candidate['T_G_C'], self.current_candidate['name'], self)
        self.comparison_dialogs.append(dialog)
        dialog.show()

    def shutdown(self):
        self._closing = True
        if self._job is not None:
            self._job.cancel_event.set()
            if not self._job.wait(15000):
                return False
        for dialog in self.comparison_dialogs:
            try:
                dialog.close()
            except RuntimeError:
                pass
        return True


def fmt(value):
    return '—' if value is None else f'{value:.6g}'
