"""Read-only experiments: validate actual files, restore independent geometry states."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import yaml

from gimbal_lab.domain.camera import detect_corners
from gimbal_lab.domain.datasets import read_quaternion, scene_signature
from gimbal_lab.domain.engine import GeometryEngine, SceneState
from gimbal_lab.domain.models import Project, validate_metadata
from gimbal_lab.domain.rigid import rotation_from_quaternion_wxyz, validate_transform


@dataclass
class ReplayItem:
    record: dict
    state: SceneState
    image: np.ndarray | None
    quaternion: np.ndarray | None


class Dataset:
    def __init__(self, root, *, allow_incomplete=False, recheck_images=False):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError("实验目录不存在")
        self.document = json.loads((self.root / "experiment.json").read_text(encoding="utf-8"))
        d = self.document
        if type(d.get("dataset_schema_version")) is not int or d["dataset_schema_version"] != 1:
            raise ValueError("不支持的数据集 Schema")
        validate_metadata(d.get("conventions"))
        self.status = d.get("status")
        if self.status not in ("completed", "partial", "cancelled", "failed", "generating", "validating"):
            raise ValueError("数据集完成状态无效")
        if not allow_incomplete and self.status in ("generating", "validating"):
            raise ValueError("实验仍标记为生成中，暂不回放；取消/失败的已关闭实验可以检查")
        self.project = Project.from_dict(d["project_snapshot"])
        self.engine = GeometryEngine(self.project.scene)
        if scene_signature(self.project.scene) != d["scene_signature"]:
            raise ValueError("场景快照摘要不匹配")
        self.records = d["candidates"]
        self.valid_records = [record for record in self.records if record["valid"]]
        self.failure_records = [record for record in self.records if not record["valid"]]
        self.calibration = yaml.safe_load((self.root / "calibration.yaml").read_text(encoding="utf-8"))
        self.ground_truth = yaml.safe_load((self.root / "ground_truth.yaml").read_text(encoding="utf-8"))
        try:
            self._validate(recheck_images)
        except (AssertionError, KeyError, TypeError, IndexError) as exc:
            raise ValueError(f"实验数据完整性检查失败：{exc}") from exc

    def _path(self, value):
        if not isinstance(value, str) or Path(value).is_absolute():
            raise ValueError("实验文件路径必须为安全的相对路径")
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("实验文件路径不能离开数据集目录")
        return path

    def _validate(self, recheck_images):
        d, cal, gt = self.document, self.calibration, self.ground_truth
        state = self.engine.solve()
        count = len(self.valid_records)
        if d["valid_count"] != count or d["attempted_count"] != len(self.records) or d["failed_count"] != len(self.failure_records):
            raise ValueError("实验统计与记录数量不一致")
        if [r["plan_id"] for r in self.records] != list(range(1, len(self.records) + 1)):
            raise ValueError("候选姿态记录序号不连续")
        if cal["pattern_type"] != "chessboard" or (cal["pattern_cols"], cal["pattern_rows"]) != (state.board.columns, state.board.rows):
            raise ValueError("YAML 棋盘参数与场景不匹配")
        if cal["center_distance_mm"] != state.board.spacing_mm or cal["translation_unit"] != "mm" or cal["matrix_layout"] != "row-major":
            raise ValueError("YAML 尺寸单位或矩阵顺序不匹配")
        if cal["quaternion_order"] != "wxyz" or cal["quaternion_direction"] != "I_to_A":
            raise ValueError("YAML 四元数约定不匹配")
        np.testing.assert_allclose(np.array(cal["camera_matrix"]).reshape(3, 3), state.camera_matrix, atol=0, rtol=0)
        np.testing.assert_array_equal(cal["distort_coeffs"], state.distortion_coefficients)
        if (cal["image_width"], cal["image_height"]) != state.image_size:
            raise ValueError("YAML 分辨率不匹配")
        validate_metadata(gt["conventions"])
        if gt["matrix_layout"] != "row-major":
            raise ValueError("Ground Truth 矩阵顺序不匹配")
        if bool(gt["fixed_extrinsics"]) != state.fixed_extrinsics.is_fixed:
            raise ValueError("Ground Truth 固定外参模型不匹配")
        if state.fixed_extrinsics.is_fixed:
            np.testing.assert_allclose(np.array(gt["T_G_C_fixed"]).reshape(4, 4), state.fixed_extrinsics.fixed_transform, atol=1e-10, rtol=0)
        elif gt["T_G_C_fixed"] is not None:
            raise ValueError("动态模型不能包含伪造的固定 T_G_C")
        np.testing.assert_allclose(np.array(gt["T_W_T"]).reshape(4, 4), state.world_pose("T"), atol=1e-10, rtol=0)
        imu = gt["imu"]
        if imu["parent"] != self.project.scene.imu.parent:
            raise ValueError("Ground Truth IMU 挂载不匹配")
        np.testing.assert_allclose(np.array(imu["T_parent_I"]).reshape(4, 4),
                                   state.transform(imu["parent"], "I"), atol=1e-10, rtol=0)
        np.testing.assert_allclose(np.array(imu["R_A_W"]).reshape(3, 3),
                                   state.transform("A", "W")[:3, :3], atol=1e-12, rtol=0)
        if state.imu_relative_is_fixed:
            np.testing.assert_allclose(np.array(imu["T_I_G_fixed"]).reshape(4, 4),
                                       state.transform("I", "G"), atol=1e-10, rtol=0)
        elif imu["T_I_G_fixed"] is not None:
            raise ValueError("动态 IMU/G 关系不能包含伪造的固定变换")
        if len(gt["frames"]) != len(self.records):
            raise ValueError("逐帧 Ground Truth 数量不匹配")
        for record, gt_frame in zip(self.records, gt["frames"]):
            frame_state = self.engine.solve(record["yaw_deg"], record["pitch_deg"])
            for key, actual in record["geometry"]["T_W_frames"].items():
                validate_transform(actual)
                np.testing.assert_allclose(actual, frame_state.world_pose(key), atol=1e-9, rtol=0)
            np.testing.assert_allclose(record["geometry"]["R_A_I"], frame_state.R_A_I, atol=1e-12, rtol=0)
            np.testing.assert_allclose(record["camera_matrix"], state.camera_matrix, atol=0, rtol=0)
            if record["image_size"] != list(state.image_size):
                raise ValueError("逐帧图像尺寸与冻结场景不匹配")
            np.testing.assert_array_equal(record["distort_coeffs"], state.distortion_coefficients)
            if gt_frame["plan_id"] != record["plan_id"] or gt_frame["export_id"] != record["export_id"]:
                raise ValueError("GT 计划编号与导出编号不匹配")
            for key, expected in (("T_G_C", frame_state.T_G_C), ("T_C_T", frame_state.transform("C", "T"))):
                np.testing.assert_allclose(np.array(gt_frame[key]).reshape(4, 4), expected, atol=1e-9, rtol=0)
                np.testing.assert_allclose(record["geometry"][key], expected, atol=1e-9, rtol=0)
        for index, record in enumerate(self.valid_records, 1):
            if record["export_id"] != index:
                raise ValueError("有效样本导出编号必须从 1 连续编号")
            files = record["files"]
            if files["picture"] != f"pictures/{index}.jpg" or files["quaternion"] != f"txt/{index}.txt":
                raise ValueError("JPG/TXT 路径或编号不匹配")
            for key in ("picture", "quaternion"):
                path = self._path(files[key])
                if not path.is_file():
                    raise ValueError(f"缺失文件：{files[key]}")
                if hashlib.sha256(path.read_bytes()).hexdigest() != files[key + "_sha256"]:
                    raise ValueError(f"文件内容校验失败：{files[key]}")
            q = read_quaternion(self._path(files["quaternion"]))
            np.testing.assert_allclose(rotation_from_quaternion_wxyz(q), record["geometry"]["R_A_I"], atol=1e-12, rtol=0)
            image = cv2.imread(str(self._path(files["picture"])), cv2.IMREAD_GRAYSCALE)
            if image is None or image.shape != (state.image_size[1], state.image_size[0]):
                raise ValueError("图片损坏或分辨率不一致")
            if recheck_images and detect_corners(image, state.board.columns, state.board.rows) is None:
                raise ValueError(f"导出 JPG 角点复检失败：{index}.jpg")
        for folder, extension in (("pictures", "jpg"), ("txt", "txt")):
            expected = {f"{i}.{extension}" for i in range(1, count + 1)}
            if {p.name for p in (self.root / folder).glob("*." + extension)} != expected:
                raise ValueError("实际文件存在编号缺口、额外样本或 JPG/TXT 不匹配")
            if list((self.root / folder).glob("*.tmp")):
                raise ValueError("实验存在未提交的临时文件")

    def frame(self, index):
        record = self.valid_records[index]
        for key in ("picture", "quaternion"):
            path = self._path(record["files"][key])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record["files"][key + "_sha256"]:
                raise ValueError("回放文件在加载后发生变化或丢失，请重新检查实验")
        image = cv2.imread(str(self._path(record["files"]["picture"])), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError("回放图片已丢失或损坏")
        quaternion = read_quaternion(self._path(record["files"]["quaternion"]))
        return ReplayItem(record, self.engine.solve(record["yaw_deg"], record["pitch_deg"]), image, quaternion)

    def failure(self, index):
        record = self.failure_records[index]
        return ReplayItem(record, self.engine.solve(record["yaw_deg"], record["pitch_deg"]), None, None)


def sequential_format_check(root):
    """Simulate a legacy sequential reader; NOT C++ calibration integration."""
    dataset = Dataset(root)
    count = 0
    while (dataset.root / "pictures" / f"{count + 1}.jpg").is_file():
        image = cv2.imread(str(dataset.root / "pictures" / f"{count + 1}.jpg"))
        if image is None:
            raise ValueError("顺序读取图片失败")
        read_quaternion(dataset.root / "txt" / f"{count + 1}.txt")
        count += 1
    if count != len(dataset.valid_records):
        raise ValueError("顺序读取提前停止，存在编号缺口")
    return {"scope": "input_format_only_not_cpp_integration", "read_count": count,
            "matrix_layout": "row-major", "quaternion_order": "wxyz", "status": dataset.status}
