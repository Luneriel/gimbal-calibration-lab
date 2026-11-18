# Gimbal Calibration Lab

面向 Ubuntu 的本地桌面几何标定实验平台，提供双轴云台场景编辑、相机与 IMU 模拟数据生成、实验回放、外部标定程序适配和独立结果评价。界面采用暗色主题，运行不需要网络服务。

## 安装

推荐 Ubuntu 22.04、Python 3.10。先安装图形库：

```bash
sudo apt update
sudo apt install python3.10-venv libgl1 libegl1 libxcb-cursor0 \
  libxkbcommon-x11-0 libxcb-xinerama0 libxcb-render-util0 libxcb-image0 \
  libxcb-keysyms1 libxcb-icccm4 libsm6 libice6 fonts-noto-cjk
```

在项目根目录创建环境并安装依赖：

```bash
python3.10 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
./scripts/run.sh
```

也可使用 `uv sync --frozen`。需要命令行入口时，额外执行 `.venv/bin/python -m pip install --no-deps -e .`。接入 CMake 工程还需要 `cmake`、C++ 编译器及目标工程声明的依赖。

Wayland 桌面默认通过 xcb/XWayland 嵌入三维视图。离线安装可提前在相同平台下载依赖 wheel，运行时不下载模型或素材。

## 使用

### 场景搭建

```bash
mkdir -p experiments
./scripts/run.sh --project examples/sampling.gimbal.json --size 1366x768
```

通过对象树或三维视图选择关节、相机、IMU 和标定板，编辑安装位置、旋转轴、关节零位及传感器参数。支持项目保存与加载、三维旋转/平移/缩放，以及 Yaw/Pitch 滑块和精确输入。

长度统一为 mm、角度为 °。`T_A_B` 将 B 中坐标转换到 A；IMU 四元数为 Hamilton `w x y z`，方向 I→A。

### 模拟数据生成

按 **Ctrl+2**，选择输出父目录后生成数据。支持自动补充、严格计划和手动保存，包含重复提示、有效性检测、覆盖统计、取消和失败记录。

宽视场示例默认采样 Yaw ±30°、Pitch ±15°、30 组有效样本。每个实验输出：

```text
experiment_001/
├── pictures/1.jpg, 2.jpg, ...
├── txt/1.txt, 2.txt, ...
├── calibration.yaml
├── ground_truth.yaml
└── experiment.json
```

生成时冻结场景，图像、四元数和真值来自同一采样状态。数据页可打开实验并回放实际文件；独立三维回放不会修改正在编辑的场景。

### 标定验证

按 **Ctrl+3**，依次选择程序预设、图片目录、TXT 目录和输出 YAML，点击开始并确认实际构建/运行命令。

支持本地可执行程序、明确的 CMake 目标，以及 CPP 文件关联工程。预设保存参数数组、工作目录、输入组织、解析规则、输出方向和单位。执行支持实时 stdout/stderr、超时、停止及交互输入。

结果保留全部候选及来源，提供独立真值误差、板位姿一致性、逐帧诊断和三维对比。高级设置可以执行相同输入重复实验，或比较随机、指定编号、角度过滤的样本子集。原始数据和已有结果不会被覆盖。

内置 OpenCV 基准使用明确的已知双轴运动学输入。接入其他标定程序时，需要根据其实际接口配置适配规则。

## Python 与命令行接口

GUI 和无图形接口共用 `ExperimentService`。使用 Python 或 CLI 前执行 `.venv/bin/python -m pip install --no-deps -e .`。先在界面中选择 `experiments` 作为输出父目录并生成数据，然后在项目根目录准备请求：

```python
import json
from pathlib import Path
from gimbal_lab.experiments.presets import baseline_preset
from gimbal_lab.experiments.schema import ExperimentRequest

request = ExperimentRequest(
    preset=baseline_preset().to_dict(),
    dataset_root="experiments/experiment_001",
    output_parent="experiments",
)
Path("experiments/request.json").write_text(
    json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
    encoding="utf-8",
)
```

检查计划后明确确认执行：

```bash
.venv/bin/python -m gimbal_lab.experiments.cli plan \
  --request experiments/request.json --output experiments/plan.json
.venv/bin/python -m gimbal_lab.experiments.cli run \
  --plan experiments/plan.json --confirm
```

不带 `--confirm` 不启动程序。计划文件必须尚不存在；每次运行创建独立记录。安装命令行入口后也可使用 `gimbal-lab-experiment`。

## 适用范围

当前成像为理想零畸变、无噪声的平面棋盘格，非零畸变配置会被拒绝。无标记棋盘的方向存在对称歧义；样本数量或覆盖充分不代表完整可观测性。

已知双轴输入模型要求 IMU 和 G 同在 Pitch。未知输入关系、动态外参和非法输出会明确标为不可可靠评价，不使用任意单帧真值替代全局真值。外部程序成功退出也不代表标定结果可靠。

平台不自动推断任意 CPP 的第三方依赖、未知坐标约定或任意终端输出格式；复杂噪声、动力学、系统性根因分析及崩溃恢复不在当前功能范围内。

## 文档与数据管理

- [坐标与单位](docs/COORDINATES.md)
- [几何引擎](docs/GEOMETRY_ENGINE.md)
- [数据集格式](docs/DATASET_FORMAT.md)
- [实验服务与适配接口](docs/EXPERIMENT_SERVICE.md)
- [界面操作](docs/GUI_SPEC.md)
- [模块接口](docs/INTERFACES.md)

示例配置不包含本机目录，使用时自行选择输入和输出位置。日志、数据集、实验记录、虚拟环境及个人配置均不应提交；默认忽略 `artifacts/`、`experiments/`、`.venv/` 和环境变量文件。运行记录可能包含所选文件位置，分享前应单独检查。
