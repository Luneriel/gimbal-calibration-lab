"""Versioned JSON project storage with atomic replacement."""
import json
import os
from pathlib import Path
import tempfile

from dataclasses import asdict

from gimbal_lab.domain.models import Project, Scene, coordinate_metadata, validate_metadata


def save_project(project: Project, path: Path) -> None:
    _write_json(project.to_dict(), path)


def _write_json(data: dict, path: Path) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".gimbal-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_project(path: Path) -> Project:
    return Project.from_dict(_read_json(path))


def _read_json(path: Path) -> dict:
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"项目文件不是有效的 UTF-8 JSON：{exc}") from exc


def save_scene(scene: Scene, path: Path) -> None:
    scene.validate()
    _write_json({"kind": "gimbal_lab.scene", "schema_version": 2,
                 "conventions": coordinate_metadata(), "scene": asdict(scene)}, path)


def load_scene(path: Path) -> Scene:
    data = _read_json(path)
    if not isinstance(data, dict) or data.get("kind") != "gimbal_lab.scene" or type(data.get("schema_version")) is not int or data["schema_version"] != 2:
        raise ValueError("不支持的独立场景格式（需要 gimbal_lab.scene / schema_version=2）")
    if set(data) != {"kind", "schema_version", "conventions", "scene"}:
        raise ValueError("独立场景文件字段缺失或包含无效字段")
    validate_metadata(data["conventions"])
    return Scene.from_dict(data["scene"])

