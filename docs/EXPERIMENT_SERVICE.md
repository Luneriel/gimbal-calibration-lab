# 实验执行服务与适配契约

版本：平台 0.4.0，适配预设/请求/计划/记录 Schema 1。GUI、Python 和 CLI 共同调用 `gimbal_lab.experiments.service.ExperimentService`。坐标与单位只以 COORDINATES.md 为准，模拟数据集规则见 DATASET_FORMAT.md。提供基础独立评价及重复/子集实验。

## 使用方式

GUI 仍保留原有顺序：选择程序预设、图片目录、TXT 目录、输出 YAML、开始。首次接入通过“管理预设”保存 JSON，后续直接导入；可执行程序、CMake 目标、CPP 关联工程均使用同一服务。高级设置包含相机配置、超时、人工交互、重复与子集；四个结果页签保持算法对比 / 3D 对比 / 逐帧分析 / 运行日志。

默认启动示例：

```bash
./scripts/run.sh --project examples/calibration.gimbal.json
```

按 Ctrl+3，检查五项设置，点击开始，在实际命令对话框中确认。示例使用独立 OpenCV 基准；自行接入的真实程序必须配置明确接口，不能依靠平台猜测参数。

无 GUI CLI（请求文件的创建方式见 [README](../README.md)；QProcess 使用 QtCore，无需 QApplication）：

```bash
.venv/bin/python -m gimbal_lab.experiments.cli plan \
  --request experiments/request.json --output experiments/plan.json
.venv/bin/python -m gimbal_lab.experiments.cli run --plan experiments/plan.json
# 上一步只展示并返回 confirmation_required，不启动程序。
.venv/bin/python -m gimbal_lab.experiments.cli run --plan experiments/plan.json --confirm
```

计划文件必须尚不存在。检查实际命令、目录、样本及警告后再明确确认。安装项目后同样可调用 `gimbal-lab-experiment`。`baseline-preset` 子命令导出基准预设，`compare run_a/run.json run_b/run.json` 读取记录并生成结构化差异摘要。

Python API：

```python
from gimbal_lab.experiments.presets import baseline_preset
from gimbal_lab.experiments.schema import ExperimentRequest, SubsetSpec
from gimbal_lab.experiments.service import ExperimentService

request = ExperimentRequest(
    preset=baseline_preset().to_dict(),
    dataset_root="experiments/experiment_001",
    output_parent="experiments",
    subset=SubsetSpec(mode="random", count=15, seed=42),
    experiment_kind="repeat", repetitions=3,
)
service = ExperimentService()
plan = service.plan(request)              # 只读检查和预览；无构建/运行
# 调用者审核 plan 后明确授权；不得对未知用户程序自动批准。
summary = service.execute(plan, confirmed=True, confirmation_source="python_api")
```

`run(request, confirmed=True)` 为计划+执行的便捷接口。执行调用本身是同步 API，GUI 在 ExperimentJob/QThread 中调用它，避免阻塞主线程；非 GUI 调用者也可放入自己的线程。可传 `cancel_event=threading.Event()`、`event=callback` 和 `stdin_queue=queue.Queue()`。事件为 phase/log/finished，日志含 stdout/stderr 来源；回调在服务工作线程，不可直接改 GUI 控件。返回对象与磁盘 JSON 可序列化，含运行状态、候选、独立指标、警告、记录路径和运行 ID。

计划摘要涵盖预设、实际命令、程序/源文件标识、数据内容、GT 标识、环境指纹及选择；执行前重新验证。参数、文件、程序、预设或环境改变后必须重新预览。GUI 的确认、CLI --confirm、API confirmed=True 分别写入记录。拒绝确认不会启动进程或创建运行目录。

## 程序适配预设

`AdapterPreset` 支持严格字段校验、save/load。入口为 executable/cmake/cpp。可执行路径保留符号链接语义，尤其保留虚拟环境 Python 路径，不能把它解析成系统 Python 后丢失依赖。

| 字段 | 规则 |
| --- | --- |
| name / preset_version / schema_version | 程序名、用户预设版本、Schema 1 |
| entry_kind / entry_path | executable、cmake 或 cpp；CPP 只是工程关联入口 |
| source_dir / cmake_target / executable_relative | CMake/CPP 明确工程目录、目标及构建目录内产物路径 |
| configure_args | CMake 配置参数数组，默认 Release |
| arguments | 程序参数字符串数组，绝不作为 shell 拼接执行 |
| working_directory | 可配置已存在目录，或本次 run/input/build/output 目录 |
| organization | separate 或 mixed |
| input_model / input_model_description | unknown 或明确的 m3_known_pitch_chain；写清假设 |
| config_overrides | 显式程序配置/轴向规则；不可含 GT 字段，必须有约定说明 |
| environment | 显式字符串环境变量；环境指纹另存，避免泄露父进程全部环境值 |
| requires_interaction | 保留程序窗口，并显示等待人工交互；GUI 可发送 stdin 行 |
| output | 文件/终端解析、字段、单位与方向规则 |

