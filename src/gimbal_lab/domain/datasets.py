"""Frozen-scene datasets, paired transactions, bounded generation and manual sampling."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid

import cv2
import numpy as np
import yaml

from gimbal_lab.domain.camera import RenderSettings, check_camera_model, render_frame
from gimbal_lab.domain.engine import GeometryEngine
from gimbal_lab.domain.models import Project, coordinate_metadata
from gimbal_lab.domain.persistence import _write_json
from gimbal_lab.domain.rigid import rotation_from_quaternion_wxyz
from gimbal_lab.domain.sampling import Candidate, CandidatePlan, coverage_report


def scene_signature(scene):
    data = asdict(scene)
    data.pop("preset", None)
    for key in ("yaw", "pitch"):
        data[key].pop("angle_deg")
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def read_quaternion(path):
    tokens = Path(path).read_text(encoding="utf-8").split()
    if len(tokens) != 4:
        raise ValueError(f"{path} 必须恰有 4 个 w x y z 数值")
    try:
        values = np.array([float(token) for token in tokens])
    except ValueError as exc:
        raise ValueError(f"{path} 四元数格式无效") from exc
    rotation_from_quaternion_wxyz(values)
    return values


def reserve_experiment_path(parent):
    parent = Path(parent).expanduser().resolve()
    if not parent.is_dir():
        raise ValueError("请选择已有的输出父目录")
    if (parent / "experiment.json").exists():
        raise ValueError("所选目录是已有实验，请选择其父目录；已有数据不会被覆盖")
    for index in range(1, 100000):
        candidate = parent / f"experiment_{index:03d}"
        if not candidate.exists():
            return candidate
    raise ValueError("输出目录下实验数量过多")


def _write_yaml(path, data):
    # Metadata is replaced atomically; it never overwrites the source scene/data.
    path = Path(path)
    temporary = path.with_name("." + path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            yaml.safe_dump(data, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ExperimentWriter:
    def __init__(self, project: Project, root: Path, settings=None, initial_plan=()):
        self.project = deepcopy(project)
        self.project.validate()
        self.engine = GeometryEngine(self.project.scene)
        self.settings = settings or RenderSettings()
        check_camera_model(self.engine.solve(), self.settings)
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=False, exist_ok=False)  # Never overwrite any dataset.
        self.records = []
        self.valid_count = 0
        self.last_checkpoint = 0.0
        self.document = {
            "dataset_schema_version": 1, "experiment_id": uuid.uuid4().hex,
            "created_utc": datetime.now(timezone.utc).isoformat(), "status": "generating",
            "project_snapshot": self.project.to_dict(), "scene_signature": scene_signature(self.project.scene),
            "conventions": coordinate_metadata(), "sampling": asdict(self.project.sampling),
            "random_seed": self.project.sampling.seed, "renderer": self.settings.to_dict(),
            "runtime": {"opencv": cv2.__version__, "numpy": np.__version__},
            "initial_plan": [c.to_dict() for c in initial_plan], "candidates": self.records,
            "completed_utc": None, "error": None,
        }
        try:
            (self.root / "pictures").mkdir()
            (self.root / "txt").mkdir()
            state = self.engine.solve()
            calibration = {
                "dataset_schema_version": 1, "pattern_type": "chessboard",
                "pattern_cols": state.board.columns, "pattern_rows": state.board.rows,
                "center_distance_mm": state.board.spacing_mm,
                "image_width": state.image_size[0], "image_height": state.image_size[1],
                "camera_matrix": state.camera_matrix.ravel().tolist(),
                "distort_coeffs": state.distortion_coefficients.ravel().tolist(),
                "matrix_layout": "row-major", "camera_intrinsic_unit": "px", "translation_unit": "mm",
                "quaternion_order": "wxyz", "quaternion_direction": "I_to_A",
                "adapter_parameters": {"R_gimbal2imubody": {"applicable": False,
                    "reason": "未绑定具体标定程序的轴向适配规则；通用数据不强行输出该矩阵"}},
            }
            _write_yaml(self.root / "calibration.yaml", calibration)
            self.checkpoint(force=True)
        except Exception as exc:
            self.document["status"], self.document["error"] = "failed", str(exc)
            _write_json(self.document, self.root / "experiment.json")
            raise

    def _pair(self, jpeg, quaternion):
        index = self.valid_count + 1
        picture, text = self.root / "pictures" / f"{index}.jpg", self.root / "txt" / f"{index}.txt"
        if picture.exists() or text.exists():
            raise FileExistsError("有效样本目标文件已存在，拒绝覆盖")
        contents = (" ".join(format(float(value), ".17g") for value in quaternion) + "\n").encode()
        stages = [picture.with_suffix(".jpg.tmp"), text.with_suffix(".txt.tmp")]
        committed = []
        try:
            for stage, data in zip(stages, (jpeg, contents)):
                with stage.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            for stage, destination in zip(stages, (picture, text)):
                os.replace(stage, destination)
                committed.append(destination)
        except Exception:
            for destination in committed:
                destination.unlink(missing_ok=True)
            raise
        finally:
            for stage in stages:
                stage.unlink(missing_ok=True)
        return {"picture": f"pictures/{index}.jpg", "quaternion": f"txt/{index}.txt",
                "picture_sha256": hashlib.sha256(jpeg).hexdigest(), "quaternion_sha256": hashlib.sha256(contents).hexdigest()}

    def add(self, candidate, frame=None, duplicate=False):
        state = frame.state if frame is not None else self.engine.solve(candidate.yaw_deg, candidate.pitch_deg)
        validation = frame.validation_record() if frame is not None else {
            "geometric_valid": None, "detected_valid": None, "valid": False,
            "reasons": ["duplicate_pose"], "reason_text": "重复姿态未加入有效数据集", "metrics": {}}
        valid = bool(validation["valid"]) and not duplicate
        record = {**candidate.to_dict(), **validation, "valid": valid, "export_id": None,
                  "files": None, "geometry": state.to_dict(), "camera_matrix": state.camera_matrix.tolist(),
                  "image_size": list(state.image_size), "distort_coeffs": state.distortion_coefficients.tolist()}
        record["geometry"]["T_C_T"] = state.transform("C", "T").tolist()
        if duplicate:
            record.update(valid=False, reasons=["duplicate_pose"], reason_text="重复姿态未加入有效数据集")
        if valid:
            record["files"] = self._pair(frame.jpeg_bytes, state.quaternion_wxyz)
            self.valid_count += 1
            record["export_id"] = self.valid_count
        self.records.append(record)
        self.checkpoint(force=self.project.sampling.mode == "手动采样")
        return record

    def checkpoint(self, force=False):
        if not force and len(self.records) % 5 and time.monotonic() - self.last_checkpoint < 1:
            return
        state = self.engine.solve()
        status = state.fixed_extrinsics
        gt = {
            "dataset_schema_version": 1, "conventions": coordinate_metadata(), "matrix_layout": "row-major",
            "fixed_extrinsics": status.is_fixed,
            "T_G_C_fixed": None if status.fixed_transform is None else status.fixed_transform.ravel().tolist(),
            "fixed_extrinsics_message": status.message,
            "T_W_T": state.world_pose("T").ravel().tolist(),
            "imu": {"parent": self.project.scene.imu.parent,
                    "T_parent_I": state.transform(self.project.scene.imu.parent, "I").ravel().tolist(),
                    "R_A_W": state.transform("A", "W")[:3, :3].ravel().tolist(),
                    "T_I_G_fixed": state.transform("I", "G").ravel().tolist() if state.imu_relative_is_fixed else None,
                    "model_message": state.imu_limitation_message},
            "gimbal": asdict(self.project.scene.gimbal),
            "frames": [{"plan_id": record["plan_id"], "export_id": record["export_id"],
                        "T_G_C": np.array(record["geometry"]["T_G_C"]).ravel().tolist(),
                        "T_C_T": np.array(record["geometry"]["T_C_T"]).ravel().tolist()}
                       for record in self.records],
        }
        self.document.update(valid_count=self.valid_count, failed_count=len(self.records) - self.valid_count,
                             attempted_count=len(self.records), coverage=coverage_report(self.records, self.project.sampling),
                             failure_reasons=dict(Counter(reason for record in self.records if not record["valid"] for reason in record["reasons"])))
        for message in (state.imu_limitation_message, "" if status.is_fixed else status.message):
            if message:
                self.document["coverage"]["warnings"].append(message)
        _write_yaml(self.root / "ground_truth.yaml", gt)
        _write_json(self.document, self.root / "experiment.json")
        self.last_checkpoint = time.monotonic()

    def finish(self, status, reason, error=None, *, cancel_event=None):
        if status not in ("completed", "partial", "cancelled", "failed"):
            raise ValueError("非法实验终止状态")
        self.document.update(status="failed" if status == "failed" else "validating", completion_reason=reason,
                             target_reached=self.valid_count >= self.project.sampling.count,
                             completed_utc=datetime.now(timezone.utc).isoformat(), error=error)
        self.checkpoint(force=True)
        from gimbal_lab.domain.replay import Dataset
        # Pairing, hashes, quaternion direction and scene consistency are checked.
        if status != "failed":
            Dataset(self.root, allow_incomplete=True)
        if status != "failed" and cancel_event is not None and cancel_event.is_set():
            status = "cancelled"
            self.document["completion_reason"] = "user_cancelled"
        self.document["status"] = status
        _write_json(self.document, self.root / "experiment.json")
        return self.root


def generate_dataset(project: Project, root: Path, *, settings=None, cancel_event=None, progress=None):
    frozen = deepcopy(project)
    plan = CandidatePlan(frozen.scene, frozen.sampling)
    writer = ExperimentWriter(frozen, root, settings, plan.initial)
    cancel_event = cancel_event or threading.Event()
    try:
        for candidate in plan:
            if cancel_event.is_set():
                return writer.finish("cancelled", "user_cancelled", cancel_event=cancel_event)
            frame = render_frame(writer.engine.solve(candidate.yaw_deg, candidate.pitch_deg), writer.settings)
            if cancel_event.is_set():
                return writer.finish("cancelled", "user_cancelled", cancel_event=cancel_event)
            record = writer.add(candidate, frame)
            if progress:
                progress(record, frame, writer.valid_count, len(writer.records) - writer.valid_count)
            if cancel_event.is_set():
                return writer.finish("cancelled", "user_cancelled", cancel_event=cancel_event)
            if writer.valid_count >= frozen.sampling.count:
                return writer.finish("completed", "target_reached", cancel_event=cancel_event)
        reason = "strict_plan_finished" if frozen.sampling.strict else "max_attempts_exhausted"
        return writer.finish("partial", reason, cancel_event=cancel_event)
    except Exception as exc:
        writer.document["failed_candidate"] = candidate.to_dict() if "candidate" in locals() else None
        writer.finish("failed", "exception", str(exc))
        raise


class ManualSession:
    def __init__(self, project, root, settings=None):
        frozen = deepcopy(project)
        frozen.sampling.mode = "手动采样"
        self.writer = ExperimentWriter(frozen, root, settings)

    @property
    def root(self):
        return self.writer.root

    def add_pose(self, scene):
        if self.writer.document["status"] != "generating":
            raise ValueError("手动实验已结束，请新建实验")
        if scene_signature(scene) != self.writer.document["scene_signature"]:
            raise ValueError("机械、相机或标定板参数已改变；已有手动实验保留旧快照，请结束后新建实验")
        yaw, pitch = scene.yaw.angle_deg, scene.pitch.angle_deg
        candidate = Candidate(len(self.writer.records) + 1, yaw, pitch, "manual")
        duplicate = any(record["valid"] and abs(record["yaw_deg"] - yaw) < 1e-6 and abs(record["pitch_deg"] - pitch) < 1e-6 for record in self.writer.records)
        try:
            frame = None if duplicate else render_frame(self.writer.engine.solve(yaw, pitch), self.writer.settings)
            record = self.writer.add(candidate, frame, duplicate)
        except Exception as exc:
            self.writer.document["failed_candidate"] = candidate.to_dict()
            self.writer.finish("failed", "exception", str(exc))
            raise
        return record, frame

    def finish(self, cancelled=False, *, cancel_event=None):
        return self.writer.finish("cancelled" if cancelled else "completed", "manual_cancelled" if cancelled else "manual_finished", cancel_event=cancel_event)
