"""Rigid pose and revolute-joint functions with compatible frame queries.

T_A_B maps B coordinates into A. Neither Qt nor rendering is imported here.
"""
from __future__ import annotations

import numpy as np
from gimbal_lab.domain.models import Joint, Pose, Scene
from gimbal_lab.domain.rigid import inverse_transform, make_transform, rotation_about_axis, rotation_from_euler_zyx_deg
from gimbal_lab.domain.units import deg_to_rad


def axis_rotation(axis: list[float], angle_deg: float) -> np.ndarray:
    return rotation_about_axis(axis, deg_to_rad(angle_deg))


def pose_matrix(pose: Pose) -> np.ndarray:
    pose.validate()
    return make_transform(rotation_from_euler_zyx_deg(pose.euler_zyx_deg), pose.position_mm)


def joint_transform(joint: Joint, angle_deg: float) -> np.ndarray:
    joint.validate()
    if not joint.limits_deg[0] <= angle_deg <= joint.limits_deg[1]:
        raise ValueError("查询角度超出关节限位")
    return pose_matrix(joint.installation) @ make_transform(axis_rotation(joint.axis, angle_deg)) @ pose_matrix(joint.child_zero)


def frame_transforms(scene: Scene) -> dict[str, np.ndarray]:
    from gimbal_lab.domain.engine import solve_scene
    return solve_scene(scene).frames


