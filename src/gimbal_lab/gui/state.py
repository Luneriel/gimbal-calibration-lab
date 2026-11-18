from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from gimbal_lab.domain.models import Project, preset_scene
from gimbal_lab.domain.engine import GeometryEngine
from gimbal_lab.domain.persistence import load_project, save_project


class AppState(QObject):
    scene_changed = Signal(str)
    project_changed = Signal()
    selection_changed = Signal(str)
    dirty_changed = Signal(bool)
    message = Signal(str, bool)

    def __init__(self):
        super().__init__()
        self.project = Project()
        self.geometry = GeometryEngine(self.project.scene).solve()
        self.selected = "camera"
        self.path: Path | None = None
        self.dirty = False

    def set_dirty(self, value: bool) -> None:
        self.dirty = value
        self.dirty_changed.emit(value)

    def select(self, key: str) -> None:
        if key != self.selected:
            self.selected = key
            self.selection_changed.emit(key)

    def edit(self, mutator: Callable[[Project], None], reason: str = "settings") -> bool:
        candidate = deepcopy(self.project)
        try:
            mutator(candidate)
            candidate.validate()
            changed_scene = candidate.scene != self.project.scene
            geometry = GeometryEngine(candidate.scene).solve() if changed_scene else self.geometry
        except (ValueError, TypeError, OverflowError) as exc:
            self.message.emit(str(exc), True)
            return False
        if candidate == self.project:
            return True
        if changed_scene and not reason.startswith("scene:"):
            reason = "scene:property"
        if changed_scene and reason != "scene:joint":
            candidate.scene.preset = "自定义场景"
        self.project = candidate
        self.geometry = geometry
        self.set_dirty(True)
        if reason.startswith("scene:"):
            self.scene_changed.emit(reason)
        return True

    def set_joint(self, key: str, value: float) -> bool:
        return self.edit(lambda p: setattr(getattr(p.scene, key), "angle_deg", value), "scene:joint")

    def apply_preset(self, name: str) -> None:
        self.project.scene = preset_scene(name)
        self.geometry = GeometryEngine(self.project.scene).solve()
        self.set_dirty(True)
        self.scene_changed.emit("scene:reset")
        self.message.emit(f"已载入场景预设：{name}", False)

    def save(self, path: Path) -> None:
        save_project(self.project, path)
        self.path = path
        self.set_dirty(False)
        self.message.emit(f"项目已保存：{path}", False)

    def load(self, path: Path) -> None:
        project = load_project(path)
        geometry = GeometryEngine(project.scene).solve()
        self.project = project
        self.geometry = geometry
        self.path = path
        self.set_dirty(False)
        self.project_changed.emit()
        self.scene_changed.emit("scene:reset")
        self.message.emit(f"项目已加载：{path.name}", False)

    def new(self) -> None:
        self.project = Project()
        self.geometry = GeometryEngine(self.project.scene).solve()
        self.path = None
        self.set_dirty(False)
        self.project_changed.emit()
        self.scene_changed.emit("scene:reset")
        self.message.emit("已新建项目", False)

