"""GUI-free SO(3)/SE(3) operations; column vectors, right-handed rotations."""
import warnings

import numpy as np
from scipy.spatial.transform import Rotation

from gimbal_lab.domain.units import deg_to_rad, finite_array

ROTATION_ATOL = 1e-10


def vector(value, size, label="向量"):
    result = finite_array(value, label)
    if result.shape != (size,):
        raise ValueError(f"{label} 必须为长度 {size} 的向量")
    return result


def unit_axis(axis):
    result = vector(axis, 3, "旋转轴方向")
    scale = np.max(np.abs(result))
    if scale == 0:
        raise ValueError("旋转轴方向不能为零向量")
    # Scaling first also handles tiny and very large non-zero finite inputs.
    result /= scale
    return result / np.linalg.norm(result)


def validate_rotation(matrix):
    result = finite_array(matrix, "旋转矩阵")
    if result.shape != (3, 3):
        raise ValueError("旋转矩阵必须为 3×3")
    if not np.allclose(result.T @ result, np.eye(3), atol=ROTATION_ATOL, rtol=0) or not np.isclose(np.linalg.det(result), 1, atol=ROTATION_ATOL, rtol=0):
        raise ValueError("旋转矩阵须正交且行列式为 +1（不接受缩放、剪切或镜像）")
    return result


def validate_transform(matrix):
    result = finite_array(matrix, "刚体变换")
    if result.shape != (4, 4):
        raise ValueError("刚体变换必须为 4×4")
    if not np.allclose(result[3], [0, 0, 0, 1], atol=1e-12, rtol=0):
        raise ValueError("刚体变换末行必须为 [0,0,0,1]")
    validate_rotation(result[:3, :3])
    return result


def rotation_about_axis(axis, angle_rad):
    if finite_array(angle_rad).ndim != 0:
        raise ValueError("关节角必须为标量（rad）")
    x, y, z = unit_axis(axis)
    skew = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + np.sin(angle_rad) * skew + (1 - np.cos(angle_rad)) * skew @ skew


def rotation_from_euler_zyx_deg(angles):
    yaw, pitch, roll = deg_to_rad(vector(angles, 3, "Yaw/Pitch/Roll"))
    return (rotation_about_axis([0, 0, 1], yaw)
            @ rotation_about_axis([0, 1, 0], pitch)
            @ rotation_about_axis([1, 0, 0], roll))


def euler_zyx_deg_from_rotation(matrix):
    # Euler angles are only a GUI representation. At gimbal lock SciPy selects
    # the equivalent canonical solution (Roll=0); the stored matrix is unchanged.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Gimbal lock detected.*", category=UserWarning)
        return Rotation.from_matrix(validate_rotation(matrix)).as_euler("ZYX", degrees=True)


def make_transform(rotation=None, translation_mm=None):
    result = np.eye(4)
    if rotation is not None:
        result[:3, :3] = validate_rotation(rotation)
    if translation_mm is not None:
        result[:3, 3] = vector(translation_mm, 3, "平移（mm）")
    return result


def inverse_transform(matrix):
    matrix = validate_transform(matrix)
    result = np.eye(4)
    result[:3, :3] = matrix[:3, :3].T
    result[:3, 3] = -result[:3, :3] @ matrix[:3, 3]
    return result


def transform_points(matrix, points):
    matrix = validate_transform(matrix)
    points = finite_array(points, "三维点")
    if points.ndim not in (1, 2) or points.shape[-1] != 3:
        raise ValueError("三维点形状必须为 (3,) 或 (N,3)")
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def quaternion_wxyz_from_rotation(matrix):
    result = Rotation.from_matrix(validate_rotation(matrix)).as_quat(canonical=True, scalar_first=True)
    return result / np.linalg.norm(result)


def rotation_from_quaternion_wxyz(quaternion):
    quaternion = vector(quaternion, 4, "四元数 w x y z")
    if not np.isclose(np.linalg.norm(quaternion), 1, atol=1e-10, rtol=0):
        raise ValueError("四元数必须已归一化")
    return Rotation.from_quat(quaternion, scalar_first=True).as_matrix()


def rotation_angle_rad(matrix):
    matrix = validate_rotation(matrix)
    sine = np.linalg.norm([matrix[2, 1] - matrix[1, 2], matrix[0, 2] - matrix[2, 0], matrix[1, 0] - matrix[0, 1]]) / 2
    cosine = np.clip((np.trace(matrix) - 1) / 2, -1, 1)
    return float(np.arctan2(sine, cosine))

