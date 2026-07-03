# ==============================================================================
# 环境声明: Python 3.12
# 核心依赖: pip install opencv-python
# 脚本身份: 自动驾驶数据快速人工审查与清洗工具 (Data Reviewer)
# 核心逻辑: 幻灯片式播放，一键标记垃圾数据，支持回退，最终批量软删除至垃圾箱
# ==============================================================================

import os
import cv2
import glob
import shutil
import argparse

# ==========================================
# 默认路径（可通过 CLI 参数覆盖）
# ==========================================
DEFAULT_DATA_DIR = 'E:/autonomous_driving/datas_ot1'
DEFAULT_TRASH_DIR = 'E:/autonomous_driving/trash'


def setup_trash(trash_dir):
    """确保垃圾箱目录存在"""
    if not os.path.exists(trash_dir):
        os.makedirs(trash_dir)


def draw_overlay(img, filename, current_idx, total, is_marked, goto_buffer=""):
    """在图片上绘制UI信息（已修复字体过大超框的问题）"""
    # 1. 提取标签
    try:
        command = filename.split('_')[-1].split('.')[0]
    except Exception:
        command = "UNKNOWN"

    # 标签色彩逻辑
    if command == 'FW':
        color = (0, 255, 0)       # 绿色 (护眼，代表安全直行)
    elif command == 'TR':
        color = (255, 255, 0)     # 天蓝色 (保留你喜欢的舒适冷色)
    elif command == 'TL':
        color = (0, 255, 255)     # 明黄色 (温暖且极具辨识度，代表左侧警示)
    else:
        color = (255, 255, 255)   # 未知指令使用默认纯白色

    # 获取图像的高(h)和宽(w)，用来动态计算文字应该放在哪里
    h, w = img.shape[:2]

    # 2. 垃圾标记警告界面
    if is_marked:
        overlay = img.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 255), -1)
        img = cv2.addWeighted(overlay, 0.3, img, 0.7, 0)
        # 修改：字号从 1.5 降到 0.8，粗细从 4 降到 2，位置动态居中偏上
        cv2.putText(img, "MARKED FOR TRASH", (w//2 - 120, h//2 - 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    else:
        # 正常状态：显示指令
        # 修改：字号从 2.0 降到 1.2，粗细从 4 降到 3，确保画面清爽
        cv2.putText(img, f"Cmd: {command}", (w//2 - 80, h//2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)

    # 3. 绘制左上角的进度条（含跳转输入）
    # 修改：字号降为 0.55，进度与跳转同行紧凑显示
    progress_text = f"[{current_idx + 1} / {total}]"
    if goto_buffer:
        progress_text += f"  Goto: {goto_buffer}_"
    cv2.putText(img, progress_text, (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

    # 4. 绘制底部的操作提示
    # 修改：精简了文案，缩短长度；字号降为 0.45，紧贴底部边缘，绝对不会超框
    controls = "Space/D:Next  A:Prev  X:Trash  Num+Enter:Jump  Q:Quit"
    cv2.putText(img, controls, (10, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (230, 230, 230), 1)

    return img


def run_reviewer(raw_data_dir, trash_dir, confirm_callback=None):
    """主流程：逐帧审查图片，标记垃圾并软删除

    Args:
        raw_data_dir:    原始图片所在目录
        trash_dir:       垃圾箱目录（标记删除的图片会移到这里）
        confirm_callback: 可选，确认回调函数，签名: (trash_count, trash_dir) -> bool
                          返回 True 表示确认移动。为 None 时使用终端 input()。
    """
    setup_trash(trash_dir)

    # 获取所有图片，并按文件名（包含时间戳）强制排序，确保画面播放是连贯的视频流
    image_paths = sorted(glob.glob(os.path.join(raw_data_dir, '*.jpg')))
    total_images = len(image_paths)

    if total_images == 0:
        print(f"[-] 在 {raw_data_dir} 中没有找到图片，请检查路径。")
        return

    print(f"[*] 成功加载 {total_images} 张图片。")
    print(f"[*] 垃圾箱: {trash_dir}")
    print("[*] 请在弹出的图像窗口中进行操作。")

    # 使用一个 Set 集合来存储被用户标记为垃圾的图片路径
    marked_for_deletion = set()

    idx = 0
    goto_buffer = ""  # 跳转数字输入缓冲区
    # 创建一个命名窗口，允许自由缩放大小
    cv2.namedWindow('Data Reviewer', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('Data Reviewer', 800, 600)  # 默认弹窗大小

    while idx < total_images:
        img_path = image_paths[idx]
        filename = os.path.basename(img_path)

        # 读取图片
        img = cv2.imread(img_path)
        if img is None:
            idx += 1
            continue

        # 检查当前图片是否已经被标记为垃圾
        is_marked = img_path in marked_for_deletion

        # 绘制 UI 界面
        display_img = draw_overlay(img, filename, idx, total_images, is_marked, goto_buffer)
        cv2.imshow('Data Reviewer', display_img)

        # 等待键盘输入 (0 表示无限等待，直到有按键按下)
        key = cv2.waitKey(0) & 0xFF

        # ---- 数字键入：累积到跳转缓冲区 ----
        if ord('0') <= key <= ord('9'):
            goto_buffer += chr(key)

        # ---- 回车：执行跳转 ----
        elif key == 13:  # Enter
            if goto_buffer:
                target = int(goto_buffer)
                idx = max(0, min(target - 1, total_images - 1))
            goto_buffer = ""

        # ---- 退格：删除最后一位 ----
        elif key == 8:  # Backspace
            goto_buffer = goto_buffer[:-1]

        # ---- 按下 D 或 空格键：认为图片没问题，播放下一张 ----
        elif key == ord(' ') or key == ord('d'):
            goto_buffer = ""
            idx += 1

        # ---- 按下 A 键：手滑了，返回上一张图片重新看 ----
        elif key == ord('a'):
            goto_buffer = ""
            idx = max(0, idx - 1)

        # ---- 按下 X 键：标记或取消标记垃圾 ----
        elif key == ord('x'):
            goto_buffer = ""
            if is_marked:
                # 如果已经标记了，再次按 X 则是"撤销标记"，并停留在当前页让你确认
                marked_for_deletion.remove(img_path)
            else:
                # 如果没标记，按 X 标记为垃圾，并【自动跳到下一张】，保证极速盲筛体验
                marked_for_deletion.add(img_path)
                idx += 1

        # ---- 按下 Q 或 ESC 键：退出审查并执行清理 ----
        elif key == ord('q') or key == 27:
            break

    cv2.destroyAllWindows()

    # ==========================================
    # 结算与执行清理
    # ==========================================
    trash_count = len(marked_for_deletion)
    print("\n" + "=" * 50)
    print(" 审查结束结算")
    print("=" * 50)
    if trash_count == 0:
        print("[*] 你没有标记任何垃圾图片，直接退出。")
        return

    print(f"[!] 你一共标记了 {trash_count} 张垃圾图片。")

    if confirm_callback is not None:
        confirmed = confirm_callback(trash_count, trash_dir)
    else:
        answer = input(f"是否将它们移动到 {trash_dir} 文件夹？(y/n): ")
        confirmed = answer.lower() == 'y'

    if confirmed:
        print("[*] 正在转移废弃数据...")
        for file_path in marked_for_deletion:
            try:
                filename = os.path.basename(file_path)
                dest_path = os.path.join(trash_dir, filename)
                shutil.move(file_path, dest_path)
            except Exception as e:
                print(f"[-] 转移失败 {file_path}: {e}")
        print("✅ 清理完成！你的 raw_images 文件夹现在非常干净了。")
    else:
        print("[*] 操作已取消，图片未被移动。")


# ==========================================
# CLI 入口
# ==========================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='自动驾驶数据快速人工审查与清洗工具 (Data Reviewer)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python data_reviewer.py
  python data_reviewer.py E:/autonomous_driving/datas_ot1
  python data_reviewer.py E:/autonomous_driving/datas_ot1 -t E:/autonomous_driving/trash
  python data_reviewer.py user/clockwise-v1/datas -t user/clockwise-v1/trash
        """
    )

    parser.add_argument(
        'input_dir', nargs='?', default=DEFAULT_DATA_DIR,
        help=f'原始图片所在目录 (默认: {DEFAULT_DATA_DIR})'
    )
    parser.add_argument(
        '--trash', '-t', default=DEFAULT_TRASH_DIR,
        help=f'垃圾箱目录 (默认: {DEFAULT_TRASH_DIR})'
    )

    args = parser.parse_args()
    run_reviewer(args.input_dir, args.trash)
