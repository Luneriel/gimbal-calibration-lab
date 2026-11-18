# 几何引擎

## 模型与边界

核心全部位于 `domain/`，只依赖 NumPy/SciPy，无 Qt、PyVista、VTK 或标定算法依赖。

| 模块 | 职责 |
| --- | --- |
| models | Pose、Joint、Camera、Imu、GimbalReference、Board、Scene、Project；配置校验及约定元数据 |
| units / rigid | 明确单位转换、SO(3)/SE(3) 校验、轴角/Euler、逆、点变换、wxyz |
| geometry | T_F_J @ Rot_J @ T_J_L_zero；兼容查询 frame_transforms 转调同一引擎 |
| board | 行优先角点、方格顶点/奇偶及外边界 |
| engine | GeometryEngine、JointAngles、只读 SceneState、固定外参与 IMU 模型状态 |
| persistence | 场景/项目 JSON、严格验证、原子写入 |

拓扑固定为 B → Y → P。Joint 明确保存 parent/child、installation（T_F_J）、局部 axis、child_zero（T_J_L_zero）、角度及限位。Camera、Imu、GimbalReference 共用 parent+installation 的刚性挂载结构；标定板固定在 W。详见 [COORDINATES.md](COORDINATES.md)。

输入 Scene 是唯一配置。引擎构造时复制配置、缓存静态安装；config 返回副本。配置改变时创建新引擎，GUI 自动完成此步骤。每次 solve 从给定关节角度重新计算，不累积上一帧。SceneState 的内部数组由不可写 bytes 支撑；公开位姿和角点返回副本，调用者不能破坏后续计算。

## 状态查询

```python
from gimbal_lab.domain.models import Scene
from gimbal_lab.domain.engine import GeometryEngine, JointAngles, solve_scene

engine = GeometryEngine(Scene())
state = engine.solve(yaw_deg=30, pitch_deg=15)
T_W_C, T_W_G, T_G_C = state.T_W_C, state.T_W_G, state.T_G_C
T_C_T = state.transform("C", "T")
object_points_mm = state.board_corners("T")  # (88,3), col changes fastest
q_wxyz = state.quaternion_wxyz               # unit quaternion, I -> A
K = state.camera_matrix
width, height = state.image_size

states = engine.solve_many([(0, 0), JointAngles(30, 15)])
for sample in engine.iter_states([(0, 0), (20, -10)]):
    per_pose_truth = sample.to_dict()        # JSON-compatible, not a dataset
```

solve_scene 是一次性便捷函数；批量查询宜复用引擎。未传入的角度使用构造时 Scene 的角度，显式参数不修改输入。超限/非有限查询报 ValueError；非法批量项标明计划序号。

| 查询 | 返回 |
| --- | --- |
| world_pose(frame) | T_W_frame，支持 W/B/Y/P/C/I/A/T/G、JY/JP、完整 ID |
| transform(target,source) | T_target_source；同帧精确单位变换，未知帧报错 |
| T_W_C、T_W_G、T_G_C、T_W_I | 有明确方向和 mm 平移列的真实位姿 |
| R_A_I、quaternion_wxyz | 理想绝对姿态，非算法估计 |
| board_corners(frame="T") | 已定义帧中的稳定三维角点 |
| board | 局部角点、方格顶点、奇偶和外边界 |
| camera_matrix、distortion_coefficients、image_size | K、保存的畸变参数、分辨率；尚不做畸变成像 |
| camera_frustum(depth_mm) | C 中光心与 4 个角射线端点 |
| joint_axes_local / joint_axes_world | 归一化局部/世界关节轴 |
| fixed_extrinsics | 固定性、相关关节、可选固定 T_G_C、数值探测信息 |
| imu_missing_joints_for_g / imu_extra_joints_for_g | I 相对 G 缺失或额外的关节运动 |
| imu_relative_is_fixed / imu_limitation_message | I/G 的刚性关系及限制说明 |
| frames | 全部世界矩阵副本；包含关节 home/moving 中间帧 |

## 固定外参和 IMU 限制

同刚体 C/G 严格满足 inverse(T_body_G) @ T_body_C 不变量。引擎检查真实挂载路径，并执行合法范围中点及两个关节各自两端的 5 个数值探测；同刚体解析关系与数值不符时抛出异常。数值容差依据 float64 eps、链长和杠杆规模，详见坐标契约。

不同刚体的全运动关系判为动态，即使当前一帧或重复采样恰好相同，也不返回固定矩阵：fixed_transform=None。每帧 T_G_C 始终可查询。数值探测不是采样覆盖或可观测性分析。

IMU 世界位姿按实际挂载求解，再独立应用 R_A_W。I/G 不同刚体时提示缺失或额外运动；不自动把原始四元数转换成算法输入。几何引擎只提供运动学状态，不进行标定求解。

## 序列化与默认值

完整项目 save_project/load_project 保存场景及采样/程序路径草稿，format_version=2。独立场景 save_scene/load_scene 的封装包含 kind="gimbal_lab.scene"、schema_version=2、conventions、scene。

项目根 name、scene、format_version 必填，Schema 2 的 conventions 必须匹配显式 mm/deg、右手列向量和帧定义。sampling/calibration 可省略为默认草稿。Scene 内省略字段使用 models.py 的 dataclass 默认：理想双轴、单位底座、Yaw 轴心 (0,0,90)、Pitch 轴心 (0,0,125)、默认相机/IMU/棋盘格。

新字段缺省为 child_zero=I、G 固定于 Pitch 且安装为 I、R_A_W=I。版本 1 项目按旧版明确的 mm/deg 字段加载并补齐上述值，内存版本升为 2；只有用户保存才写入新版，加载不改写源文件。未知字段/版本、非法旋转/限位/挂载、非有限数和不匹配约定均拒绝。不猜测其他厂商格式，也未开发复杂迁移系统。

保存先验证并序列化，再同目录临时写入、fsync 和原子替换；无效输入不覆盖现有项目。GUI 加载在验证及求解成功后才提交。

## GUI

保留暗色主题、三页和三栏。AppState 在提交参数前求解并更新统一 geometry；渲染只读该 SceneState 的矩阵、轴、棋盘方格和视锥。轴套绑定关节帧，子刚体绑定含 child_zero 的真实刚体帧，不加算两遍位移。

- 世界节点 → Gimbal 参考系 G：父部件、固定安装与外参模型状态。
- 关节 → 安装姿态与关节限位 → 子部件零位安装。
- IMU → 姿态参考与四元数：R_A_W 的 Euler 编辑与真实 q_A_I。
- 相机 → 真实几何位姿：t_W_C、t_G_C 和固定/动态状态。
- 视图下方显示 G 的挂载与固定/逐帧外参状态。

成像、数据集和回放共用几何状态，见 [DATASET_FORMAT.md](DATASET_FORMAT.md)。外部程序执行与基础评价见 [EXPERIMENT_SERVICE.md](EXPERIMENT_SERVICE.md)。

## 示例与适用范围

- `examples/analytic.scene.json`：可手算的组合运动。
- `examples/geometry_offset.gimbal.json`：轴心偏移、关节零位和非对齐参考系。
- `examples/geometry_dynamic.gimbal.json`：动态外参及 IMU 运动限制。

示例项目可以通过项目菜单或 `scripts/run.sh --project` 打开。输入与输出位置需自行选择。

模型为固定双轴结构，不模拟碰撞、间隙、弹性或动力学。机械外观是示意，真实枢轴、轴向、传感器坐标由核心决定。A 与 W 共原点，支持固定方向关系。四元数规范符号不保证时间连续，拓扑覆盖也不等于完整可观测性。
