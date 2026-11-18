"""Independent static extrinsic comparison; never mutates the editing scene."""
import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout

from gimbal_lab.gui.widgets import label


class ExtrinsicDialog(QDialog):
    def __init__(self, truth, estimate, name, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('相机外参 3D 对比 · G 坐标系')
        self.resize(980, 720)
        layout = QVBoxLayout(self)
        layout.addWidget(label(name + ' · 蓝色为真值，紫色为估计；平移单位 mm。', 'Section'))
        self.plotter = QtInteractor(self, auto_update=False)
        self.plotter.set_background('#101e31')
        layout.addWidget(self.plotter.interactor, 1)
        truth, estimate = np.asarray(truth), np.asarray(estimate)
        extent = max(40., np.linalg.norm(truth[:3, 3]), np.linalg.norm(estimate[:3, 3]))
        length = extent * .45
        for title, transform, color in (('C_true', truth, '#64b8ff'), ('C_est', estimate, '#e3a1ff')):
            origin = transform[:3, 3]
            self.plotter.add_mesh(pv.Sphere(radius=extent * .015, center=origin), color=color)
            for index, axis in enumerate('XYZ'):
                end = origin + transform[:3, index] * length
                self.plotter.add_mesh(pv.Line(origin, end), color=color, line_width=5)
                self.plotter.add_point_labels([end], [title + '_' + axis], font_size=12, text_color=color, shape_opacity=.2)
        self.plotter.add_mesh(pv.Sphere(radius=extent * .02), color='#b9cbe7')
        self.plotter.add_point_labels([[0., 0., 0.]], ['G'], text_color='white', font_size=14)
        self.plotter.add_axes()
        self.plotter.show_grid(color='#536780')
        self.plotter.view_isometric()
        self.plotter.reset_camera()
        layout.addWidget(label('仅比较该运行已解析的 T_G_C；此视图与场景编辑器独立。', 'Muted', True))
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self.plotter.render)
        self.render_timer.start(150)

    def closeEvent(self, event):
        self.render_timer.stop()
        self.plotter.close()
        super().closeEvent(event)