占位符仅允许 `{pictures}`、`{quaternions}`、`{input_dir}`、`{config}`、`{motion}`、`{output}`、`{run_dir}`、`{source_dir}`、`{build_dir}`。不支持属性访问、格式转换或任意代码求值。显示用 shlex.join 帮助阅读；实际 QProcess 始终接收独立 program/arguments。

CMake 使用独立运行目录中的 build：先 `cmake -S source -B build ...`，再 `cmake --build build --target target --parallel 2`。保存实际构建命令、源文件摘要、日志及产物哈希。不自动推断孤立 CPP 的依赖，不修改外部算法源码。自定义工程、编译器/第三方库需用户准备；源文件标识不代替完整可复现构建系统。

## 输入适配与 GT 分离

可以提供 `dataset_root`，或独立 pictures_dir/quaternion_dir/config_file；同级 模拟数据模块 目录可自动识别实验。非 模拟数据模块 输入也可运行，但没有可靠 GT 时全局误差不适用。使用独立目录关联 模拟数据模块 时，文件编号和 SHA256 必须匹配其正式有效集，不能把其它图像误配到该 GT。

图片与 TXT 必须使用无前导零的正整数编号，扩展名为小写 jpg/txt，并一一配对。允许原始编号不连续；子集在私有目录从 1 重新连续编号。TXT 保持原有 wxyz/I→A **字节不变**，不会静默修改轴向或适配算法。

- separate：私有 input/pictures、input/txt；相机配置和 motion.json 位于 input 下。
- mixed：私有 input 下放 1.jpg/1.txt…及配置。
- input_mapping 记录输入 ID、原始有效 ID、模拟数据模块 计划 ID；实际文件摘要独立保存。
- 模拟数据模块 相机配置仅复制相机/棋盘格白名单；不复制 ground_truth.yaml、experiment.json、相机安装或标定板世界位姿。
- 显式提供相机配置及 config_overrides 也拒绝已知 GT/场景快照字段。
- 原始数据只读；运行后核对原始 JPG/TXT 和交付副本，配置/运动文件也核对摘要。
- GT 对照文件 evaluation_truth.json 在外部进程结束后写入记录目录，供评价和 结果分析 复核，不属于程序输入。

这是文件级输入隔离，不是操作系统沙箱；外部程序仍以当前用户权限运行。

未知输入模型保持 unknown，平台不声称完整重现外部程序的内部坐标转换。允许通过显式配置提供 R_gimbal2imubody 等程序参数，但必须说明该参数关系，保留物理原始四元数；不能把某一程序的约定推广到所有挂载。

## 已知双轴输入模型与独立基准

`m3_known_pitch_chain` 是一种明确的**已知机械参数**基准模式：只提供底座、两关节安装/轴向/零位/限位、IMU 安装与 R_A_W、G 安装；删除关节当前角度，不含相机和标定板参数。对实际交付的每个 TXT，以多起点有界最小二乘反解两关节角，再按声明的机械链重建 T_W_G。

检查 IMU 拟合残差、Jacobian 秩和多解；无法可靠反解则标为输入模型不可用，绝不替换成 几何引擎 真值位姿。当前该模式要求 I/G 同在 Pitch；Yaw/Base IMU、其它 G 关系保留模型警告，不能强行提供完整双轴输入。外部程序可另行配置自己的明确输入模型，未实现的模型不能假装已支持。

基准作为独立外部 Python 进程运行 `benchmark.py`，只读取交付的 JPEG、TXT、相机配置和已知模型重建运动表。它对实际图像执行 FAST_CHECK、cornerSubPix 和迭代 PnP，使用原始无标记棋盘角点顺序，**不使用 GT 排列对齐**。它检查至少三个姿态、非平行旋转和平移方程秩后，实际调用 OpenCV PARK/TSAI/HORAUD calibrateHandEye。输入回执中的文件摘要与平台交付值核对。

这验证的是在已知运动学输入条件下的求解链路；不声称单靠未知 IMU 姿态就能恢复完整机器人平移。无标记棋盘的固定坐标方向歧义仍存在；若不同帧角点顺序跳变，会影响求解，不能从 GT 偷换正确对应关系。

## 输出解析与规范化

结果可来自：

- file：`output.file_path` 默认为 `{output}`；可为工作目录内的相对文件名。必须位于本次私有运行目录，拒绝已有文件或与输入冲突。
- stdout：整个 stdout 必须是可靠的 YAML 文档。
- markers：只解析用户配置的 begin_marker/end_marker 之间的 YAML，保留外部其它日志；允许多个标记块。

支持安全标准 YAML 及 `%YAML:1.0 / !!opencv-matrix` 的 rows/cols/data 格式。默认 `candidates_path="candidates"`，其内容可以是候选列表或命名映射；空路径表示单一根候选。rotation_path/translation_path 可用点分字段选择，不求值任意表达式。

