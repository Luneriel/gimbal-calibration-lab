"""Configuration; mm/degree fields, explicit frame metadata, no Qt imports."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from copy import deepcopy
import math
from typing import Any

from gimbal_lab.domain.rigid import unit_axis, validate_rotation

SCHEMA_VERSION = 2


def coordinate_metadata() -> dict:
    return {
        "length_unit": "mm", "angle_unit": "deg", "handedness": "right",
        "vectors": "column", "transform": "T_A_B maps B to A",
        "euler": "Rz(yaw) @ Ry(pitch) @ Rx(roll)",
        "quaternion": "Hamilton wxyz, I to A",
        "world_axes": "X_forward,Y_left,Z_up",
        "camera_axes": "X_right,Y_down,Z_forward",
        "board_corner_order": "row_major,column_fastest",
        "imu_reference": "R_A_W; A and W share origin",
        "frames": {"W": "world", "B": "base", "Y": "yaw", "P": "pitch", "C": "camera", "I": "imu", "A": "absolute_reference", "T": "board", "G": "gimbal"},
    }


def validate_metadata(data) -> None:
    if data != coordinate_metadata():
        raise ValueError("坐标或单位元数据不匹配：要求 mm / deg、右手列向量及预定义坐标系")


NAMES = {
    "world": "世界坐标系", "base": "固定底座", "yaw": "Yaw 机构",
    "pitch": "Pitch 机构", "camera": "相机", "imu": "IMU", "board": "标定板",
}
MOUNTS = ("pitch", "yaw", "base")


def _vector(values: Any, size: int, label: str) -> None:
    if not isinstance(values, (tuple, list)) or len(values) != size:
        raise ValueError(f"{label} 必须包含 {size} 个数值")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError(f"{label} 必须为有限数值")


@dataclass
class Pose:
    position_mm: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    # R = Rz(yaw) @ Ry(pitch) @ Rx(roll); components ordered [yaw,pitch,roll].
    euler_zyx_deg: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])

    def validate(self) -> None:
        _vector(self.position_mm, 3, "位置")
        _vector(self.euler_zyx_deg, 3, "安装角")
        if any(abs(v) > 100000 for v in self.position_mm):
            raise ValueError("位置范围为 ±100000 mm")
        if any(abs(v) > 360 for v in self.euler_zyx_deg):
            raise ValueError("安装角范围为 ±360°")


def _validate_pose(value, label):
    if not isinstance(value, Pose):
        raise ValueError(f"{label} 必须为 Pose 配置")
    value.validate()


@dataclass
class Joint:
    installation: Pose = field(default_factory=Pose)
    axis: list[float] = field(default_factory=lambda: [0.0, 0.0, 1.0])
    angle_deg: float = 0.0
    limits_deg: list[float] = field(default_factory=lambda: [-90.0, 90.0])
    child_zero: Pose = field(default_factory=Pose)
    parent: str = "base"
    child: str = "yaw"

    def validate(self) -> None:
        _validate_pose(self.installation, "关节安装")
        _validate_pose(self.child_zero, "子部件零位安装")
        _vector(self.axis, 3, "旋转轴方向")
        unit_axis(self.axis)
        _vector(self.limits_deg, 2, "关节限位")
        lo, hi = self.limits_deg
        if not -180 <= lo < hi <= 180:
            raise ValueError("关节限位须满足 −180° ≤ 下限 < 上限 ≤ 180°")
        if isinstance(self.angle_deg, bool) or not isinstance(self.angle_deg, (int, float)) or not math.isfinite(self.angle_deg):
            raise ValueError("关节角必须为有限数值")
        if not lo <= self.angle_deg <= hi:
            raise ValueError("当前关节角超出可用范围，请先调整角度")


@dataclass
class Camera:
    parent: str = "pitch"
    installation: Pose = field(default_factory=lambda: Pose([80.0, 0.0, 0.0], [-90.0, 0.0, -90.0]))
    width: int = 1280
    height: int = 960
    fx: float = 950.0
    fy: float = 950.0
    cx: float = 640.0
    cy: float = 480.0
    distortion: list[float] = field(default_factory=lambda: [0.0] * 5)

    def validate(self) -> None:
        if self.parent not in MOUNTS:
            raise ValueError("相机挂载对象无效")
        _validate_pose(self.installation, "相机安装")
        if any(type(v) is not int or not 64 <= v <= 8192 for v in (self.width, self.height)):
            raise ValueError("图像尺寸须为 64–8192 的整数")
        _vector([self.fx, self.fy, self.cx, self.cy], 4, "相机内参")
        if not 1 <= self.fx <= 100000 or not 1 <= self.fy <= 100000:
            raise ValueError("焦距须为 1–100000 px 的正数")
        if not 0 <= self.cx < self.width or not 0 <= self.cy < self.height:
            raise ValueError("主点须位于图像范围内，请先调整主点或增大分辨率")
        _vector(self.distortion, 5, "畸变参数")


@dataclass
class Imu:
    parent: str = "pitch"
    installation: Pose = field(default_factory=lambda: Pose([0.0, 0.0, 62.0], [0.0, 0.0, 0.0]))
    reference_rotation_aw: list[list[float]] = field(default_factory=lambda: [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])

    def validate(self) -> None:
        if self.parent not in MOUNTS:
            raise ValueError("IMU 挂载对象无效")
        _validate_pose(self.installation, "IMU 安装")
        validate_rotation(self.reference_rotation_aw)


@dataclass
class GimbalReference:
    parent: str = "pitch"
    installation: Pose = field(default_factory=Pose)

    def validate(self) -> None:
        if self.parent not in MOUNTS:
            raise ValueError("Gimbal 参考系挂载对象无效")
        _validate_pose(self.installation, "G 安装")


@dataclass
class Board:
    kind: str = "chessboard"
    columns: int = 11
    rows: int = 8
    spacing_mm: float = 40.0
    installation: Pose = field(default_factory=lambda: Pose([1000.0, 200.0, 355.0], [-90.0, 0.0, -90.0]))

    def validate(self) -> None:
        _validate_pose(self.installation, "标定板安装")
        if self.kind != "chessboard":
            raise ValueError("当前版本仅支持棋盘格")
        if any(type(v) is not int or not 2 <= v <= 30 for v in (self.columns, self.rows)):
            raise ValueError("内角点数量范围为 2–30")
        if isinstance(self.spacing_mm, bool) or not isinstance(self.spacing_mm, (int, float)) or not math.isfinite(self.spacing_mm) or not 1 <= self.spacing_mm <= 500:
            raise ValueError("角点间距范围为 1–500 mm")


@dataclass
class Scene:
    preset: str = "理想双轴云台"
    base: Pose = field(default_factory=Pose)
    yaw: Joint = field(default_factory=lambda: Joint(Pose([0.0, 0.0, 90.0]), [0.0, 0.0, 1.0], 0.0, [-90.0, 90.0]))
    pitch: Joint = field(default_factory=lambda: Joint(Pose([0.0, 0.0, 125.0]), [0.0, 1.0, 0.0], 0.0, [-60.0, 60.0], parent="yaw", child="pitch"))
    camera: Camera = field(default_factory=Camera)
    imu: Imu = field(default_factory=Imu)
    board: Board = field(default_factory=Board)
    gimbal: GimbalReference = field(default_factory=GimbalReference)

    def validate(self) -> None:
        if not isinstance(self.preset, str):
            raise ValueError("场景预设名称无效")
        for key, kind in (("base", Pose), ("yaw", Joint), ("pitch", Joint), ("camera", Camera), ("imu", Imu), ("board", Board), ("gimbal", GimbalReference)):
            obj = getattr(self, key)
            if not isinstance(obj, kind):
                raise ValueError(f"scene.{key} 配置类型无效")
            obj.validate()
        if (self.yaw.parent, self.yaw.child, self.pitch.parent, self.pitch.child) != ("base", "yaw", "yaw", "pitch"):
            raise ValueError("机构层级必须为 Base → Yaw → Pitch")

    @classmethod
    def from_dict(cls, data: dict) -> Scene:
        result = _decode(cls(), data, {
            "base": {}, "yaw": {"installation": {}, "child_zero": {}},
            "pitch": {"installation": {}, "child_zero": {}},
            "camera": {"installation": {}}, "imu": {"installation": {}},
            "board": {"installation": {}}, "gimbal": {"installation": {}},
        }, "scene")
        result.validate()
        return result


def _decode(default, data, children, path):
    if not isinstance(data, dict):
        raise ValueError(f"{path} 必须为对象")
    allowed = set(default.__dataclass_fields__)
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"{path} 存在无效字段：{', '.join(sorted(unknown))}")
    result = deepcopy(default)
    for key, value in data.items():
        if key in children:
            value = _decode(getattr(default, key), value, children[key], f"{path}.{key}")
        setattr(result, key, deepcopy(value))
    return result


@dataclass
class Sampling:
    mode: str = "自动采样"
    count: int = 30
    yaw_range_deg: list[float] = field(default_factory=lambda: [-30.0, 30.0])
    pitch_range_deg: list[float] = field(default_factory=lambda: [-15.0, 15.0])
    distribution: str = "分层均匀"
    seed: int = 42
    strict: bool = False
    output_dir: str = ""
    max_attempts: int = 0

    def validate(self) -> None:
        if self.mode not in ("自动采样", "手动采样") or self.distribution not in ("分层均匀", "均匀随机"):
            raise ValueError("采样模式或分布无效")
        if type(self.count) is not int or not 3 <= self.count <= 10000:
            raise ValueError("样本数量范围为 3–10000")
        for label, angles in (("Yaw", self.yaw_range_deg), ("Pitch", self.pitch_range_deg)):
            _vector(angles, 2, label + " 采样范围")
            if not -180 <= angles[0] < angles[1] <= 180:
                raise ValueError(label + " 采样范围须满足 −180° ≤ 下限 < 上限 ≤ 180°")
        if type(self.seed) is not int or not 0 <= self.seed <= 2147483647:
            raise ValueError("随机种子范围为 0–2147483647")
        if type(self.strict) is not bool or not isinstance(self.output_dir, str):
            raise ValueError("采样设置格式无效")
        if type(self.max_attempts) is not int or not 0 <= self.max_attempts <= 200000:
            raise ValueError("最大尝试次数须为 0–200000，0 表示自动预算")
        if self.max_attempts and self.max_attempts < self.count:
            raise ValueError("最大尝试次数不能小于目标样本数")


@dataclass
class CalibrationDraft:
    entry_kind: str = ""
    entry_path: str = ""
    pictures_dir: str = ""
    quaternion_dir: str = ""
    output_yaml: str = ""
    config_file: str = ""
    preset_path: str = ""
    run_options: dict = field(default_factory=dict)

    def validate(self) -> None:
        if any(not isinstance(v, str) for k, v in asdict(self).items() if k != "run_options"):
            raise ValueError("标定路径须为字符串")
        if not isinstance(self.run_options, dict):
            raise ValueError("标定运行选项须为对象")
        import json
        try:
            json.dumps(self.run_options, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("标定运行选项必须为有限的 JSON 数据") from exc
        if self.entry_kind not in ("", "executable", "cmake", "cpp"):
            raise ValueError("程序入口类型无效")


@dataclass
class Project:
    name: str = "未命名实验"
    scene: Scene = field(default_factory=Scene)
    sampling: Sampling = field(default_factory=Sampling)
    calibration: CalibrationDraft = field(default_factory=CalibrationDraft)
    format_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        if type(self.format_version) is not int or self.format_version != SCHEMA_VERSION:
            raise ValueError("不支持的项目格式版本（当前写入 2，可加载旧版 1）")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("项目名称不能为空")
        for key, kind in (("scene", Scene), ("sampling", Sampling), ("calibration", CalibrationDraft)):
            value = getattr(self, key)
            if not isinstance(value, kind):
                raise ValueError(f"project.{key} 配置类型无效")
            value.validate()

    def to_dict(self) -> dict:
        self.validate()
        return {**asdict(self), "conventions": coordinate_metadata()}

    @classmethod
    def from_dict(cls, data: dict) -> Project:
        try:
            if not isinstance(data, dict) or type(data.get("format_version")) is not int or data["format_version"] not in (1, SCHEMA_VERSION):
                raise ValueError("不支持的项目格式版本（可加载 1、2）")
            unknown = set(data) - set(cls.__dataclass_fields__) - {"conventions"}
            if unknown:
                raise ValueError(f"项目存在无效字段：{', '.join(sorted(unknown))}")
            if data["format_version"] == SCHEMA_VERSION or "conventions" in data:
                validate_metadata(data.get("conventions"))
            project = cls(
                name=data["name"], scene=Scene.from_dict(data["scene"]),
                sampling=_decode(Sampling(), data.get("sampling", {}), {}, "sampling"),
                calibration=_decode(CalibrationDraft(), data.get("calibration", {}), {}, "calibration"),
                format_version=SCHEMA_VERSION,
            )
            project.validate()
            return project
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"项目结构不完整或字段格式错误：{exc}") from exc


def preset_scene(name: str) -> Scene:
    scene = Scene(preset=name)
    if name == "Pitch 轴心偏移":
        scene.pitch.installation.position_mm = [40.0, 15.0, 125.0]
    elif name == "相机安装偏置":
        scene.camera.installation.position_mm = [90.0, 25.0, 20.0]
        scene.camera.installation.euler_zyx_deg = [-86.0, 3.0, -88.0]
    elif name == "采样示例（宽视场）":
        scene.camera.fx = scene.camera.fy = 520.0
    elif name not in ("理想双轴云台", "自定义场景"):
        raise ValueError("未知的场景预设")
    scene.validate()
    return scene

