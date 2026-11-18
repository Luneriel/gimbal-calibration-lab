# 模拟数据与回放契约

本文件定义数据集 Schema 1。项目/场景继续使用 Schema 2，旧项目缺省 `sampling.max_attempts=0`。坐标、安装角和运动学只以 [COORDINATES.md](COORDINATES.md) 为准；模拟数据模块 直接消费 [GeometryEngine / SceneState](GEOMETRY_ENGINE.md)，不从 VTK 模型或屏幕截图推算位姿。

## 相机成像与棋盘格

每个候选姿态只求解一次 几何引擎 状态，图像、IMU 和几何记录均取自该状态：

```
T_C_T = inverse(T_W_C) @ T_W_T
p_C = T_C_T @ p_T
u = fx * X_C / Z_C + cx
v = fy * Y_C / Z_C + cy
R_A_I = R_A_W @ R_W_I
T_G_C = inverse(T_W_G) @ T_W_C
```

C 为 OpenCV 光学系（右、下、前）；像素中心使用整数坐标，原图左上角像素中心为 (0,0)。K 的单位为 px，平移/三维点为 mm，关节角为 deg。相机宽、高、fx/fy/cx/cy 均来自冻结场景。

默认棋盘格为 11×8 内角点、12×9 方格、40 mm 间距。内角点 `(j*d,i*d,0)`，编号 `i*cols+j`；外边界为 `[-d,cols*d] × [-d,rows*d]`。第一内角点位于外边界向内一个方格处，纹理不使用内角点边界充当整张棋盘边界。

渲染器按核心方格奇偶生成黑白平面纹理，通过平面单应矩阵投影到白色背景。默认每方格 80 个纹素、2 倍超采样、线性透视插值后面积下采样，JPEG 质量 98。纹素中心对应 `((i+.5)/80-1)*d`；超采样内参为 `fx'=s*fx, cx'=s*cx+(s-1)/2`（Y 同理），避免半像素或整格偏移。实时预览展示的就是这条链路编码、重新解码后的实际 JPEG。

模拟数据模块 支持理想、无噪声、零畸变成像。**非零 k1/k2/p1/p2/k3 明确拒绝**，不允许 YAML 声明了未实施的畸变。噪声控件禁用。默认超采样像素预算 1600 万，超出时明确报错；不偷偷降低分辨率或改变 K。白背景、双面平面纹理、无光照/遮挡/镜头模糊是当前成像边界。

## 有效性与方向歧义

`geometric_valid` 和 `detected_valid` 分别记录，正式导出还要求 PnP 检查通过。

1. 外边界全部在相机前方，且完整保留至少 8 px 图像边界余量；投影方格每条边至少 8 px。
2. 对实际解码 JPEG 执行 `findChessboardCorners(ADAPTIVE_THRESH | NORMALIZE_IMAGE | FAST_CHECK)`，必须得到 `cols*rows` 个角点。
3. `cornerSubPix` 窗口 (5,5)，迭代上限 60、epsilon=1e-4。
4. 比较原始角点的恒等、180°、行翻转、列翻转四种排列与理论投影，记录最佳排列和原始/对齐角点。默认角点 RMSE 上限 0.75 px。
5. 对齐角点执行 `solvePnP(..., SOLVEPNP_ITERATIVE)`；解应使所有角点在相机前方，重投影 RMSE ≤0.75 px。

棋盘格没有唯一方向标记。**排列选择使用已知模拟 GT，仅用于检测与验证**，每帧写 `alignment_uses_ground_truth: true`；不代表未知场景能从无标记图像唯一恢复板坐标方向。原始 JPG 和原始检测角点均保留，正式图片未被叠加检测标记。外部程序接入时必须在 实验服务 明确其角点/板坐标规则。

PnP 的旋转/平移真值误差也记录在每帧 `metrics` 中；它是单帧图像验证结果，不是手眼标定或跨帧算法误差。核心数值、图像有效性与采样覆盖是三个不同层次。

原因代码包括 `board_behind_camera`、`board_crosses_camera_plane`、`board_outside_fov`、`projected_cells_too_small`、`corners_not_detected`、`corner_order_mismatch`、`pnp_failed`、`pnp_reprojection_failed`、`duplicate_pose`，并有可读中文说明。几何无效时不将未执行检测误报为检测成功。

## 采样与冻结