候选至少有 name、旋转 3×3（或 row-major 9 元素）和平移 3 元素。全部保留原始 R/t、方向/单位、规则、规范 T_G_C 和合法性；非法候选不被丢弃。rotation_source/translation_source 不同时明确标记组合结果。程序推荐及自带指标仅作为原始报告值，不替代平台独立评价，不自动选“最佳”。

方向必须明确为 T_G_C、T_C_G、T_U_V 或 T_V_U；m 平移先转 mm，反向变换明确求逆。U/V 必须给出固定 T_G_U、T_V_C 及映射依据：

```
T_G_C = T_G_U @ T_U_V_est @ T_V_C
```

数值检查使用旋转正交性、det=+1、有限数值和形状；默认不修复非法旋转。可显式启用小误差 SVD 投影，但只接受正交性/det 偏差 ≤1e-6，记录原始矩阵与修正量。所有规范结果平移为 mm。NaN/Inf 在原始文件保留，结构化 JSON 使用 nonfinite_original 表示，不能伪造为零。

输出 YAML 路径保存**平台规范结果**，原始程序文件仍在运行记录目录。多次实验导出 `name_01.yaml`、`name_02.yaml`…；独占发布，不覆盖已有结果。

## 独立评价及 A/B 来源

固定外参成立时，平台对规范 T_G_C 计算相对旋转测地角及平移欧氏距离（°、mm）。角度采用数值稳定的 atan2(sin,cos)，等价于 clamp 后的 trace/acos 定义，避免近 0/180° 时不稳定；不以 Euler 分量差作为主要误差。

动态 GT 时保留输出，T_G_C_true=null、全局误差不适用，不选择任意单帧真值。没有 GT、输入坐标关系不足、数据不足、运动退化、非法结果等均单独记录。退出码为 0 只证明进程成功退出。

平台重新从**实际适配 JPEG**独立检测/PnP 得到 T_C_T，记录检测/求解状态，不读取 模拟数据模块 已做 GT 对齐的角点作为评价输入。该 PnP 是平台独立实现路径，不声称就是未知程序内部的 PnP。

对 `T_W_T_i = T_W_G_i @ T_G_C_est @ T_C_T_i` 分别统计：

- A：T_W_G 来自 几何引擎 仿真真值，明确 depends_on_simulation_truth=true，只作对照。
- B：T_W_G 来自实际 TXT 和声明的输入模型。未知关系时不适用，不用 A 补位。

保存 A/B 输入位姿逐帧旋转/平移差。旋转均值采用 SciPy Rotation.mean 的四元数弦均值，再统计到它的测地角 RMS/max（°）；平移统计到算术均值的距离 RMS/max（mm），并保存逐帧值。未标记板坐标方向不唯一，因此不把板绝对位姿直接与 GT 板原点强行比较。均值一致性不是跨帧独立重投影或完整根因结论。

## 重复与子集

SubsetSpec 支持 all/random/ids，可选 模拟数据模块 关节范围过滤；random 使用固定种子、不放回选择；指定 ID 保留顺序。非 模拟数据模块 无关节记录时拒绝角度过滤。

experiment_kind 为 single/repeat/subsets。repeat 复用完全相同的选择，subsets 使用递增种子，每次都是独立运行/记录/目录。**不同种子不保证子集不同**，计划对此提示，统计按实际输入内容判断。

记录 base_condition_id（程序/二进制/预设、完整数据、已知机械参数、环境、初始 stdin/超时）及 condition_id（再加入实际适配内容和 stdin）。相同条件归入 program_repeatability；基准条件相同、实际子集不同归入 sampling_sensitivity；其它配置不同归入 configuration_difference。每类分别保存候选之间的全部成对差异与最大旋转/平移差，不从差异直接断言程序缺陷。

人工窗口操作无法自动完整记录；stdin 行及时间会保存。存在未观测人工交互时，比较单独标记 uncontrolled_manual_interaction，不能宣称输入条件完全相同。重复候选名称保留但无法可靠跨运行配对，给出警告。

## 执行、记录与边界

QProcess 使用独立 Unix 会话/进程组，实时分流 stdout/stderr，超时/取消先 TERM，必要时 KILL 整组，避免遗留普通子进程。GUI 保持响应；交互预设保留程序自身窗口，可发送 stdin。总输出上限 64 MiB，超出时明确终止并保留截断日志；原始文件/YAML 解析同样有大小限制。主动脱离进程组的外部守护程序不属于普通子进程清理保证。

每次创建全新的 run_UUID，不复用构建/结果；run.json 原子检查点更新，最终保存状态、退出码、实际 argv/cwd、程序/源文件摘要、产物哈希、预设及版本、样本/映射、物理/适配内容 ID、配置来源、环境指纹、原始 stdout/stderr、结果、候选、GT 对照、评价与警告。批次写 batch_UUID.json，包含所有运行及比较摘要。受控失败、取消、解析失败都保留记录；强杀/断电恢复及断点续写未实现。

支持明确配置的通用接口，不自动推断任意第三方程序的依赖、终端格式或坐标模型。请求、预设、运行记录、适配文件和原始输出可以用于脚本化的后续分析。
