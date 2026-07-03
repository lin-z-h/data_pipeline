#!/usr/bin/env python
# ==============================================================================
# 环境声明: Python 3.12
# 核心依赖: pip install opencv-python
# 脚本身份: 自动驾驶数据标准化与增强工具 (Data Processor)
# 核心逻辑: 读取清洗后的散装图片 → 解析文件名 → 生成 tub 格式 → 可选数据增强
# 位置: data_reviewer.py 的下游环节，在推理模型训练之前运行
# ==============================================================================

import os
import cv2
import glob
import json
import shutil
import random
import argparse
import itertools

# ==========================================
# 基础配置
# ==========================================

# 命令到控制量的映射
# 我们的环节只传递 3 个离散状态 (FW/TR/TL)
# angle 值为分类编码载体（不是物理转角），与 NEURAL_FUNCTION = "default_categorical" 对应
COMMAND_MAP = {
    'FW': {'angle': 0.0,  'throttle': 1.0},   # 直行
    'TR': {'angle': 1.0,  'throttle': 0.8},   # 右转
    'TL': {'angle': -1.0, 'throttle': 0.8},   # 左转
}

# 目标分辨率，与 config.py CAMERA_RESOLUTION 保持一致
TARGET_RESOLUTION = (180, 320)  # (height, width)，cv2.resize 用 (320, 180)

# tub 元数据模板，与推理模型输入格式保持一致
META_TEMPLATE = {
    "inputs": ["cam/image_array", "user/angle", "user/throttle", "user/mode"],
    "types": ["image_array", "float", "float", "str"]
}

# 默认增强配置 — 每个增强类型包含开关、触发概率和强度参数
# 每帧独立判定：以 probability 的概率触发对应增强，两种增强可同时生效
DEFAULT_AUG_CONFIG = {
    'brightness_contrast': {
        'enabled': True,
        'probability': 0.1,         # p2: 每帧触发亮度/对比度增强的概率 (10%)
        'alpha': (0.7, 1.3),        # 对比度系数范围
        'beta': (-30, 30),          # 亮度偏移范围
    },
    'gaussian_blur': {
        'enabled': True,
        'probability': 0.1,         # p1: 每帧触发高斯模糊的概率 (10%)
        'kernels': [3, 5],          # 可选的高斯核大小
    },
}


# 默认均衡配置
DEFAULT_BALANCE_MODE = "downsample"  # downsample | upsample


# ==========================================
# 比例解析
# ==========================================

def _parse_ratio(ratio_str):
    """解析比例字符串为 dict

    格式: "FW:N,TL:N,TR:N" → {"FW": N, "TL": N, "TR": N}
    容错: 支持空格、大小写不敏感、部分缺省（缺省值=1）

    Args:
        ratio_str: 如 "FW:2,TL:2,TR:1" 或 "fw:3,tr:1"

    Returns:
        dict 或 None（解析失败）
    """
    if not ratio_str or not isinstance(ratio_str, str):
        return None

    ratio = {}
    try:
        parts = [p.strip() for p in ratio_str.split(',')]
        for part in parts:
            if ':' not in part:
                continue
            cmd, val = part.split(':', 1)
            cmd = cmd.strip().upper()
            val = int(val.strip())
            if cmd in ('FW', 'TL', 'TR') and val > 0:
                ratio[cmd] = val
    except (ValueError, AttributeError):
        return None

    # 至少需要一个有效类别
    if not ratio:
        return None

    # 缺省填充：未指定的类别默认比例=1
    for cmd in ('FW', 'TL', 'TR'):
        if cmd not in ratio:
            ratio[cmd] = 1

    return ratio


# ==========================================
# 类别均衡
# ==========================================

