# 模块接口

| 模块 | 职责 |
| --- | --- |
| domain.models | 配置、校验和显式坐标元数据 |
| domain.units / rigid / geometry | 单位、刚体与关节运动学 |
| domain.engine / board | 只读几何状态、传感器姿态和棋盘格 |
| domain.persistence | 项目与场景的版本化 JSON |
| domain.camera | 理想成像、实际 JPEG 检测和 PnP |
| domain.sampling / datasets | 有限采样计划、冻结导出、覆盖统计 |
| domain.replay | 实际文件完整性校验及只读回放 |
| experiments.schema / inputs | 预设、请求、子集及适配输入 |
| experiments.process / service | 已确认计划的构建、执行、取消和记录 |
| experiments.results / evaluation | 输出规范化、独立评价及重复/子集比较 |
| experiments.cli | 无图形界面入口 |
| gui | 页面、事务状态、后台任务和独立结果视图 |
| rendering.viewport | 从统一几何状态更新 VTK 场景 |

GUI 不另算传感器位姿；图像、IMU 和真值均来自同一几何查询。

```python
from gimbal_lab.domain.camera import render_frame
from gimbal_lab.domain.engine import GeometryEngine
from gimbal_lab.domain.replay import Dataset

state = GeometryEngine(project.scene).solve(yaw_deg=10, pitch_deg=-5)
frame = render_frame(state)
saved = Dataset("experiments/experiment_001", recheck_images=True)
item = saved.frame(0)
```

实验接口为 `ExperimentService.plan/execute/run`、`AdapterPreset`、`ExperimentRequest`、`SubsetSpec`、`load_run` 和 `compare_run_records`。GUI、Python 和 CLI 共用这些服务；事件回调在工作线程执行，不能直接修改界面。

数学、数据和执行约定分别集中在 [COORDINATES.md](COORDINATES.md)、[DATASET_FORMAT.md](DATASET_FORMAT.md) 和 [EXPERIMENT_SERVICE.md](EXPERIMENT_SERVICE.md)。
