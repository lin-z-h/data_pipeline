# AutoCar 数据处理流水线 (Data Pipeline)

自动驾驶小车的数据处理工具集，提供从**原始采集数据 → 人工审核清洗 → 标准化增强 → tub 训练集**的完整流水线。

---

## 目录

- [项目概述](#项目概述)
- [系统架构](#系统架构)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [模块详解](#模块详解)
  - [data_reviewer — 数据审核清洗](#data_reviewer--数据审核清洗)
  - [data_processor — 数据标准化与增强](#data_processor--数据标准化与增强)
  - [data_launcher — GUI 统一面板](#data_launcher--gui-统一面板)
- [数据传输规范](#数据传输规范)
  - [文件命名规范](#文件命名规范)
  - [驾驶指令与控制量映射](#驾驶指令与控制量映射)
  - [Tub 目录结构规范](#tub-目录结构规范)
  - [meta.json 元数据规范](#metajson-元数据规范)
  - [record_N.json 记录规范](#record_njson-记录规范)
  - [图像分辨率规范](#图像分辨率规范)
- [数据增强规范](#数据增强规范)
- [团队协作指南](#团队协作指南)
  - [目录组织约定](#目录组织约定)
  - [工作流建议](#工作流建议)
  - [Git 管理规范](#git-管理规范)
- [CLI 参数参考](#cli-参数参考)
- [常见问题](#常见问题)

---

## 项目概述

本项目为 AutoCar 自动驾驶小车项目的数据处理核心模块。小车在运行时通过摄像头采集驾驶图像，以散装 `.jpg` 文件的形式存储在 `datas/` 目录中。数据流水线负责将这些原始数据转化为可供模型直接训练的标准化 **tub 格式**数据集。

**核心能力：**

| 环节 | 工具 | 输入 | 输出 |
|------|------|------|------|
| 审核清洗 | `data_reviewer` | 散装 .jpg 图片 | 剔除垃圾图后的干净图片集 |
| 标准化增强 | `data_processor` | 清洗后的图片集 | tub 格式训练集（含可选数据增强） |
| GUI 面板 | `data_launcher` | — | 一键串联上述两个环节 |

---

## 系统架构

```
采集原始数据              审核清洗                标准化 & 增强            模型训练
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ datas_ot1/   │───▶│ data_reviewer│───▶│data_processor│───▶│   tub/       │
│ *.jpg 散装    │    │ X 标记垃圾    │    │ 标准化 + 增强  │    │ 可直接训练    │
│              │    │ 移至 trash/  │    │ 生成 record   │    │              │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

**模块关系：**

```
data_launcher.py  ── GUI 启动器 ──┐
                                  ├──▶ data_reviewer.run_reviewer()
                                  ├──▶ data_processor.create_tub()
                                  └──▶ 日志面板 (LogRedirector)

data_reviewer.py  ── 独立可运行（CLI），也可被 GUI 调用
data_processor.py ── 独立可运行（CLI），也可被 GUI 调用
```

---

## 环境要求

| 依赖 | 版本/说明 |
|------|----------|
| Python | **3.12**（必须，与模型推理环境一致） |
| opencv-python | `pip install opencv-python` |
| tkinter | Python 内置，无需额外安装 |

> **注意：** 项目构建时使用 Python 3.12。请勿使用其他 Python 版本，避免与模型推理端（PyInstaller 打包的 `AdcarV2_3.exe` / `AdcarV2_game2.exe`）产生兼容性问题。

---

## 快速开始

### 方式一：GUI 面板（推荐）

```bash
cd data_pipeline
python data_launcher.py
```

操作流程：
1. 选择数据集目录（如 `user/clockwise-v1/datas`）
2. 点击 **「审核清洗」** → 在 OpenCV 窗口中逐帧审查，按 `X` 标记垃圾图片，按 `Q` 退出
3. 在面板中调整增强参数（高斯模糊/亮度对比度的触发概率）
4. 点击 **「标准化处理」** → 自动在数据集同级目录生成 `tub/` 训练集

### 方式二：命令行分步执行

```bash
cd data_pipeline

# 第一步：审核清洗
python data_reviewer.py user/clockwise-v1/datas -t user/trash

# 第二步：标准化处理（默认增强参数）
python data_processor.py user/clockwise-v1/datas
```

---

## 模块详解

### data_reviewer — 数据审核清洗

**功能：** 以幻灯片方式逐帧播放图片，人工标记质量不合格的数据（模糊、遮挡、错误转向等），审核结束后批量移至垃圾箱。

**运行方式：**

```bash
# 基本用法
python data_reviewer.py [图片目录]

# 指定垃圾箱
python data_reviewer.py user/clockwise-v1/datas -t user/trash
```

**审核窗口快捷键：**

| 按键 | 功能 | 说明 |
|------|------|------|
| `Space` / `D` | 下一张 | 当前图片合格，前进 |
| `A` | 上一张 | 手滑了，回退重新审查 |
| `X` | 标记/取消垃圾 | 标记后自动跳到下一张（极速盲筛）；已标记图片再次按 X 撤销 |
| `Q` / `ESC` | 退出并结算 | 弹出确认对话框，确认后批量移至垃圾箱 |

**界面显示：**

- **左上角：** 当前进度 `[N / Total]`
- **中央：** 驾驶指令标签 `Cmd: FW / TR / TL`（绿/蓝/黄三色区分）
- **底部：** 快捷键操作提示
- **已标记垃圾：** 整张图片覆盖红色半透明遮罩 + "MARKED FOR TRASH" 提示

**命令行示例：**

```bash
python data_reviewer.py                                    # 使用默认路径
python data_reviewer.py E:/autonomous_driving/datas_ot1    # 指定路径
python data_reviewer.py user/anticlockwise-v1/datas -t user/trash
```

---

### data_processor — 数据标准化与增强

**功能：** 将清洗后的散装图片转化为标准 tub 格式，并可选地对图像施加概率性数据增强（高斯模糊、亮度/对比度扰动），扩充训练集多样性。

**核心流程：**

1. 扫描输入目录中所有 `.jpg` 文件
2. 解析文件名，提取时间戳和驾驶指令
3. 将图像统一缩放至目标分辨率 `180×320`（与 `config.py` 中 `CAMERA_RESOLUTION` 一致）
4. 根据指令映射为 `(angle, throttle, mode)` 控制量
5. 对每一帧独立判定是否触发增强（概率独立，两种增强可叠加）
6. 将图片写入 tub 目录，同时生成 `meta.json` 和 `record_N.json` 索引文件

**运行方式：**

```bash
# 基本用法（默认：p=10% 高斯模糊 + p=10% 亮度对比度）
python data_processor.py user/clockwise-v1/datas

# 指定输出目录
python data_processor.py user/clockwise-v1/datas -o custom_tub/

# 自定义触发概率
python data_processor.py user/clockwise-v1/datas --bc-prob 0.3 --blur-prob 0.2

# 关闭特定增强
python data_processor.py user/clockwise-v1/datas --no-blur
python data_processor.py user/clockwise-v1/datas --no-brightness

# 关闭所有增强（纯格式标准化）
python data_processor.py user/clockwise-v1/datas --no-augment

# 覆盖模式：增强替代原图，不增加数据量
python data_processor.py user/clockwise-v1/datas --replace
```

**输出规范：** 详见 [数据传输规范](#数据传输规范) 章节。

---

### data_launcher — GUI 统一面板

**功能：** 基于 tkinter 的图形化操作面板，整合数据审核与标准化流程，提供日志实时输出。

**界面布局：**

```
┌─────────────────────────────────────────────┐
│  自动驾驶数据流水线：审核清洗 → 标准化增强    │
├─────────────────────────────────────────────┤
│  目录设置                                   │
│  数据集目录:  [______________] [浏览...]     │
│  垃圾箱目录:  [______________] [浏览...]     │
│  Tub 输出目录:[______________] (自动)        │
├─────────────────────────────────────────────┤
│  数据增强                    [审核清洗]      │
│  ☑ 高斯模糊  概率 [10]%     [标准化处理]    │
│  ☑ 亮度/对比度 概率 [10]%                   │
│  ☐ 覆盖原图（不保留原始帧）                  │
├─────────────────────────────────────────────┤
│  日志                                       │
│  就绪。选择目录后点击「审核清洗」...          │
│  ─────────────────────────────────          │
└─────────────────────────────────────────────┘
```

**特性：**

- `print` 输出自动重定向到日志面板（线程安全）
- 输入目录变更时自动计算 tub 输出路径
- 标准化处理在后台线程执行，界面不阻塞
- 审核清洗时自动隐藏 tkinter 窗口，交由 OpenCV 接管；审核结束后恢复

---

## 数据传输规范

> **重要：** 以下规范定义了数据在采集端、清洗端、处理端和模型训练端之间传递的标准格式。所有协作者必须严格遵守，确保数据可被模型正确读取。

### 文件命名规范

**采集端输出的原始图片必须遵循以下命名格式：**

```
FV_<timestamp>_<COMMAND>.jpg
```

**字段说明：**

| 字段 | 格式 | 示例 | 说明 |
|------|------|------|------|
| `FV` | 固定前缀 | `FV` | 帧标识，不可修改 |
| `timestamp` | Unix 毫秒时间戳（13位数字） | `1782961058697` | 采集时刻，用于排序和去重 |
| `COMMAND` | 三选一：`FW` / `TR` / `TL` | `FW` | 当前帧对应的驾驶指令 |

**合法文件名示例：**

```
FV_1782961058697_FW.jpg    ✅ 直行帧
FV_1782961067045_TR.jpg    ✅ 右转帧
FV_1782961214316_TL.jpg    ✅ 左转帧
```

**非法文件名示例：**

```
IMG_001.jpg                ❌ 缺少 FV 前缀和时间戳
FV_1782961058697.jpg       ❌ 缺少指令字段
FV_abc_FW.jpg              ❌ 时间戳非数字
FV_1782961058697_XX.jpg    ❌ 未知指令（将被回退为 FW 默认值）
```

### 驾驶指令与控制量映射

文件名中的指令被映射为两个控制量，存入 `record_N.json`：

| 指令 | 含义 | `user/angle` | `user/throttle` | 视觉标签色 |
|------|------|-------------|----------------|-----------|
| `FW` | 直行 (Forward) | `0.0` | `1.0` | 绿色 |
| `TR` | 右转 (Turn Right) | `1.0` | `0.8` | 蓝色 |
| `TL` | 左转 (Turn Left) | `-1.0` | `0.8` | 黄色 |

**重要说明：**

- `angle` 值为**分类编码载体**，不是物理转角角度。它与模型配置文件 `config.py` 中的 `NEURAL_FUNCTION = "default_categorical"` 相对应。模型将 `-1.0 / 0.0 / 1.0` 作为三个离散类别进行学习。
- `throttle` 在直行时为满速 `1.0`，转弯时为 `0.8`（减速过弯）。
- 如果文件名中的指令不是 `FW`/`TR`/`TL` 之一，系统会打印警告并回退为 `FW` 默认值（`angle=0.0, throttle=1.0`）。

### Tub 目录结构规范

**标准 tub 目录结构：**

```
tub/
├── meta.json                 # 数据集元信息（有且仅有一个）
├── record_1.json             # 第 1 条数据记录
├── record_2.json             # 第 2 条数据记录
├── ...
├── record_N.json             # 第 N 条数据记录
├── FV_1782961058697_FW.jpg   # 原始帧图片
├── FV_1782961058697_FW_aug0.jpg  # 增强变体（如有）
├── FV_1782961058697_FW_aug1.jpg  # 增强变体（如有）
├── FV_1782961067045_TR.jpg
├── ...
```

**规范要点：**

| 规则 | 说明 |
|------|------|
| `meta.json` | 必须存在，位于 tub 目录根，描述数据集结构 |
| `record_N.json` | 从 1 开始连续编号，每个文件对应一张图片的一条记录 |
| 图片文件 | 与 record 文件同级存放，文件名与 record 中的 `cam/image_array` 值一致 |
| 增强变体 | 命名格式为 `{原文件名基名}_aug{N}.jpg`，`N` 从 0 起递增 |
| 记录总数 | `record_N.json` 的最大编号等于图片总数（含增强变体） |

### meta.json 元数据规范

**固定格式（不可自行修改字段顺序或名称）：**

```json
{
    "inputs": [
        "cam/image_array",
        "user/angle",
        "user/throttle",
        "user/mode"
    ],
    "types": [
        "image_array",
        "float",
        "float",
        "str"
    ]
}
```

**字段说明：**

| 路径 | 类型 | 含义 |
|------|------|------|
| `inputs[0]` = `"cam/image_array"` | `types[0]` = `"image_array"` | 图像数据，值为图片文件名 |
| `inputs[1]` = `"user/angle"` | `types[1]` = `"float"` | 转向控制量（分类编码） |
| `inputs[2]` = `"user/throttle"` | `types[2]` = `"float"` | 油门控制量 |
| `inputs[3]` = `"user/mode"` | `types[3]` = `"str"` | 驾驶模式，固定为 `"user"` |

> **兼容性警告：** `inputs` 数组的顺序与模型推理端强绑定。模型按索引 0→图像、1→angle、2→throttle、3→mode 读取数据，**严禁调整字段顺序或增删字段**。

### record_N.json 记录规范

每条 record 文件存储一个训练样本：

```json
{
    "cam/image_array": "FV_1782961058697_FW.jpg",
    "user/angle": 0.0,
    "user/throttle": 1.0,
    "user/mode": "user"
}
```

**字段说明：**

| 字段 | 类型 | 取值范围 | 说明 |
|------|------|---------|------|
| `cam/image_array` | `string` | 合法文件名 | 指向同目录下的图片文件（相对路径） |
| `user/angle` | `float` | `-1.0`, `0.0`, `1.0` | 转向分类编码，与 `FW/TR/TL` 一一对应 |
| `user/throttle` | `float` | `0.8`, `1.0` | 油门值，直行满速，转弯减速 |
| `user/mode` | `string` | `"user"` | 固定值，表示人工驾驶模式 |

**增强帧记录说明：** 增强变体的 record 中，`cam/image_array` 指向增强图片（如 `FV_xxx_aug0.jpg`），但 `user/angle`、`user/throttle`、`user/mode` 与原帧保持一致——增强只改变图像像素，不改变标签。

### 图像分辨率规范

| 参数 | 值 | 来源 |
|------|-----|------|
| 目标分辨率 | `180 × 320` (height × width) | `config.py` → `CAMERA_RESOLUTION` |
| 颜色通道 | 3 (BGR) | OpenCV 默认格式 |
| 文件格式 | `.jpg` (JPEG) | 采集端输出格式 |

> `data_processor` 在标准化过程中会使用 `cv2.resize(img, (320, 180))` 将所有图像统一缩放至此分辨率。**注意：** OpenCV 的 resize 参数顺序是 `(width, height)` 即 `(320, 180)`。

---

## 数据增强规范

数据增强的目的是在不改变驾驶标签的前提下，通过图像变换增加训练样本的多样性，提升模型对光照变化和图像噪声的鲁棒性。

### 增强类型

| 增强类型 | 操作 | 参数 | 默认触发概率 |
|----------|------|------|------------|
| **高斯模糊** (Gaussian Blur) | 随机选取核大小 `3×3` 或 `5×5` 进行高斯模糊 | `kernels: [3, 5]` | 10% (p=0.1) |
| **亮度/对比度** (Brightness/Contrast) | 对比度系数 `α ∈ [0.7, 1.3]`，亮度偏移 `β ∈ [-30, 30]` | `alpha: (0.7, 1.3)`, `beta: (-30, 30)` | 10% (p=0.1) |

### 触发规则

```
对每一帧独立判定：
  if random() < p_blur → 生成高斯模糊变体
  if random() < p_bc   → 生成亮度/对比度变体
```

- 两种增强的触发判定**相互独立**，一帧可能触发 0、1 或 2 种增强
- 同时触发两种增强时，**先执行高斯模糊，再执行亮度/对比度调整**（叠加顺序固定）

### 保留模式 vs 覆盖模式

| 模式 | 行为 | 数据量 | 适用场景 |
|------|------|--------|---------|
| **保留模式**（默认） | 原图始终保留，触发的增强生成额外变体文件 | 总记录 ≈ 原始帧 × (1 + p₁ + p₂) | 训练数据较少，需要扩充 |
| **覆盖模式**（`--replace`） | 增强图片替代原图，不保留原始帧 | 总记录 = 原始帧 | 数据充足，仅需增加多样性 |

**数据量预期：**

| 配置 | CLI 参数 | 预期记录/帧 |
|------|----------|------------|
| 全关 | `--no-augment` | 1.0 |
| 模糊 10% + 亮度 10% | 默认 | ~1.2 |
| 模糊 30% + 亮度 30% | `--blur-prob 0.3 --bc-prob 0.3` | ~1.6 |
| 模糊 50% + 亮度 50% | `--blur-prob 0.5 --bc-prob 0.5` | ~2.0 |
| 任意 + 覆盖 | `--replace` | 1.0 |

### 增强参数配置方式

**方式一：GUI 面板** — 通过复选框和百分比微调器直观配置。

**方式二：CLI 参数** — 通过命令行开关控制。

**方式三：代码级修改** — 修改 `data_processor.py` 中的 `DEFAULT_AUG_CONFIG` 字典，可调整 alpha/beta/kernels 等强度参数。

```python
DEFAULT_AUG_CONFIG = {
    'brightness_contrast': {
        'enabled': True,
        'probability': 0.1,         # 触发概率
        'alpha': (0.7, 1.3),        # 对比度系数范围
        'beta': (-30, 30),          # 亮度偏移范围
    },
    'gaussian_blur': {
        'enabled': True,
        'probability': 0.1,         # 触发概率
        'kernels': [3, 5],          # 可选的高斯核大小
    },
}
```

---

## 团队协作指南

### 目录组织约定

项目采用以下约定目录结构管理多人采集的训练数据：

```
autocar/
├── data_pipeline/                # 【本模块】数据处理工具
│   ├── data_launcher.py          #   GUI 启动器
│   ├── data_reviewer.py          #   审核清洗模块
│   ├── data_processor.py         #   标准化增强模块
│   └── README.md                 #   本文档
│
├── user/                         # 【数据区】所有用户采集数据
│   ├── clockwise-v1/             #   顺时针赛道 v1
│   │   ├── datas/                #     原始采集图片（清洗后）
│   │   └── tub/                  #     标准化训练集（处理后生成）
│   ├── anticlockwise-v1/         #   逆时针赛道 v1
│   │   ├── datas/
│   │   └── tub/
│   ├── clockwise_v2/             #   顺时针赛道 v2（下划线命名风格）
│   │   ├── datas/
│   │   └── tub/
│   ├── anticlockwise_v2/         #   逆时针赛道 v2
│   │   ├── datas/
│   │   └── tub/
│   └── trash/                    #   垃圾箱（审核标记的废弃图片）
│
├── ADcarV2_3/                    # 模型推理端（PyInstaller 打包）
├── ADcarV2_game2/                # 游戏模式推理端
└── tub文件夹示例/                 # tub 格式参考示例
```

**命名约定：**

| 元素 | 约定 | 示例 |
|------|------|------|
| 赛道方向 | `clockwise` / `anticlockwise` | `clockwise-v1` |
| 版本号 | `-v1`, `-v2` 或 `_v2`（建议统一为 `-vN`） | `clockwise-v1` |
| 原始数据 | 统一放在 `<赛道>/datas/` 下 | `clockwise-v1/datas/` |
| 训练数据 | 统一放在 `<赛道>/tub/` 下（由工具自动生成） | `clockwise-v1/tub/` |
| 垃圾图片 | 统一移至 `user/trash/` | `user/trash/` |

### 工作流建议

**新采集一批数据后的标准流程：**

```
1. 将采集图片放入 user/<赛道名>/datas/
   ↓
2. 运行 data_launcher.py，选择对应目录
   ↓
3. 点击「审核清洗」，逐帧标记垃圾图片
   ↓
4. 在面板中调整增强参数（建议新手保持默认 10%）
   ↓
5. 点击「标准化处理」，等待 tub/ 生成
   ↓
6. 检查 tub/ 目录：确认 meta.json、record 文件、图片数量一致
   ↓
7. 将 datas/ 和 tub/ 一并提交到 GitHub
```

**注意：** `datas/`（原始数据）和 `tub/`（生成数据）**都应纳入版本管理**：
- `datas/` 是原始采集数据，不可再生
- `tub/` 是可直接训练的数据集，队友拉取后立即可用

### Git 管理规范

**推荐的 `.gitignore` 配置（放置于项目根目录）：**

```gitignore
# Python
__pycache__/
*.pyc
*.pyo

# IDE
.vscode/
.idea/

# 系统文件
Thumbs.db
Desktop.ini

# 垃圾数据
user/trash/

# 打包产物（二进制文件过大，不建议入仓库）
ADcarV2_3/AdcarV2_3/
ADcarV2_game2/AdcarV2_game2/

# 压缩包
*.rar
*.zip
*.7z
```

**提交前检查清单：**

- [ ] `__pycache__/` 未被提交
- [ ] `user/trash/` 未被提交（或确认为空）
- [ ] 大文件（.exe, .dll, .rar）未被提交
- [ ] tub 目录中 `meta.json` 存在
- [ ] tub 目录中 `record_N.json` 数量与图片数量一致
- [ ] 无文件名异常的图片残留

---

## CLI 参数参考

### data_reviewer.py

```
python data_reviewer.py [INPUT_DIR] [-t TRASH_DIR]

位置参数:
  INPUT_DIR           原始图片所在目录（默认: E:/autonomous_driving/datas_ot1）

可选参数:
  -t, --trash TRASH   垃圾箱目录（默认: E:/autonomous_driving/trash）
```

### data_processor.py

```
python data_processor.py INPUT_DIR [选项]

位置参数:
  INPUT_DIR            原始图片所在目录（审核清洗后）

可选参数:
  -o, --output PATH    tub 输出目录（默认: INPUT_DIR 同级目录下的 tub/）
  --no-brightness      关闭亮度/对比度增强
  --no-blur            关闭高斯模糊增强
  --no-augment         关闭所有数据增强，仅做格式标准化
  --bc-prob FLOAT      亮度/对比度触发概率，范围 0.0~1.0（默认: 0.1）
  --blur-prob FLOAT    高斯模糊触发概率，范围 0.0~1.0（默认: 0.1）
  --replace            覆盖模式：增强替代原图，不保留原始帧
```

---

## 常见问题

### Q: 为什么 angle 使用 -1.0 / 0.0 / 1.0 而不是实际角度值？

A: 本项目使用分类模型而非回归模型。`angle` 的三个离散值对应三个驾驶类别（左转/直行/右转），模型配置文件 `config.py` 中 `NEURAL_FUNCTION = "default_categorical"` 将其作为分类问题处理。这降低了模型学习难度，适合赛道场景。

### Q: 如果我的文件名格式不符合规范怎么办？

A: `data_processor` 会跳过无法解析的文件并打印警告。请确保采集端输出的文件名严格遵守 `FV_<timestamp>_<COMMAND>.jpg` 格式。

### Q: 增强概率应该设多少？

A: 建议从默认值 10% 开始。数据量较少时可适当提高到 20%~30%，但不建议超过 50%（过多合成数据可能导致模型过拟合到增强噪声）。

### Q: 审核时误标记了垃圾图片怎么办？

A: 在审核窗口中按 `A` 回退到上一张，再按 `X` 取消标记。也可以在退出前多次按 `A` 回退检查。

### Q: tub 目录已经存在，再次运行 data_processor 会怎样？

A: 系统会提示是否覆盖。选择 `y` 会删除旧目录并重新生成，选择 `n` 会取消操作。

### Q: 为什么图片分辨率是 180×320？

A: 这是小车摄像头采集的原始分辨率，在 `config.py` 中由 `CAMERA_RESOLUTION = (180, 320)` 定义。保持此分辨率是为了与模型推理端输入尺寸一致。

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `config.py` | 模型配置（分辨率、批次大小、训练/测试分割、神经网络类型） |
| `tub文件夹示例/a/` | tub 格式参考示例（含 meta.json、record 文件和示例图片） |
| `AdcarV2_3/` | 模型推理端（PyInstaller 打包的独立可执行文件） |
| `AdcarV2_game2/` | 游戏模式推理端 |

---

> **维护者：** AutoCar 团队
> **最后更新：** 2026-07-03
> **Python 版本：** 3.12
