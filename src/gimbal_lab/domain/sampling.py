"""Seeded sampling plans and explicit coverage heuristics; no GUI or images."""
from dataclasses import asdict, dataclass

import numpy as np

from gimbal_lab.domain.models import Sampling, Scene
from gimbal_lab.domain.rigid import rotation_angle_rad
from gimbal_lab.domain.units import rad_to_deg


@dataclass(frozen=True)
class Candidate:
    plan_id: int
    yaw_deg: float
    pitch_deg: float
    source: str = "initial"

    def to_dict(self):
        return asdict(self)


def validate_sampling(scene: Scene, sampling: Sampling):
    scene.validate()
    sampling.validate()
    for key, limits in (("yaw", sampling.yaw_range_deg), ("pitch", sampling.pitch_range_deg)):
        allowed = getattr(scene, key).limits_deg
        if limits[0] < allowed[0] or limits[1] > allowed[1]:
            raise ValueError(f"{key} 采样范围 {limits}° 超出关节限位 {allowed}°；不会自动缩小范围")


class CandidatePlan:
    def __init__(self, scene: Scene, sampling: Sampling):
        validate_sampling(scene, sampling)
        self.rng = np.random.default_rng(sampling.seed)
        self.limit = sampling.count if sampling.strict else (sampling.max_attempts or max(50, 10 * sampling.count))
        lo = np.array([sampling.yaw_range_deg[0], sampling.pitch_range_deg[0]])
        hi = np.array([sampling.yaw_range_deg[1], sampling.pitch_range_deg[1]])
        self.lo, self.hi = lo, hi
        if sampling.distribution == "均匀随机":
            normalized = self.rng.random((sampling.count, 2))
        else:
            anchors = np.array([(0.5, 0.5), (0, 0), (1, 1), (0, 1), (1, 0), (0, 0.5), (1, 0.5), (0.5, 0), (0.5, 1)])[:sampling.count]
            remaining = sampling.count - len(anchors)
            if remaining:
                lhs = np.column_stack([(self.rng.permutation(remaining) + self.rng.random(remaining)) / remaining for _ in range(2)])
                normalized = np.vstack((anchors, lhs))
            else:
                normalized = anchors
        angles = lo + normalized * (hi - lo)
        self.initial = tuple(Candidate(index + 1, float(yaw), float(pitch)) for index, (yaw, pitch) in enumerate(angles))

    def __iter__(self):
        yield from self.initial
        for index in range(len(self.initial), self.limit):
            yaw, pitch = self.rng.uniform(self.lo, self.hi)
            yield Candidate(index + 1, float(yaw), float(pitch), "supplement")


def coverage_report(records, sampling: Sampling):
    valid = [record for record in records if record["valid"]]
    warnings = []
    actual, fractions = {}, {}
    if valid:
        angles = np.array([[r["yaw_deg"], r["pitch_deg"]] for r in valid])
        for index, (key, desired) in enumerate((("yaw", sampling.yaw_range_deg), ("pitch", sampling.pitch_range_deg))):
            low, high = float(angles[:, index].min()), float(angles[:, index].max())
            actual[key + "_deg"] = [low, high]
            fractions[key] = (high - low) / (desired[1] - desired[0])
            if fractions[key] < 0.75:
                warnings.append(f"{key} 实际范围 [{low:.2f},{high:.2f}]° 仅覆盖请求跨度的 {100 * fractions[key]:.1f}%")
            if high - low < 2:
                warnings.append(f"{key} 运动幅度小于 2°，存在姿态激励不足风险")
        unique = len(np.unique(np.round(angles, 6), axis=0))
        duplicate_count = len(valid) - unique
        if duplicate_count:
            warnings.append(f"存在 {duplicate_count} 个重复关节姿态")
        eigenvalues = [0.0, 0.0]
        if len(valid) >= 3:
            spans = np.array([np.ptp(sampling.yaw_range_deg), np.ptp(sampling.pitch_range_deg)])
            normalized = angles / spans
            eigenvalues = np.linalg.eigvalsh(np.cov(normalized.T)).tolist()
            if eigenvalues[1] <= 1e-15 or eigenvalues[0] / eigenvalues[1] < 0.02:
                warnings.append("Yaw/Pitch 分布接近单一直线，存在组合姿态退化风险")
        first_r = np.array(valid[0]["geometry"]["R_A_I"])
        imu_span = max(float(rad_to_deg(rotation_angle_rad(first_r.T @ np.array(r["geometry"]["R_A_I"])))) for r in valid)
        if imu_span < 2:
            warnings.append("IMU 实际姿态变化小于 2°，不能将图像有效等同于标定运动充分")
    else:
        unique = duplicate_count = 0
        eigenvalues, imu_span = [0.0, 0.0], 0.0
        warnings.append("没有有效样本")
    if len(valid) < 3:
        warnings.append("有效样本少于 3 组")
    return {"valid_count": len(valid), "actual_ranges": actual, "requested_ranges": {
        "yaw_deg": list(sampling.yaw_range_deg), "pitch_deg": list(sampling.pitch_range_deg)},
        "span_fractions": fractions, "unique_pose_count": unique, "duplicate_count": duplicate_count,
        "normalized_covariance_eigenvalues": eigenvalues, "imu_rotation_span_deg": imu_span,
        "warnings": warnings, "heuristics_only": True}