默认自动采样：30 组有效样本、Yaw ±30°、Pitch ±15°、种子 42、分层均匀、无噪声。

- 分层均匀：先中心、四个组合边界及两轴边界（最多 9 组），剩余初始点采用各轴分层随机排列。少量目标数只使用相应前缀，因此可能存在退化，覆盖检查会提示。
- 均匀随机：初始计划在原请求范围内独立均匀采样。
- 自动补充：初始计划无效后继续在**原请求范围**内随机尝试，直到有效数量达标或预算耗尽。`max_attempts=0` 使用 `max(50,10*count)`；显式预算必须 ≥目标数。
- 严格采样：只执行完整固定初始计划，不替换失败候选。失败不进入正式图片集，仍保留原始计划号与失败原因。
- 手动采样：保存当前关节角，使用同一渲染/验证/导出逻辑；与已保存有效姿态两轴差均小于 1e-6° 时记录 `duplicate_pose`，不重复导出。点击“结束手动实验”结束，数量由实际保存决定，`target_reached` 独立记录，不以自动目标数阻止手动结束。

超出关节限位的采样范围被拒绝，不自动裁剪。开始任务时深拷贝完整项目/场景；初始计划、种子、渲染设置及实际候选顺序都保存。候选、JPG、TXT、GT 来自相同冻结快照和同一 `SceneState`。生成期间编辑场景只影响编辑器；数据页提示旧实验属于原快照。手动会话只允许改变当前关节角，改变机械/相机/板/参考系后要求结束旧实验再新建。

“采样示例（宽视场）”预设仅将相机 fx/fy 设为 520 px，其余为理想双轴默认结构。已验证默认 ±30°/±15° 的 30 组有效图像及完整跨度。原场景 fx/fy=950 px 不会被自动修改；该场景可补足数量，但边界常超视野，实际覆盖会明确报告。载入示例为用户显式操作。

覆盖统计只使用有效样本：实际两轴最小/最大值、请求跨度占比、6 位小数下的唯一姿态数/重复数、按请求跨度归一化的协方差特征值、相对首帧 IMU 的最大旋转角。提示条件：跨度占比 <75%、任一轴变化 <2°、协方差小/大特征值比 <0.02、IMU 变化 <2°、有效数 <3，以及 几何引擎 原有 IMU/G 模型限制。`heuristics_only: true`，不将图像有效或跨度充分等同于标定可观测性。

## 目录和文件

```
experiment_001/
├── pictures/1.jpg, 2.jpg, ...
├── txt/1.txt, 2.txt, ...
├── calibration.yaml
├── ground_truth.yaml
└── experiment.json
```

有效样本从 1 连续编号；第 5 个候选失败时不会占用图片序号。清单记录 `plan_id → export_id`；失败的 `export_id/files` 为 null。文件路径相对于实验根目录，禁止绝对路径或越出目录的路径。

GUI 选择已有**父目录**，在其中寻找未使用的 `experiment_###`，独占创建实验目录。核心 API 要求一个尚不存在的实验根目录，拒绝覆盖任何已有目录。

### TXT

恰好一行 4 个有限浮点数：

```
w x y z
```

Hamilton 单位四元数，方向 **I → A**。每项以 17 位有效数字保存，读回校验单位范数及对应 `R_A_I`。规范符号见坐标契约，不承诺跨 180° 时符号连续。TXT 不包含时间戳或额外 IMU 轴向适配。

### calibration.yaml

| 字段 | 含义 |
| --- | --- |
| dataset_schema_version | 1 |
| pattern_type | chessboard |
| pattern_cols / pattern_rows | 内角点列/行数，不是方格数 |
| center_distance_mm | 相邻内角点距离，mm |
| image_width / image_height | 原始 JPG 分辨率 |
| camera_matrix | K 的 9 元素数组，row-major |
| distort_coeffs | k1,k2,p1,p2,k3；模拟数据模块 必须全 0 |
| matrix_layout / camera_intrinsic_unit / translation_unit | row-major / px / mm |
| quaternion_order / quaternion_direction | wxyz / I_to_A |
| adapter_parameters.R_gimbal2imubody | applicable=false，记录未绑定具体适配规则的原因 |

该 YAML 使用通用数组，不带 OpenCV 私有 `!!opencv-matrix` 标签。例如宽视场示例的 K 为 `[520,0,640,0,520,480,0,0,1]`。实验服务 可在有明确消费者时转换其文件格式。

