# 坐标系与数学契约（Schema 2）

采用右手系、齐次列向量和内部 mm 单位。**B 定义为底座，T 定义为标定板**。加载项目不会改写源文件。

## 变换与单位

`T_A_B` 将 B 中的齐次列向量转换到 A：`p_A = T_A_B @ p_B`。下标在此为任意坐标系占位符。

- `T_A_C = T_A_B @ T_B_C`。
- 刚体逆：`[R.T, -R.T @ t; 0,1]`。
- 所有内部平移、三维点、尺寸、返回矩阵的平移列均为 **mm**。
- 配置、GUI、JointAngles 和 solve 接口使用 **°**，字段以 `_deg` 命名；三角函数内部使用 rad。
- 转换集中在 domain/units.py：mm_to_m、m_to_mm、deg_to_rad、rad_to_deg。
- rigid.rotation_about_axis 的参数明确为 angle_rad；兼容函数 geometry.axis_rotation 接受 °。
- Schema 2 明确保存单位，拒绝 m/mm、deg/rad、帧约定不匹配，不猜测外部程序的约定。

## 坐标系

| 符号 | 查询 ID | 定义 |
| --- | --- | --- |
| W | world | 世界，X 前、Y 左、Z 上 |
| B | base | 固定底座，位姿 T_W_B |
| JY | yaw_home | 固定在 B 的 Yaw 关节坐标系 |
| Y | yaw | Yaw 运动刚体 |
| JP | pitch_home | 固定在 Y 的 Pitch 关节坐标系 |
| P | pitch | Pitch 运动刚体 |
| C | camera | 光学系，挂载 B/Y/P 可选 |
| I | imu | IMU 本体，挂载 B/Y/P 可选 |
| A | absolute_reference | IMU 绝对参考系，与 W 共原点，方向可配置 |
| T | board | 固定在 W 的标定板，原点为第一内角点 |
| G | gimbal | 求解参考系，挂载 B/Y/P 可选，有独立固定安装位姿 |

另有 yaw_moving / pitch_moving：关节旋转之后、施加子部件零位安装之前的中间帧，供轴套示意模型使用。world_pose("C") 返回 T_W_C；transform("G","C") 返回 T_G_C。符号和完整 ID 均可查询，未知帧报错。

## 安装角与关节

Pose 保存 position_mm=[x,y,z] 和 euler_zyx_deg=[yaw,pitch,roll]，表示子系在父系中的固定安装位姿：

`R = Rz(yaw) @ Ry(pitch) @ Rx(roll)`。

对列向量先作用 Roll、再 Pitch、再 Yaw；等价于固定轴 X/Y/Z 外禀转动或 Z/Y/X 内禀转动，不能交换。GUI 按 Yaw/Pitch/Roll 输入。IMU 的 R_A_W 矩阵反解 Euler 仅用于编辑显示，奇异点采用 Roll=0 的等价解；真实旋转仍为矩阵。

Joint 唯一保存：父/子刚体、installation=T_F_J、J 中的 axis、child_zero=T_J_L_zero、角度及限位。

```
T_F_L(theta) = T_F_J @ Rot_J(axis,theta) @ T_J_L_zero
T_W_Y = T_W_B @ T_B_JY @ Rot_JY(yaw) @ T_JY_Y_zero
T_W_P = T_W_Y @ T_Y_JP @ Rot_JP(pitch) @ T_JP_P_zero
T_W_C = T_W_parentC @ T_parentC_C
T_W_I = T_W_parentI @ T_parentI_I
T_W_G = T_W_parentG @ T_parentG_G
```

轴经过 J 原点，axis 在 J 中定义，按右手正方向旋转。非零有限轴在核心中归一化；零向量、非有限数、非法限位和超限查询被拒绝。没有另一份等价世界轴心参数。

T_F_J 平移在转动前作用，T_J_L_zero 在转动后作用。子刚体原点可偏离真实轴心，显示轴线绑定 J。默认 Yaw +Z、Pitch 局部 +Y。每次从配置及角度重新求解，不累乘上次渲染结果。T_W_T 不随关节或底座改变。

解析基准：Yaw 关节位于世界原点，Pitch 安装 (100,0,0) mm。Yaw=+90°、Pitch=0° 时，Pitch 轴心为 (0,100,0) mm。相机安装为平移 (50,0,0) mm、单位旋转，再令 Pitch=+90°，相机位置为 (0,100,-50) mm。

## 相机与标定板

C 为 OpenCV 光学系：X 右、Y 下、Z 光轴前。默认安装 Rz(-90°) @ Rx(-90°)，使 Z_C 对应 +X_P、X_C 对应 −Y_P、Y_C 对应 −Z_P。渲染直接使用 T_W_C，没有隐藏的朝向修正。

棋盘格默认 11 列×8 行内角点、12×9 方格、40 mm 间距：

- ID = row*columns+column，列先变化。
- T 中角点为 (column*spacing,row*spacing,0)，返回 (N,3) float64。
- 外边界 x∈[-spacing,columns*spacing]、y∈[-spacing,rows*spacing]。
- +X_T 沿列、+Y_T 沿行，真值平面 Z_T=0；渲染直接使用核心方格顶点，边框位于平面之后。
- board_corners("T"/"W"/"C") 返回对应坐标。几何引擎只提供几何；成像模块、像素中心、检测排列和文件契约见 [DATASET_FORMAT.md](DATASET_FORMAT.md)，不另建坐标约定。

## G 与固定外参

默认 G=P、安装为单位变换。核心和世界节点的高级属性支持 G 固定于 B/Y/P 及任意合法安装。

`T_G_C = inverse(T_W_G) @ T_W_C`。

C/G 同属一个刚体时，T_G_C = inverse(T_body_G) @ T_body_C，对所有关节运动固定，轴心偏移不影响此不变量。不同刚体之间存在独立关节时，全运动关系为动态。核心同时检查拓扑和合法姿态变换；只有固定模型返回 fixed_transform，否则为 None，始终保留每帧 T_G_C。

单帧、重复姿态或某个耦合计划看似不变，不能证明全运动模型固定。

## IMU 参考与四元数

reference_rotation_aw 明确为固定 **R_A_W**，须为合法 3×3 旋转矩阵。

```
T_W_A = [R_A_W.T, 0; 0,1]
R_A_I = R_A_W @ R_W_I
q_A_I = quaternion_wxyz(R_A_I)
```

q 为 Hamilton、右手、主动旋转，顺序 **w x y z**，表示 I → A，输出为单位四元数。q 与 −q 等价；采用规范符号（w≥0，w=0 时首个非零向量分量为正），不保证跨 180° 的时间符号连续性。

I 在 P 时包含两关节运动，在 Y 时不随 Pitch 改变，在 B 时不随关节改变。核心同时报告 I 相对 G 缺失或额外的关节运动，不把非同刚体的原始 IMU 姿态强行当作 G 姿态。拓扑覆盖也不等同于全部可观测性或从姿态恢复位置的保证。

## 数值验证

旋转合法性检查使用正交性与 det=+1，绝对容差 1e-10；齐次末行容差 1e-12，四元数单位范数容差 1e-10。生成的标准旋转通常达到约 1e-15 误差。

独立解析/小矩阵测试使用旋转约 1e-14、毫米链约 1e-12；随机含多次安装、约 1000 mm 杠杆的独立 SciPy 链比较使用 1e-10 mm、rtol=0。固定外参内部数值核对采用旋转元素 128*eps、平移 256*eps*max(1,安装平移范数总和) mm，反映浮点链长和消差规模。这些是数学运算检查，不是标定误差阈值。
