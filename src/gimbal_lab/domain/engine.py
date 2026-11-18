"""Deterministic, GUI-independent dual-axis kinematics and sensor query boundary."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

import numpy as np

from gimbal_lab.domain.board import BoardGeometry, readonly
from gimbal_lab.domain.geometry import axis_rotation, pose_matrix
from gimbal_lab.domain.models import Scene, coordinate_metadata
from gimbal_lab.domain.rigid import (
    inverse_transform, make_transform, quaternion_wxyz_from_rotation,
    rotation_angle_rad, transform_points, unit_axis,
)
from gimbal_lab.domain.units import finite_array, rad_to_deg

FRAME_ALIASES = {**coordinate_metadata()["frames"], "JY": "yaw_home", "JP": "pitch_home"}
BODY_MOTION = {"base": (), "yaw": ("yaw",), "pitch": ("yaw", "pitch")}


@dataclass(frozen=True)
class JointAngles:
    yaw_deg: float
    pitch_deg: float


@dataclass(frozen=True)
class FixedExtrinsics:
    is_fixed: bool
    varying_joints: tuple[str, ...]
    fixed_transform: np.ndarray | None
    probe_max_translation_mm: float
    probe_max_rotation_deg: float
    translation_tolerance_mm: float
    rotation_tolerance: float
    message: str


@dataclass(frozen=True)
class SceneState:
    angles_deg: JointAngles
    _frames: Mapping[str, np.ndarray]
    joint_axes_world: Mapping[str, np.ndarray]
    joint_axes_local: Mapping[str, np.ndarray]
    board: BoardGeometry
    camera_matrix: np.ndarray
    distortion_coefficients: np.ndarray
    image_size: tuple[int, int]
    fixed_extrinsics: FixedExtrinsics
    imu_missing_joints_for_g: tuple[str, ...]
    imu_missing_joints_for_pitch: tuple[str, ...]
    imu_extra_joints_for_g: tuple[str, ...]

    @property
    def frames(self) -> dict[str, np.ndarray]:
        return {key: value.copy() for key, value in self._frames.items()}

    def world_pose(self, frame: str) -> np.ndarray:
        key = FRAME_ALIASES.get(frame, frame)
        if key not in self._frames:
            raise KeyError(f"未知坐标系 {frame!r}；使用 W/B/Y/P/C/I/A/T/G 或明确的对象 ID")
        return self._frames[key].copy()

    def transform(self, target: str, source: str) -> np.ndarray:
        """Return T_target_source, mapping source coordinates into target."""
        target_pose, source_pose = self.world_pose(target), self.world_pose(source)
        if FRAME_ALIASES.get(target, target) == FRAME_ALIASES.get(source, source):
            return np.eye(4)
        return inverse_transform(target_pose) @ source_pose

    @property
    def T_W_C(self):
        return self.world_pose("C")

    @property
    def T_W_G(self):
        return self.world_pose("G")

    @property
    def T_G_C(self):
        return self.transform("G", "C")

    @property
    def T_W_I(self):
        return self.world_pose("I")

    @property
    def R_A_I(self):
        return self.transform("A", "I")[:3, :3]

    @property
    def quaternion_wxyz(self):
        return quaternion_wxyz_from_rotation(self.R_A_I)

    def board_corners(self, frame="T"):
        return transform_points(self.transform(frame, "T"), self.board.corners_local_mm)

    def camera_frustum(self, depth_mm):
        depth = finite_array(depth_mm)
        if depth.ndim != 0 or float(depth) <= 0:
            raise ValueError("视锥深度须为正的有限 mm 标量")
        width, height = self.image_size
        pixels = np.array([[0, 0, 1], [width, 0, 1], [width, height, 1], [0, height, 1]])
        rays = pixels @ np.linalg.inv(self.camera_matrix).T * float(depth)
        return np.vstack((np.zeros(3), rays))

    @property
    def imu_limitation_message(self):
        missing = self.imu_missing_joints_for_g
        if missing:
            return f"单 IMU 姿态缺少 G 运动中的 {' / '.join(missing)} 信息，不能单独提供完整 G 姿态。"
        if self.imu_extra_joints_for_g:
            return f"IMU 额外包含 {' / '.join(self.imu_extra_joints_for_g)} 运动；I 与 G 非同一刚体，不能通过固定安装旋转直接替代 G 的运动。"
        if self.imu_missing_joints_for_pitch:
            return f"IMU 不包含 Pitch 部件的完整运动（缺少 {' / '.join(self.imu_missing_joints_for_pitch)}）；当前 G 不需要这些关节。"
        return ""

    @property
    def imu_relative_is_fixed(self):
        return not (self.imu_missing_joints_for_g or self.imu_extra_joints_for_g)

    def to_dict(self):
        """Per-pose geometric truth, not a dataset or a calibration result."""
        return {
            "geometry_state_version": 2, "conventions": coordinate_metadata(),
            "angles_deg": {"yaw": self.angles_deg.yaw_deg, "pitch": self.angles_deg.pitch_deg},
            "T_W_frames": {key: value.tolist() for key, value in self._frames.items()},
            "T_G_C": self.T_G_C.tolist(), "R_A_I": self.R_A_I.tolist(),
            "quaternion_wxyz": self.quaternion_wxyz.tolist(),
            "fixed_extrinsics": self.fixed_extrinsics.is_fixed,
            "fixed_T_G_C": None if self.fixed_extrinsics.fixed_transform is None else self.fixed_extrinsics.fixed_transform.tolist(),
            "imu_missing_joints_for_g": list(self.imu_missing_joints_for_g),
            "imu_extra_joints_for_g": list(self.imu_extra_joints_for_g),
            "imu_relative_is_fixed": self.imu_relative_is_fixed,
        }


class GeometryEngine:
    def __init__(self, scene: Scene):
        if not isinstance(scene, Scene):
            raise ValueError("几何引擎需要 Scene 配置")
        scene.validate()
        self._scene = deepcopy(scene)
        scene = self._scene
        self._board = BoardGeometry.from_config(self._scene.board)
        self._poses = {"base": pose_matrix(scene.base), "board": pose_matrix(scene.board.installation)}
        self._axes = {}
        for key in ("yaw", "pitch"):
            joint = getattr(scene, key)
            self._poses[key + "_home"] = pose_matrix(joint.installation)
            self._poses[key + "_zero"] = pose_matrix(joint.child_zero)
            self._axes[key] = unit_axis(joint.axis)
        for key in ("camera", "imu", "gimbal"):
            self._poses[key] = pose_matrix(getattr(scene, key).installation)
        # A and W share an origin; the specified R_A_W maps W axes into A.
        self._poses["absolute_reference"] = make_transform(np.asarray(scene.imu.reference_rotation_aw).T)
        cam = scene.camera
        self._camera_matrix = readonly(np.array([[cam.fx, 0, cam.cx], [0, cam.fy, cam.cy], [0, 0, 1]], dtype=float))
        self._distortion = readonly(np.array(cam.distortion, dtype=float))
        self.fixed_extrinsics = self._check_fixed_extrinsics()

    @property
    def config(self):
        return deepcopy(self._scene)

    def _angles(self, yaw_deg=None, pitch_deg=None):
        result = []
        for key, value in (("yaw", yaw_deg), ("pitch", pitch_deg)):
            joint = getattr(self._scene, key)
            value = joint.angle_deg if value is None else value
            if finite_array(value).ndim != 0:
                raise ValueError(f"{key} 查询角必须为标量（°）")
            value = float(value)
            if not joint.limits_deg[0] <= value <= joint.limits_deg[1]:
                raise ValueError(f"{key} 查询角 {value}° 超出 {joint.limits_deg}°")
            result.append(value)
        return JointAngles(*result)

    def _evaluate(self, angles: JointAngles):
        frames = {"world": np.eye(4), "base": self._poses["base"]}
        for key, value in (("yaw", angles.yaw_deg), ("pitch", angles.pitch_deg)):
            joint = getattr(self._scene, key)
            frames[key + "_home"] = frames[joint.parent] @ self._poses[key + "_home"]
            frames[key + "_moving"] = frames[key + "_home"] @ make_transform(axis_rotation(self._axes[key], value))
            frames[joint.child] = frames[key + "_moving"] @ self._poses[key + "_zero"]
        for key in ("camera", "imu", "gimbal"):
            frames[key] = frames[getattr(self._scene, key).parent] @ self._poses[key]
        frames["board"] = self._poses["board"]
        frames["absolute_reference"] = self._poses["absolute_reference"]
        return frames

    def _check_fixed_extrinsics(self):
        scene = self._scene
        camera_path, gimbal_path = set(BODY_MOTION[scene.camera.parent]), set(BODY_MOTION[scene.gimbal.parent])
        varying = tuple(key for key in ("yaw", "pitch") if key in camera_path ^ gimbal_path)
        is_fixed = not varying
        mids = [(getattr(scene, key).limits_deg[0] + getattr(scene, key).limits_deg[1]) / 2 for key in ("yaw", "pitch")]
        probes = [JointAngles(*mids)]
        for index, key in enumerate(("yaw", "pitch")):
            for end in getattr(scene, key).limits_deg:
                values = mids.copy()
                values[index] = end
                probes.append(JointAngles(*values))
        transforms = []
        for angles in probes:
            frames = self._evaluate(angles)
            transforms.append(inverse_transform(frames["gimbal"]) @ frames["camera"])
        # Roundoff budget from float64 eps, chain length and configured lever arms.
        scale_mm = max(1.0, sum(np.linalg.norm(pose[:3, 3]) for pose in self._poses.values()))
        translation_tol = 256 * np.finfo(float).eps * scale_mm
        rotation_tol = 128 * np.finfo(float).eps
        fixed = inverse_transform(self._poses["gimbal"]) @ self._poses["camera"] if is_fixed else None
        baseline = fixed if is_fixed else transforms[0]
        max_translation = max(float(np.linalg.norm(t[:3, 3] - baseline[:3, 3])) for t in transforms)
        max_rotation = max(float(rad_to_deg(rotation_angle_rad(baseline[:3, :3].T @ t[:3, :3]))) for t in transforms)
        if is_fixed and any(not np.allclose(t[:3, :3], fixed[:3, :3], atol=rotation_tol, rtol=0)
                            or np.linalg.norm(t[:3, 3] - fixed[:3, 3]) > translation_tol for t in transforms):
            raise ArithmeticError("固定外参拓扑与数值变换不一致")
        message = "相机与 G 固定在同一刚体，T_G_C 为固定外参。" if is_fixed else f"T_G_C 随 {' / '.join(varying)} 运动变化；仅可使用逐帧 Ground Truth。"
        return FixedExtrinsics(is_fixed, varying, None if fixed is None else readonly(fixed),
                               max_translation, max_rotation, translation_tol, rotation_tol, message)

    def solve(self, yaw_deg=None, pitch_deg=None) -> SceneState:
        angles = self._angles(yaw_deg, pitch_deg)
        frames = self._evaluate(angles)
        scene = self._scene
        imu_motion = set(BODY_MOTION[scene.imu.parent])
        missing_g = tuple(key for key in BODY_MOTION[scene.gimbal.parent] if key not in imu_motion)
        missing_pitch = tuple(key for key in BODY_MOTION["pitch"] if key not in imu_motion)
        extra_g = tuple(key for key in BODY_MOTION[scene.imu.parent] if key not in BODY_MOTION[scene.gimbal.parent])
        axes = {key: readonly(frames[key + "_home"][:3, :3] @ self._axes[key]) for key in ("yaw", "pitch")}
        return SceneState(
            angles_deg=angles, _frames=MappingProxyType({key: readonly(value) for key, value in frames.items()}),
            joint_axes_world=MappingProxyType(axes),
            joint_axes_local=MappingProxyType({key: readonly(value) for key, value in self._axes.items()}),
            board=self._board, camera_matrix=self._camera_matrix, distortion_coefficients=self._distortion,
            image_size=(scene.camera.width, scene.camera.height), fixed_extrinsics=self.fixed_extrinsics,
            imu_missing_joints_for_g=missing_g, imu_missing_joints_for_pitch=missing_pitch,
            imu_extra_joints_for_g=extra_g,
        )

    def iter_states(self, poses: Iterable[JointAngles | tuple[float, float]]):
        for index, pose in enumerate(poses):
            try:
                angles = pose if isinstance(pose, JointAngles) else JointAngles(*pose)
                yield self.solve(angles.yaw_deg, angles.pitch_deg)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"姿态计划第 {index + 1} 项无效：{exc}") from exc

    def solve_many(self, poses: Iterable[JointAngles | tuple[float, float]]) -> tuple[SceneState, ...]:
        return tuple(self.iter_states(poses))


def solve_scene(scene: Scene, *, yaw_deg=None, pitch_deg=None) -> SceneState:
    return GeometryEngine(scene).solve(yaw_deg, pitch_deg)

