"""First-connection editor for versioned adapter presets; saving does not execute."""
from dataclasses import asdict
import json
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from gimbal_lab.experiments.schema import AdapterPreset
from gimbal_lab.gui.widgets import button, label, scroll


class AdapterDialog(QDialog):
    def __init__(self, preset, parent=None):
        super().__init__(parent)
        self.setWindowTitle('标定程序适配预设')
        self.resize(820, 820)
        self.value = None
        layout = QVBoxLayout(self)
        layout.addWidget(label('配置程序、数据接口和输出约定；保存预设不会执行程序。参数使用 JSON 字符串数组。', 'Notice', True))
        content = QWidget()
        form = QFormLayout(content)
        self.fields = {}
        data = asdict(preset)
        for key, title in (('name', '程序名称'), ('preset_version', '预设版本')):
            self.fields[key] = QLineEdit(data[key])
            form.addRow(title, self.fields[key])
        for key, title, values in (('entry_kind', '入口形式', ['executable', 'cmake', 'cpp']),
                                   ('organization', '输入文件组织', ['separate', 'mixed']),
                                   ('input_model', '输入运动模型', ['unknown', 'm3_known_pitch_chain'])):
            combo = QComboBox()
            combo.addItems(values)
            combo.setCurrentText(data[key])
            self.fields[key] = combo
            form.addRow(title, combo)
        for key, title in (('entry_path', '程序 / CMakeLists / CPP'), ('source_dir', '关联工程目录')):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(data[key])
            self.fields[key] = edit
            row_layout.addWidget(edit, 1)
            row_layout.addWidget(button('浏览…', lambda checked=False, k=key: self.browse(k)))
            form.addRow(title, row)
        for key, title in (('cmake_target', 'CMake 构建目标'), ('executable_relative', '产物相对构建目录'),
                           ('working_directory', '运行工作目录'), ('input_model_description', '输入/轴向关系说明')):
            self.fields[key] = QLineEdit(data[key])
            form.addRow(title, self.fields[key])
        self.arguments = QPlainTextEdit(json.dumps(data['arguments'], ensure_ascii=False, indent=2))
        self.arguments.setMinimumHeight(100)
        self.arguments.setMaximumHeight(140)
        form.addRow('运行参数数组', self.arguments)
        form.addRow('', label('占位符：{pictures} {quaternions} {input_dir} {config} {motion} {output} {run_dir} {source_dir} {build_dir}', 'Muted', True))
        self.interactive = QCheckBox('程序需要人工窗口或终端交互')
        self.interactive.setChecked(data['requires_interaction'])
        form.addRow('', self.interactive)
        self.source = QComboBox()
        self.source.addItems(['file', 'stdout', 'markers'])
        self.source.setCurrentText(data['output']['source'])
        form.addRow('结果来源', self.source)
        self.direction = QComboBox()
        self.direction.addItems(['T_G_C', 'T_C_G', 'T_U_V', 'T_V_U'])
        self.direction.setCurrentText(data['output']['direction'])
        form.addRow('原始输出方向', self.direction)
        self.unit = QComboBox()
        self.unit.addItems(['mm', 'm'])
        self.unit.setCurrentText(data['output']['translation_unit'])
        form.addRow('原始平移单位', self.unit)
        for key in (*self.fields, 'arguments', 'requires_interaction'):
            data.pop(key)
        for key in ('source', 'direction', 'translation_unit'):
            data['output'].pop(key)
        self.extra = QPlainTextEdit(json.dumps(data, ensure_ascii=False, indent=2))
        self.extra.setMinimumHeight(150)
        form.addRow('高级解析 / 构建配置 JSON', self.extra)
        form.addRow('', label('separate：pictures 与 txt 分开；mixed：连续 JPG/TXT 同目录。unknown 保留真实四元数，但无法完整重现程序输入运动。已知模型需明确假设；不支持从孤立 CPP 猜测依赖。', 'Muted', True))
        layout.addWidget(scroll(content), 1)
        self.error = label('', 'Notice', True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse(self, key):
        if key == 'source_dir':
            path = QFileDialog.getExistingDirectory(self, '选择关联 CMake 工程目录', self.fields[key].text() or str(Path.home()))
        else:
            path, _ = QFileDialog.getOpenFileName(self, '选择程序入口', self.fields[key].text() or str(Path.home()), '所有文件 (*)')
        if path:
            self.fields[key].setText(path)

    def validate_and_accept(self):
        try:
            data = json.loads(self.extra.toPlainText())
            for key, widget in self.fields.items():
                data[key] = widget.currentText() if isinstance(widget, QComboBox) else widget.text().strip()
            data['arguments'] = json.loads(self.arguments.toPlainText())
            data['requires_interaction'] = self.interactive.isChecked()
            data.setdefault('output', {}).update(source=self.source.currentText(), direction=self.direction.currentText(), translation_unit=self.unit.currentText())
            self.value = AdapterPreset.from_dict(data)
        except (ValueError, TypeError, AttributeError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