def _balance_classes(image_paths, ratio, mode="downsample"):
    """按指定比例均衡各类别帧数

    Args:
        image_paths: 已排序的图片路径列表
        ratio:       dict，如 {"FW": 2, "TL": 2, "TR": 1}
        mode:        "downsample" | "upsample"

    Returns:
        (selected_paths, class_multipliers)
          - selected_paths:   均衡后的图片路径列表（已排序）
          - class_multipliers: upsample 模式下各类增强倍率 dict，downsample 返回 None
    """
    # ---- 按指令分类 ----
    buckets = {'FW': [], 'TL': [], 'TR': []}
    for p in image_paths:
        _, command = parse_filename(os.path.basename(p))
        if command in buckets:
            buckets[command].append(p)

    counts = {c: len(buckets[c]) for c in buckets}
    total = sum(counts.values())
    if total == 0:
        return image_paths, None

    print(f"[均衡] 原始分布: FW={counts['FW']}, TL={counts['TL']}, TR={counts['TR']}")

    # ---- 计算目标数量 ----
    if mode == "downsample":
        # 以最紧缺类别为基准，按比例收缩
        ratios_list = [counts[c] / ratio.get(c, 1) for c in buckets if ratio.get(c, 1) > 0]
        if not ratios_list:
            return image_paths, None
        base = min(ratios_list)
    elif mode == "upsample":
        # 以最充裕类别为基准，按比例扩张
        ratios_list = [counts[c] / ratio.get(c, 1) for c in buckets if ratio.get(c, 1) > 0]
        if not ratios_list:
            return image_paths, None
        base = max(ratios_list)
    else:
        print(f"[!] 未知均衡模式 '{mode}'，使用 downsample")
        return _balance_classes(image_paths, ratio, "downsample")

    targets = {}
    for c in buckets:
        targets[c] = max(1, int(base * ratio.get(c, 1)))

    print(f"[均衡] 目标分布 (base={base:.1f}): FW={targets['FW']}, "
          f"TL={targets['TL']}, TR={targets['TR']}")

    # ---- 按模式执行 ----
    if mode == "downsample":
        selected = []
        for c in buckets:
            n = min(targets[c], counts[c])
            if n < counts[c]:
                selected.extend(random.sample(buckets[c], n))
            else:
                selected.extend(buckets[c])

        selected.sort()
        print(f"[均衡] downsample 完成: {len(selected)} 帧 "
              f"(丢弃 {total - len(selected)} 帧)")
        return selected, None

    elif mode == "upsample":
        # 全部保留，计算各类需要的增强倍率
        multipliers = {}
        for c in buckets:
            if counts[c] > 0 and targets[c] > counts[c]:
                # 需要每个原始帧平均生成多少额外变体
                # 倍率 = 需要新增的数量 / 原数量
                multipliers[c] = (targets[c] - counts[c]) / counts[c]
            else:
                multipliers[c] = 0.0

        image_paths.sort()
        print(f"[均衡] upsample 模式: 全部 {total} 帧保留，增强倍率 "
              f"FW={multipliers['FW']:.2f}, "
              f"TL={multipliers['TL']:.2f}, "
              f"TR={multipliers['TR']:.2f}")
        return image_paths, multipliers


# ==========================================
# 文件名解析
# ==========================================

def parse_filename(filename):
    """从文件名中提取时间戳和驾驶指令

    期望格式: FV_<timestamp>_<COMMAND>.jpg
    示例: FV_1779764393153_FW.jpg → ('1779764393153', 'FW')
    返回: (timestamp, command) 或 (None, None) 如果格式不匹配
    """
    base = os.path.splitext(filename)[0]
    parts = base.split('_')

    if len(parts) < 3:
        return None, None

    timestamp = parts[1]
    command = parts[-1]

    return timestamp, command


def command_to_values(command):
    """将驾驶指令映射为 (angle, throttle)"""
    if command in COMMAND_MAP:
        m = COMMAND_MAP[command]
        return m['angle'], m['throttle']
    else:
        print(f"  [!] 未知指令 '{command}'，回退为 FW 默认值")
        return COMMAND_MAP['FW']['angle'], COMMAND_MAP['FW']['throttle']


# ==========================================
# 数据增强函数
# ==========================================

def apply_brightness_contrast(img, alpha_range=(0.7, 1.3), beta_range=(-30, 30)):
    """随机调整亮度和对比度

    Args:
        img:         输入图像
        alpha_range: 对比度系数范围 (min, max)
        beta_range:  亮度偏移范围 (min, max)
    """
    alpha = random.uniform(*alpha_range)
    beta = random.randint(*beta_range)
    return cv2.convertScaleAbs(img, alpha=alpha, beta=beta)


def apply_gaussian_blur(img, kernels=None):
    """随机高斯模糊

    Args:
        img:     输入图像
        kernels: 可选核大小列表，默认 [3, 5]
    """
    if kernels is None:
        kernels = [3, 5]
    k = random.choice(kernels)
    return cv2.GaussianBlur(img, (k, k), 0)


# ==========================================
# 增强配置规范化
# ==========================================

