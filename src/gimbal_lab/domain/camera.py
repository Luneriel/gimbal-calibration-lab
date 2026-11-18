"""Ideal pinhole image formation and validation, using only geometry scene states."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from gimbal_lab.domain.engine import SceneState
from gimbal_lab.domain.rigid import rotation_angle_rad, transform_points
from gimbal_lab.domain.units import rad_to_deg

# Avoid OpenCV spawning a CPU-sized pool in each GUI/generation worker.
cv2.setNumThreads(1)
DETECTION_FLAGS = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK
REASONS = {
    "board_behind_camera": "标定板位于相机后方",
    "board_crosses_camera_plane": "标定板穿过相机平面，不能形成完整透视图像",
    "board_outside_fov": "完整棋盘格超出视野或图像边界余量不足",
    "projected_cells_too_small": "棋盘格投影太小或过度倾斜",
    "corners_not_detected": "OpenCV 未检测到完整棋盘格角点（含 FAST_CHECK）",
    "corner_order_mismatch": "检测角点与理论角点无法通过棋盘对称排列对应",
    "pnp_failed": "单帧 PnP 求解失败或解位于相机后方",
    "pnp_reprojection_failed": "单帧 PnP 重投影残差超出像素采样容差",
}


@dataclass(frozen=True)
class RenderSettings:
    supersampling: int = 2
    texture_pixels_per_square: int = 80
    jpeg_quality: int = 98
    margin_px: float = 8.0
    min_cell_px: float = 8.0
    max_corner_rmse_px: float = 0.75
    max_pnp_reprojection_px: float = 0.75
    max_render_pixels: int = 16_000_000

    def validate(self):
        if type(self.supersampling) is not int or not 1 <= self.supersampling <= 4:
            raise ValueError("超采样倍数须为 1–4 的整数")
        if type(self.texture_pixels_per_square) is not int or not 16 <= self.texture_pixels_per_square <= 256:
            raise ValueError("纹理方格尺寸须为 16–256 像素")
        if type(self.jpeg_quality) is not int or not 90 <= self.jpeg_quality <= 100:
            raise ValueError("JPEG 质量须为 90–100")
        for value in (self.margin_px, self.min_cell_px, self.max_corner_rmse_px, self.max_pnp_reprojection_px):
            if not np.isfinite(value) or value <= 0:
                raise ValueError("成像有效性阈值必须为正的有限数")
        if type(self.max_render_pixels) is not int or self.max_render_pixels < 4096:
            raise ValueError("渲染像素预算无效")

    def to_dict(self):
        return asdict(self)


@dataclass
class CameraFrame:
    state: SceneState
    image: np.ndarray
    jpeg_bytes: bytes
    theoretical_corners: np.ndarray
    geometric_valid: bool
    detected_valid: bool = False
    valid: bool = False
    reasons: list[str] = field(default_factory=list)
    raw_corners: np.ndarray | None = None
    aligned_corners: np.ndarray | None = None
    corner_alignment: str | None = None
    pnp_T_C_T: np.ndarray | None = None
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def reason_text(self):
        return "；".join(REASONS.get(reason, reason) for reason in self.reasons)

    def validation_record(self):
        return {
            "geometric_valid": self.geometric_valid, "detected_valid": self.detected_valid,
            "valid": self.valid, "reasons": list(self.reasons), "reason_text": self.reason_text,
            "corner_alignment": self.corner_alignment,
            "alignment_uses_ground_truth": True,
            "detector_flags": int(DETECTION_FLAGS), "metrics": self.metrics,
            "theoretical_corners_px": self.theoretical_corners.tolist() if np.all(np.isfinite(self.theoretical_corners)) else None,
            "raw_detected_corners_px": None if self.raw_corners is None else self.raw_corners.tolist(),
            "aligned_detected_corners_px": None if self.aligned_corners is None else self.aligned_corners.tolist(),
            "pnp_T_C_T": None if self.pnp_T_C_T is None else self.pnp_T_C_T.tolist(),
        }


def check_camera_model(state: SceneState, settings: RenderSettings):
    settings.validate()
    if np.any(state.distortion_coefficients != 0):
        raise ValueError("当前只支持零畸变成像；请将 k1/k2/p1/p2/k3 设为 0，不能导出与图像不一致的畸变配置")
    width, height = state.image_size
    if width * height * settings.supersampling ** 2 > settings.max_render_pixels:
        raise ValueError("超出当前超采样渲染像素预算，请降低相机分辨率或显式调整 RenderSettings")


def project_points(state: SceneState, points_t=None):
    """Analytic ideal projection. Invalid depths are NaN, never plausible pixels."""
    points = state.board.corners_local_mm if points_t is None else np.asarray(points_t, dtype=float)
    camera_points = transform_points(state.transform("C", "T"), points)
    pixels = np.full((len(camera_points), 2), np.nan)
    front = camera_points[:, 2] > 1e-6
    homogeneous = camera_points[front] @ state.camera_matrix.T
    pixels[front] = homogeneous[:, :2] / homogeneous[:, 2, None]
    return pixels, camera_points[:, 2]


def detect_corners(image, columns, rows, flags=DETECTION_FLAGS):
    ok, corners = cv2.findChessboardCorners(image, (columns, rows), flags)
    if not ok or corners is None or len(corners) != columns * rows:
        return None
    refined = cv2.cornerSubPix(image, corners, (5, 5), (-1, -1),
                             (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-4))
    return refined.reshape(-1, 2).astype(float)


def align_corner_order(raw, theoretical, columns, rows):
    grid = raw.reshape(rows, columns, 2)
    alternatives = {"identity": grid, "rotate_180": grid[::-1, ::-1],
                    "reverse_rows": grid[::-1], "reverse_columns": grid[:, ::-1]}
    errors = {name: float(np.sqrt(np.mean(np.sum((points.reshape(-1, 2) - theoretical) ** 2, axis=1))))
              for name, points in alternatives.items()}
    name = min(errors, key=errors.get)
    return alternatives[name].reshape(-1, 2).copy(), name, errors[name]


def render_frame(state: SceneState, settings: RenderSettings | None = None) -> CameraFrame:
    settings = settings or RenderSettings()
    check_camera_model(state, settings)
    width, height = state.image_size
    outer, depth = project_points(state, state.board.outer_vertices_local_mm)
    theoretical, _ = project_points(state)
    reasons = []
    if np.all(depth <= 1e-6):
        reasons.append("board_behind_camera")
    elif np.any(depth <= 1e-6):
        reasons.append("board_crosses_camera_plane")
    else:
        m = settings.margin_px
        if np.any(outer[:, 0] < m) or np.any(outer[:, 0] > width - 1 - m) or np.any(outer[:, 1] < m) or np.any(outer[:, 1] > height - 1 - m):
            reasons.append("board_outside_fov")
        projected_squares, _ = project_points(state, state.board.squares_local_mm.reshape(-1, 3))
        projected_squares = projected_squares.reshape(-1, 4, 2)
        edges = np.linalg.norm(projected_squares - np.roll(projected_squares, 1, axis=1), axis=2)
        if not np.all(np.isfinite(edges)) or np.min(edges) < settings.min_cell_px:
            reasons.append("projected_cells_too_small")
    image = np.full((height, width), 255, dtype=np.uint8)
    if np.all(depth > 1e-6) and np.all(np.isfinite(outer)) and np.max(np.abs(outer)) < 1e7:
        s = settings.texture_pixels_per_square
        board = state.board
        pattern = (~board.square_is_dark.reshape(board.rows + 1, board.columns + 1)).astype(np.uint8) * 255
        texture = np.repeat(np.repeat(pattern, s, axis=0), s, axis=1)
        # Pixel-centre convention: texel i represents (i+.5)/s squares.
        d = board.spacing_mm
        source_to_plane = np.array([[d / s, 0, -d + d / (2 * s)], [0, d / s, -d + d / (2 * s)], [0, 0, 1]])
        transform = state.transform("C", "T")
        k = state.camera_matrix.copy()
        scale = settings.supersampling
        k[:2] *= scale
        k[0, 2] += (scale - 1) / 2
        k[1, 2] += (scale - 1) / 2
        homography = k @ np.column_stack((transform[:3, 0], transform[:3, 1], transform[:3, 3])) @ source_to_plane
        large = cv2.warpPerspective(texture, homography, (width * scale, height * scale), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=255)
        image = cv2.resize(large, (width, height), interpolation=cv2.INTER_AREA) if scale > 1 else large
    encoded, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, settings.jpeg_quality])
    if not encoded:
        raise RuntimeError("OpenCV JPEG 编码失败")
    jpeg = buffer.tobytes()
    decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    frame = CameraFrame(state, decoded, jpeg, theoretical, not reasons, reasons=reasons)
    if reasons:
        return frame
    frame.raw_corners = detect_corners(decoded, state.board.columns, state.board.rows)
    if frame.raw_corners is None:
        frame.reasons.append("corners_not_detected")
        return frame
    frame.aligned_corners, frame.corner_alignment, rmse = align_corner_order(frame.raw_corners, theoretical, state.board.columns, state.board.rows)
    frame.metrics["corner_rmse_px"] = rmse
    frame.metrics["corner_max_error_px"] = float(np.max(np.linalg.norm(frame.aligned_corners - theoretical, axis=1)))
    if rmse > settings.max_corner_rmse_px:
        frame.reasons.append("corner_order_mismatch")
        return frame
    frame.detected_valid = True
    ok, rvec, tvec = cv2.solvePnP(state.board.corners_local_mm.copy(), frame.aligned_corners, state.camera_matrix.copy(), np.zeros(5), flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        frame.reasons.append("pnp_failed")
        return frame
    rotation, _ = cv2.Rodrigues(rvec)
    estimate = np.eye(4)
    estimate[:3, :3], estimate[:3, 3] = rotation, tvec.ravel()
    if np.any(transform_points(estimate, state.board.corners_local_mm)[:, 2] <= 0):
        frame.reasons.append("pnp_failed")
        return frame
    frame.pnp_T_C_T = estimate
    recovered_pixels, _ = cv2.projectPoints(state.board.corners_local_mm, rvec, tvec, state.camera_matrix, np.zeros(5))
    reprojection = float(np.sqrt(np.mean(np.sum((recovered_pixels.reshape(-1, 2) - frame.aligned_corners) ** 2, axis=1))))
    truth = state.transform("C", "T")
    frame.metrics.update(pnp_reprojection_rmse_px=reprojection,
                         pnp_rotation_error_deg=float(rad_to_deg(rotation_angle_rad(truth[:3, :3].T @ rotation))),
                         pnp_translation_error_mm=float(np.linalg.norm(truth[:3, 3] - tvec.ravel())))
    if reprojection > settings.max_pnp_reprojection_px:
        frame.reasons.append("pnp_reprojection_failed")
        return frame
    frame.valid = True
    return frame