**没有顶层通用 `R_gimbal2imubody` 数值矩阵**。模拟数据模块 不假设任何外部程序的 IMU 轴映射，也不把 I/G 动态关系硬编码成固定安装旋转。

### ground_truth.yaml

变换 4×4 展平为 16 元素、旋转 3×3 展平为 9 元素，均 row-major；坐标及 mm/deg 在 `conventions` 中声明。

- `fixed_extrinsics`、`fixed_extrinsics_message`：几何引擎 全运动模型判定。
- `T_G_C_fixed`：仅固定模型有值，否则 null。
- `T_W_T`：固定标定板世界位姿。
- `imu.parent / T_parent_I / R_A_W / T_I_G_fixed / model_message`：安装、绝对参考方向、可选刚性关系及限制。
- `gimbal`：G 的挂载及安装配置。
- `frames[]`：全部已尝试候选（包含失败）的 `plan_id / export_id / T_G_C / T_C_T`。

动态 G/C 配置始终保存逐帧 T_G_C，明确固定假设不成立。单次采样中看起来不变也不能冒充固定模型。

### experiment.json

`dataset_schema_version=1`，含唯一实验 ID、创建/结束时间、`project_snapshot`、静态场景 SHA256、坐标约定、采样参数、种子、渲染设置和 OpenCV/NumPy 版本。场景摘要排除预设名及当前关节角；每帧角度另存。

- `initial_plan`：完整初始候选计划，包括未执行部分（如取消）。
- `candidates`：全部实际尝试，含 source=initial/supplement/manual、plan_id、角度、几何/视觉有效性、失败原因、文件映射和 SHA256。
- 每帧 `geometry`：几何引擎 的完整世界矩阵、R_A_I、四元数、T_G_C 及模型状态，另含 T_C_T；每帧还包含 K、分辨率、畸变。JSON 矩阵为嵌套行数组。
- 理论/原始检测/对齐角点、排列名称、单帧 PnP 和误差；无有效深度时理论像素为 null，不写 NaN。
- `valid_count / failed_count / attempted_count / failure_reasons / coverage`：数量、原因与实际覆盖；`target_reached` 与终止原因单独保存。
- `status`：generating → validating → completed/partial/cancelled/failed。partial 表示严格计划或预算结束但有效数未达目标；cancelled 即使已输出样本也不标为完成。

## 导出、取消与回放

每对 JPG/TXT 先写临时文件并 fsync，再提交；受控异常回滚该对已提交文件，清理临时文件。元数据使用临时文件+原子替换，批量期间最多每 5 次候选或约 1 秒写检查点，手动逐次检查点。结束前检查配对、连续编号、文件摘要、JPEG 尺寸、TXT 方向、YAML 参数和 几何引擎/逐帧 GT 一致性。最终校验期间收到的取消也保存为 cancelled。

跨两个文件的提交无法对强杀/断电保证操作系统级事务；此时数据可能停留 generating，普通回放拒绝把它当作完成实验。没有实现断点续写或崩溃后自动修复。正常取消、关闭窗口和注入写入异常有自动化测试。

`Dataset(root)` 只读实际文件，验证冻结快照/元数据和文件完整性；`recheck_images=True` 额外对实际 JPG 复检。`frame(index)` 再次核对加载后文件 SHA256，返回实际解码 JPG、实际 TXT、同快照 几何引擎 状态。失败候选无 JPG/TXT，诊断显示失败原因并可恢复 3D 几何。

GUI 上一帧/下一帧/滑块及独立 3D 回放共用 ReplayController；其 SceneState、项目和 VTK 实例独立于正在编辑的 AppState。检测角点叠加、适应/1:1、滚轮缩放和拖动仅作用于显示，不修改 JPG、K 或导出分辨率。

## 读取与兼容范围

```python
from gimbal_lab.domain.replay import Dataset, sequential_format_check

dataset = Dataset("experiments/experiment_001", recheck_images=True)
frame = dataset.frame(0)
format_report = sequential_format_check("experiments/experiment_001")
```

`sequential_format_check` 模拟连续 JPG/TXT 读取，检查四元数并载入 YAML。它只检查输入格式，不代表已执行标定程序。程序适配、运行与基础真值评价由 [ExperimentService](EXPERIMENT_SERVICE.md) 提供。