def _normalize_aug_config(augmentations):
    """将用户传入的增强配置规范化为内部格式

    兼容旧格式: {'brightness_contrast': True, 'gaussian_blur': False}
    新格式:    {'brightness_contrast': {'enabled': True, 'count': 1, ...}, ...}
    """
    if augmentations is None:
        return {k: dict(v) for k, v in DEFAULT_AUG_CONFIG.items()}

    normalized = {}
    for key, default in DEFAULT_AUG_CONFIG.items():
        user_val = augmentations.get(key, default)

        if isinstance(user_val, bool):
            # 旧格式：True/False → 用默认参数
            cfg = dict(default)
            cfg['enabled'] = user_val
        elif isinstance(user_val, dict):
            # 新格式：合并用户参数到默认值
            cfg = dict(default)
            cfg.update(user_val)
        else:
            cfg = dict(default)

        normalized[key] = cfg

    return normalized


# ==========================================
# Tub 生成主流程
# ==========================================

def create_tub(input_dir, output_dir=None, augmentations=None,
               replace_original=False,
               balance_ratio=None, balance_mode=None):
    """将原始图片文件夹标准化为 tub 格式数据集，可选数据增强和类别均衡

    Args:
        input_dir:        原始图片所在目录（经过 data_reviewer 清洗后）
        output_dir:       tub 输出目录，默认在数据集同级目录下创建 "tub/"
        augmentations:    增强配置，支持多种格式:
                          旧格式: {'brightness_contrast': bool, 'gaussian_blur': bool}
                          新格式: {'brightness_contrast': {'enabled': bool, 'probability': float, ...}, ...}
                          None 则使用 DEFAULT_AUG_CONFIG
        replace_original: True=增强图片替代原图（不保留原始帧），
                          False=原图始终保留，增强为额外记录
        balance_ratio:    None 不启用均衡；或 dict 如 {"FW": 2, "TL": 2, "TR": 1}
        balance_mode:     "downsample"（默认）或 "upsample"

    Returns:
        str: tub 输出目录路径，失败时返回 None
    """

    # ---- 参数校验 ----
    input_dir = os.path.normpath(input_dir)

    if not os.path.isdir(input_dir):
        print(f"[-] 错误: 目录不存在 → '{input_dir}'")
        return None

    if output_dir is None:
        # 默认: 数据集目录的父目录下创建 "tub"
        project_dir = os.path.dirname(input_dir)
        output_dir = os.path.join(project_dir, "tub")

    output_dir = os.path.normpath(output_dir)

    aug_cfg = _normalize_aug_config(augmentations)

    # ---- 扫描图片 ----
    image_paths = sorted(glob.glob(os.path.join(input_dir, '*.jpg')))
    total_files = len(image_paths)

    if total_files == 0:
        print(f"[-] 在 '{input_dir}' 中没有找到 .jpg 图片。")
        return None

    print(f"[*] 扫描到 {total_files} 张图片")

    # ---- 创建输出目录 ----
    if os.path.exists(output_dir):
        print(f"[!] 输出目录已存在: '{output_dir}'")
        confirm = input("    是否覆盖？(y/n): ")
        if confirm.lower() != 'y':
            print("[*] 操作已取消。")
            return None
        shutil.rmtree(output_dir)

    os.makedirs(output_dir)
    print(f"[*] 输出目录: '{output_dir}'")

    # ---- 显示增强配置 ----
    bc_cfg = aug_cfg['brightness_contrast']
    blur_cfg = aug_cfg['gaussian_blur']
    print(f"[*] 增强: 亮度对比度={'ON' if bc_cfg['enabled'] else 'OFF'}"
          f" (p={bc_cfg['probability']:.0%}, α{bc_cfg['alpha']}, β{bc_cfg['beta']}), "
          f"高斯模糊={'ON' if blur_cfg['enabled'] else 'OFF'}"
          f" (p={blur_cfg['probability']:.0%}, 核{blur_cfg['kernels']})")
    if replace_original:
        print(f"[*] 模式: 覆盖原图（增强替代原始帧）")
    else:
        print(f"[*] 模式: 保留原图（增强为额外记录）")

    # ---- 类别均衡 ----
    class_multipliers = None
    if balance_ratio is not None:
        _mode = balance_mode or DEFAULT_BALANCE_MODE
        print(f"[均衡] 目标比例 FW:{balance_ratio.get('FW',1)}:"
              f"TL:{balance_ratio.get('TL',1)}:TR:{balance_ratio.get('TR',1)}, "
              f"模式={_mode}")
        balanced_paths, class_multipliers = _balance_classes(
            image_paths, balance_ratio, _mode
        )
        if balanced_paths is not None:
            image_paths = balanced_paths
            total_files = len(image_paths)

    # ---- 逐帧处理 ----
    records = []
    record_count = 0
    skipped = 0

    for idx, img_path in enumerate(image_paths):
        filename = os.path.basename(img_path)
        timestamp, command = parse_filename(filename)

        if timestamp is None:
            print(f"  [~] 跳过 (文件名格式异常): {filename}")
            skipped += 1
            continue

        angle, throttle = command_to_values(command)

        # 读取图像以验证有效性，同时留着做增强
        img = cv2.imread(img_path)
        if img is None:
            print(f"  [~] 跳过 (无法读取图像): {filename}")
            skipped += 1
            continue

        # 统一缩放到目标分辨率 (180×320)，与 config.py CAMERA_RESOLUTION 一致
        img = cv2.resize(img, (320, 180))

        # ---- 原始帧 + 概率增强 ----
        base_no_ext = os.path.splitext(filename)[0]
        aug_counter = 0
        has_bc = False
        has_blur = False

        # 计算有效增强概率（upsample 模式下不足类别放大）
        _bc_prob = bc_cfg['probability']
        _blur_prob = blur_cfg['probability']
        if class_multipliers and command in class_multipliers:
            mult = class_multipliers[command]
            if mult > 0:
                _bc_prob = min(bc_cfg['probability'] * (1 + mult), 1.0)
                _blur_prob = min(blur_cfg['probability'] * (1 + mult), 1.0)

        # 独立判定两种增强是否触发
        if bc_cfg['enabled'] and random.random() < _bc_prob:
            has_bc = True
        if blur_cfg['enabled'] and random.random() < _blur_prob:
            has_blur = True

        if replace_original:
            # 覆盖模式：增强图片替代原图，使用原文件名
            if has_blur and has_bc:
                # 两种增强叠加：先模糊再亮度
                aug_img = apply_gaussian_blur(img, kernels=blur_cfg['kernels'])
                aug_img = apply_brightness_contrast(
                    aug_img,
                    alpha_range=bc_cfg['alpha'],
                    beta_range=bc_cfg['beta']
                )
                cv2.imwrite(os.path.join(output_dir, filename), aug_img)
            elif has_blur:
                aug_img = apply_gaussian_blur(img, kernels=blur_cfg['kernels'])
                cv2.imwrite(os.path.join(output_dir, filename), aug_img)
            elif has_bc:
                aug_img = apply_brightness_contrast(
                    img,
                    alpha_range=bc_cfg['alpha'],
                    beta_range=bc_cfg['beta']
                )
                cv2.imwrite(os.path.join(output_dir, filename), aug_img)
            else:
                # 都未触发，保留原图
                cv2.imwrite(os.path.join(output_dir, filename), img)
            record_count += 1
            records.append({
                "cam/image_array": filename,
                "user/angle": angle,
                "user/throttle": throttle,
                "user/mode": "user"
            })
        else:
            # 非覆盖模式：原图始终保留，增强为额外记录
            cv2.imwrite(os.path.join(output_dir, filename), img)
            record_count += 1
            records.append({
                "cam/image_array": filename,
                "user/angle": angle,
                "user/throttle": throttle,
                "user/mode": "user"
            })

            if has_blur:
                aug_img = apply_gaussian_blur(img, kernels=blur_cfg['kernels'])
                aug_filename = f"{base_no_ext}_aug{aug_counter}.jpg"
                cv2.imwrite(os.path.join(output_dir, aug_filename), aug_img)
                record_count += 1
                records.append({
                    "cam/image_array": aug_filename,
                    "user/angle": angle,
                    "user/throttle": throttle,
                    "user/mode": "user"
                })
                aug_counter += 1

            if has_bc:
                aug_img = apply_brightness_contrast(
                    img,
                    alpha_range=bc_cfg['alpha'],
                    beta_range=bc_cfg['beta']
                )
                aug_filename = f"{base_no_ext}_aug{aug_counter}.jpg"
                cv2.imwrite(os.path.join(output_dir, aug_filename), aug_img)
                record_count += 1
                records.append({
                    "cam/image_array": aug_filename,
                    "user/angle": angle,
                    "user/throttle": throttle,
                    "user/mode": "user"
                })
                aug_counter += 1

        # 进度提示
        if (idx + 1) % 50 == 0 or idx == total_files - 1:
            print(f"  处理进度: {idx + 1}/{total_files}")

    # ---- 写入 record 文件 ----
    original_frames = total_files - skipped
    aug_frames = len(records) - original_frames
    if replace_original:
        print(f"[*] 记录总数: {len(records)} (覆盖模式)")
    else:
        print(f"[*] 记录总数: {len(records)} (原始 {original_frames} + 增强 {aug_frames})")
    print(f"[*] 写入 record 文件...")

    for i, record in enumerate(records, start=1):
        record_path = os.path.join(output_dir, f"record_{i}.json")
        with open(record_path, 'w', encoding='utf-8') as f:
            json.dump(record, f, ensure_ascii=False)

    # ---- 写入 meta.json ----
    print(f"[*] 写入 meta.json...")
    meta_path = os.path.join(output_dir, 'meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(META_TEMPLATE, f, indent=2, ensure_ascii=False)

    # ---- 结算 ----
    print("\n" + "=" * 50)
    print(" Tub 生成完毕")
    print("=" * 50)
    print(f"  输入:   {input_dir}")
    print(f"  输出:   {output_dir}")
    print(f"  原始帧: {original_frames}")
    if not replace_original:
        print(f"  增强帧: {aug_frames}")
    print(f"  总记录: {len(records)}")
    if skipped > 0:
        print(f"  跳过:   {skipped} (文件名异常或图像损坏)")

    return output_dir


# ==========================================
# CLI 入口
# ==========================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='自动驾驶数据标准化与增强工具 (Data Processor)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python data_processor.py E:/autonomous_driving/datas_ot1
  python data_processor.py user/clockwise-v1/datas --bc-prob 0.3
  python data_processor.py user/clockwise-v1/datas --no-augment
  python data_processor.py user/clockwise-v1/datas --bc-prob 0.2 --blur-prob 0.15 --replace
  python data_processor.py user/clockwise-v1/datas --ratio "FW:2,TL:2,TR:1"
  python data_processor.py user/clockwise-v1/datas --ratio "FW:2,TL:2,TR:1" --balance-mode upsample
        """
    )

    parser.add_argument('input_dir', help='原始图片所在目录（清洗后）')
    parser.add_argument('--output', '-o', default=None,
                        help='tub 输出目录 (默认: 在数据集同级创建 tub/)')

    # 增强开关
    parser.add_argument('--no-brightness', action='store_true',
                        help='关闭亮度/对比度增强')
    parser.add_argument('--no-blur', action='store_true',
                        help='关闭高斯模糊增强')
    parser.add_argument('--no-augment', action='store_true',
                        help='关闭所有数据增强，仅做格式标准化')

    # 增强参数
    parser.add_argument('--bc-prob', type=float, default=None,
                        help='亮度/对比度触发概率 0~1 (默认: 0.1)')
    parser.add_argument('--blur-prob', type=float, default=None,
                        help='高斯模糊触发概率 0~1 (默认: 0.1)')
    parser.add_argument('--replace', action='store_true',
                        help='覆盖模式：增强替代原图，不保留原始帧')

    # 类别均衡
    parser.add_argument('--ratio', type=str, default=None,
                        help='类别均衡比例，格式 "FW:N,TL:N,TR:N"（如 "FW:2,TL:2,TR:1"）')
    parser.add_argument('--balance-mode', type=str, default=None,
                        choices=['downsample', 'upsample'],
                        help='均衡模式: downsample(降采样)或upsample(升采样)，默认 downsample')

    args = parser.parse_args()

    # 构建增强配置
    if args.no_augment:
        aug_config = {
            'brightness_contrast': {'enabled': False},
            'gaussian_blur': {'enabled': False},
        }
    else:
        aug_config = {}
        if args.no_brightness:
            aug_config['brightness_contrast'] = {'enabled': False}
        elif args.bc_prob is not None:
            aug_config['brightness_contrast'] = {'probability': args.bc_prob}

        if args.no_blur:
            aug_config['gaussian_blur'] = {'enabled': False}
        elif args.blur_prob is not None:
            aug_config['gaussian_blur'] = {'probability': args.blur_prob}

    # 解析均衡比例
    balance_ratio = None
    if args.ratio is not None:
        balance_ratio = _parse_ratio(args.ratio)
        if balance_ratio is None:
            print("[-] 无法解析 --ratio 参数，已禁用均衡功能")

    create_tub(args.input_dir, args.output,
               aug_config if aug_config else None,
               replace_original=args.replace,
               balance_ratio=balance_ratio,
               balance_mode=args.balance_mode or DEFAULT_BALANCE_MODE)
