#!/usr/bin/env python
# ==============================================================================
# 环境声明: Python 3.12
# 核心依赖: tkinter（Python 内置）
# 脚本身份: AutoCar 数据处理面板 - 统一 GUI 启动器
# 核心逻辑: 选择目录 → 一键审核清洗 → 一键标准化增强 → 完成
# ==============================================================================

import os
import sys
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import glob as _glob

from data_reviewer import run_reviewer
from data_processor import create_tub


class LogRedirector:
    """将 print 输出安全地重定向到 tkinter Text 组件（线程安全）"""

    def __init__(self, root, write_callback):
        self.root = root
        self.write_callback = write_callback
        self._buffer = ""

    def write(self, s):
        self._buffer += s
        if '\n' in self._buffer:
            lines = self._buffer.split('\n')
            for line in lines[:-1]:
                if line.strip():
                    self.root.after(0, self.write_callback, line)
            self._buffer = lines[-1]

    def flush(self):
        if self._buffer.strip():
            self.root.after(0, self.write_callback, self._buffer)
            self._buffer = ""


class DataLauncher:
    """GUI 启动器：整合数据审核与标准化流程"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AutoCar 数据处理面板")
        self.root.geometry("700x550")
        self.root.minsize(580, 400)
        self.root.resizable(True, True)

        # ---- 顶部说明 ----
        header = ttk.Label(
            self.root,
            text="自动驾驶数据流水线：审核清洗 → 标准化增强 → tub 训练集",
            font=("", 10, "bold"),
        )
        header.pack(pady=(12, 4))

        # ---- 目录选择区 ----
        dir_frame = ttk.LabelFrame(self.root, text="目录设置", padding=10)
        dir_frame.pack(fill=tk.X, padx=12, pady=(4, 8))

        # 数据集目录
        row0 = ttk.Frame(dir_frame)
        row0.pack(fill=tk.X, pady=2)
        ttk.Label(row0, text="数据集目录:", width=14).pack(side=tk.LEFT)
        self.input_var = tk.StringVar(value=self._default_input())
        ttk.Entry(row0, textvariable=self.input_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(row0, text="浏览...", width=7, command=self.browse_input).pack(side=tk.RIGHT)

        # 垃圾箱目录
        row1 = ttk.Frame(dir_frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="垃圾箱目录:", width=14).pack(side=tk.LEFT)
        self.trash_var = tk.StringVar(value=self._default_trash())
        ttk.Entry(row1, textvariable=self.trash_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(row1, text="浏览...", width=7, command=self.browse_trash).pack(side=tk.RIGHT)

        # Tub 输出目录（强制命名，只读显示）
        row2 = ttk.Frame(dir_frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Tub 输出目录:", width=14).pack(side=tk.LEFT)
        self.output_var = tk.StringVar(value=self._compute_tub_path(self.input_var.get()))
        self.output_entry = ttk.Entry(row2, textvariable=self.output_var, state='readonly')
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Label(row2, text="(自动)", foreground="gray").pack(side=tk.RIGHT)

        # 数据集目录变更时自动更新 tub 输出路径
        self.input_var.trace_add('write', lambda *_: self._auto_update_output())

        # ---- 增强选项 + 操作按钮 ----
        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill=tk.X, padx=12, pady=4)

        # 增强选项
        aug_frame = ttk.LabelFrame(action_frame, text="数据增强", padding=6)
        aug_frame.pack(side=tk.LEFT)

        # 高斯模糊
        blur_row = ttk.Frame(aug_frame)
        blur_row.pack(anchor=tk.W, pady=1)
        self.blur_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(blur_row, text="高斯模糊", variable=self.blur_var, width=14).pack(side=tk.LEFT)
        ttk.Label(blur_row, text=" 概率").pack(side=tk.LEFT)
        self.blur_prob_var = tk.IntVar(value=10)
        ttk.Spinbox(blur_row, from_=1, to=100, width=3,
                    textvariable=self.blur_prob_var).pack(side=tk.LEFT)
        ttk.Label(blur_row, text="%").pack(side=tk.LEFT)

        # 亮度/对比度
        bc_row = ttk.Frame(aug_frame)
        bc_row.pack(anchor=tk.W, pady=1)
        self.bc_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bc_row, text="亮度/对比度", variable=self.bc_var, width=14).pack(side=tk.LEFT)
        ttk.Label(bc_row, text=" 概率").pack(side=tk.LEFT)
        self.bc_prob_var = tk.IntVar(value=10)
        ttk.Spinbox(bc_row, from_=1, to=100, width=3,
                    textvariable=self.bc_prob_var).pack(side=tk.LEFT)
        ttk.Label(bc_row, text="%").pack(side=tk.LEFT)

        # 覆盖原图
        self.replace_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(aug_frame, text="覆盖原图（不保留原始帧）",
                        variable=self.replace_var).pack(anchor=tk.W, pady=2)

        # 数据均衡
        bal_frame = ttk.LabelFrame(action_frame, text="数据均衡", padding=6)
        bal_frame.pack(side=tk.LEFT, padx=8)

        # 启用开关
        self.balance_enabled_var = tk.BooleanVar(value=False)
        self.balance_mode_var = tk.StringVar(value='downsample')

        bal_top = ttk.Frame(bal_frame)
        bal_top.pack(anchor=tk.W, pady=1)
        ttk.Checkbutton(bal_top, text="启用类别均衡",
                        variable=self.balance_enabled_var,
                        command=self._toggle_balance).pack(side=tk.LEFT)

        # 各类张数显示
        self.bal_count_var = tk.StringVar(value="(未扫描)")
        count_row = ttk.Frame(bal_frame)
        count_row.pack(anchor=tk.W, pady=1)
        ttk.Label(count_row, text="当前:", foreground="gray").pack(side=tk.LEFT)
        ttk.Label(count_row, textvariable=self.bal_count_var,
                  foreground="gray").pack(side=tk.LEFT)

        # 建议比例按钮
        suggest_row = ttk.Frame(bal_frame)
        suggest_row.pack(anchor=tk.W, pady=1)
        self._bal_suggest_btn = ttk.Button(
            suggest_row, text="建议比例", width=9,
            command=self._suggest_ratio, state=tk.DISABLED)
        self._bal_suggest_btn.pack(side=tk.LEFT)
        self._bal_suggest_label = ttk.Label(
            suggest_row, text="", foreground="gray")
        self._bal_suggest_label.pack(side=tk.LEFT, padx=4)

        # 比例设置
        self.balance_fw_var = tk.IntVar(value=2)
        self.balance_tl_var = tk.IntVar(value=2)
        self.balance_tr_var = tk.IntVar(value=1)

        ratio_row = ttk.Frame(bal_frame)
        ratio_row.pack(anchor=tk.W, pady=1)
        self._bal_ratio_widgets = []  # 用于状态切换
        for label, var in [("FW", self.balance_fw_var),
                           ("TL", self.balance_tl_var),
                           ("TR", self.balance_tr_var)]:
            ttk.Label(ratio_row, text=f" {label}").pack(side=tk.LEFT)
            sb = ttk.Spinbox(ratio_row, from_=1, to=10, width=3,
                             textvariable=var, state=tk.DISABLED)
            sb.pack(side=tk.LEFT)
            self._bal_ratio_widgets.append(sb)

        # 模式选择
        mode_row = ttk.Frame(bal_frame)
        mode_row.pack(anchor=tk.W, pady=1)
        self._bal_radio_ds = ttk.Radiobutton(
            mode_row, text="降采样", value="downsample",
            variable=self.balance_mode_var, state=tk.DISABLED)
        self._bal_radio_ds.pack(side=tk.LEFT)
        self._bal_radio_us = ttk.Radiobutton(
            mode_row, text="升采样", value="upsample",
            variable=self.balance_mode_var, state=tk.DISABLED)
        self._bal_radio_us.pack(side=tk.LEFT)
        self._bal_mode_widgets = [self._bal_radio_ds, self._bal_radio_us]

        # 操作按钮
        btn_frame = ttk.Frame(action_frame)
        btn_frame.pack(side=tk.RIGHT)

        self.btn_review = ttk.Button(btn_frame, text="审核清洗", width=12,
                                     command=self.on_review)
        self.btn_review.pack(side=tk.LEFT, padx=3)

        self.btn_process = ttk.Button(btn_frame, text="标准化处理", width=12,
                                      command=self.on_process)
        self.btn_process.pack(side=tk.LEFT, padx=3)

        # ---- 日志区 ----
        log_frame = ttk.LabelFrame(self.root, text="日志", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 10))

        self.log_text = tk.Text(log_frame, height=10, wrap=tk.WORD,
                                font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
                                insertbackground="white")
        self.log_text.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(self.log_text, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)

        self.log("就绪。选择目录后点击「审核清洗」或「标准化处理」。")

    # ---- 默认路径 ----
    @staticmethod
    def _resolve(rel_path):
        """将相对于项目根目录的路径转为绝对路径"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        root = os.path.normpath(os.path.join(script_dir, '..'))
        return os.path.normpath(os.path.join(root, rel_path))

    @classmethod
    def _default_input(cls):
        candidates = [
            "E:/autonomous_driving/datas_ot1",
            cls._resolve("user/clockwise-v1/datas"),
            cls._resolve("user/anticlockwise-v1/datas"),
        ]
        for p in candidates:
            if os.path.isdir(p):
                return os.path.normpath(p)
        return ""

    @classmethod
    def _default_trash(cls):
        return cls._resolve("user/trash")

    @staticmethod
    def _compute_tub_path(input_dir):
        """根据数据集目录计算强制 tub 输出路径

        clockwise-v1/datas → clockwise-v1/tub
        anticlockwise-v1/datas → anticlockwise-v1/tub
        """
        if not input_dir or not os.path.isdir(input_dir):
            return ""
        project_dir = os.path.dirname(os.path.normpath(input_dir))
        return os.path.join(project_dir, "tub")

    # ---- 日志 ----
    def log(self, msg):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    # ---- 浏览按钮 ----
    def browse_input(self):
        path = filedialog.askdirectory(title="选择数据集目录")
        if path:
            self.input_var.set(os.path.normpath(path))

    def browse_trash(self):
        path = filedialog.askdirectory(title="选择垃圾箱目录")
        if path:
            self.trash_var.set(os.path.normpath(path))

    def _auto_update_output(self):
        """输入目录变更时自动计算并更新 tub 输出路径和各类计数"""
        self.output_var.set(self._compute_tub_path(self.input_var.get()))
        self._refresh_counts()
        # 清除之前的建议说明
        self._bal_suggest_label.config(text="")

    def _toggle_balance(self):
        """启用/禁用均衡控件的可编辑状态"""
        enabled = self.balance_enabled_var.get()
        state = tk.NORMAL if enabled else tk.DISABLED
        for w in self._bal_ratio_widgets:
            w.config(state=state)
        for w in self._bal_mode_widgets:
            w.config(state=state)
        self._bal_suggest_btn.config(state=state)
        if enabled:
            self._refresh_counts()

    def _count_classes(self, input_dir):
        """统计目录中各类别图片数量

        Returns:
            dict {"FW": n, "TL": n, "TR": n} 或 None（目录无效）
        """
        if not input_dir or not os.path.isdir(input_dir):
            return None
        counts = {"FW": 0, "TL": 0, "TR": 0}
        for f in _glob.glob(os.path.join(input_dir, '*.jpg')):
            name = os.path.basename(f)
            parts = name.split('_')
            if len(parts) >= 3:
                cmd = parts[-1].split('.')[0]
                if cmd in counts:
                    counts[cmd] += 1
        return counts

    def _refresh_counts(self):
        """更新均衡面板中的各类张数显示"""
        input_dir = self.input_var.get().strip()
        counts = self._count_classes(input_dir)
        if counts:
            self.bal_count_var.set(
                f"FW={counts['FW']}, TL={counts['TL']}, TR={counts['TR']}")
        else:
            self.bal_count_var.set("(目录无效)")

    def _suggest_ratio(self):
        """根据实际数据分布，自动建议均衡比例

        算法: 以最少类别为基准(ratio=1)，其他类别按比例计算，上限3
              确保最少类别的数据被完全保留
        """
        input_dir = self.input_var.get().strip()
        counts = self._count_classes(input_dir)
        if not counts:
            messagebox.showwarning("警告", "无法扫描目录，请先选择有效的数据集目录。")
            return

        total = sum(counts.values())
        if total == 0:
            return

        # 找出最少的类别
        min_cmd = min(counts, key=counts.get)
        min_count = counts[min_cmd]

        if min_count == 0:
            messagebox.showwarning("警告", f"类别 {min_cmd} 数量为0，无法计算比例。")
            return

        # 计算建议比例，上限 3
        MAX_RATIO = 3
        ratios = {}
        for cmd in ("FW", "TL", "TR"):
            if counts[cmd] == 0:
                ratios[cmd] = 1
            else:
                raw = counts[cmd] / min_count
                ratios[cmd] = max(1, min(int(raw + 0.5), MAX_RATIO))

        # 填入 GUI
        self.balance_fw_var.set(ratios["FW"])
        self.balance_tl_var.set(ratios["TL"])
        self.balance_tr_var.set(ratios["TR"])

        # 显示建议说明
        self._bal_suggest_label.config(
            text=f"(最少: {min_cmd}={min_count}, "
                 f"上限={MAX_RATIO}×)" if ratios[max(ratios, key=ratios.get)] == MAX_RATIO
                 else f"(基准: {min_cmd}={min_count})")

    # ---- 审核清洗 ----
    def on_review(self):
        input_dir = self.input_var.get().strip()
        trash_dir = self.trash_var.get().strip()

        if not input_dir or not os.path.isdir(input_dir):
            messagebox.showerror("错误", f"数据集目录不存在:\n{input_dir or '(空)'}")
            return

        jpg_count = len(_glob.glob(os.path.join(input_dir, '*.jpg')))
        if jpg_count == 0:
            messagebox.showwarning("警告", f"该目录中没有找到 .jpg 图片:\n{input_dir}")
            return

        self.log(f"[审核] 启动 → {input_dir}")
        self.log(f"[审核] 共 {jpg_count} 张图片，垃圾箱: {trash_dir}")

        # GUI 确认回调（替换终端 input）
        def gui_confirm(count, trash):
            self.root.deiconify()  # 先恢复 tkinter 窗口以显示对话框
            result = messagebox.askyesno(
                "确认移动",
                f"你一共标记了 {count} 张垃圾图片。\n\n"
                f"是否将它们移动到垃圾箱？\n{trash}"
            )
            self.root.withdraw()  # 再次隐藏以便可能继续审核
            return result

        # 隐藏 tkinter 窗口，让 OpenCV 审核窗口接管
        self.root.withdraw()
        try:
            run_reviewer(input_dir, trash_dir, confirm_callback=gui_confirm)
        finally:
            self.root.deiconify()
            self.log("[审核] 完成。")

    # ---- 标准化处理 ----
    def on_process(self):
        input_dir = self.input_var.get().strip()
        output_dir = self.output_var.get().strip()

        if not input_dir or not os.path.isdir(input_dir):
            messagebox.showerror("错误", f"数据集目录不存在:\n{input_dir or '(空)'}")
            return

        if not output_dir:
            messagebox.showerror("错误", "无法确定 Tub 输出目录。")
            return

        # 输出目录覆盖确认
        if os.path.exists(output_dir):
            ok = messagebox.askyesno(
                "确认覆盖",
                f"输出目录已存在:\n{output_dir}\n\n是否删除并重新生成？"
            )
            if not ok:
                self.log("[*] 操作已取消。")
                return
            shutil.rmtree(output_dir)

        aug_config = {
            'brightness_contrast': {
                'enabled': self.bc_var.get(),
                'probability': self.bc_prob_var.get() / 100.0,
            },
            'gaussian_blur': {
                'enabled': self.blur_var.get(),
                'probability': self.blur_prob_var.get() / 100.0,
            },
        }
        replace_original = self.replace_var.get()

        # 构建均衡参数
        balance_ratio = None
        balance_mode = 'downsample'
        if self.balance_enabled_var.get():
            balance_ratio = {
                'FW': self.balance_fw_var.get(),
                'TL': self.balance_tl_var.get(),
                'TR': self.balance_tr_var.get(),
            }
            balance_mode = self.balance_mode_var.get()

        bc_cfg = aug_config['brightness_contrast']
        blur_cfg = aug_config['gaussian_blur']
        log_parts = [
            f"增强: 高斯模糊={'ON' if blur_cfg['enabled'] else 'OFF'}"
            f"({blur_cfg['probability']:.0%})",
            f"亮度对比度={'ON' if bc_cfg['enabled'] else 'OFF'}"
            f"({bc_cfg['probability']:.0%})",
            f"覆盖={'ON' if replace_original else 'OFF'}",
        ]
        if balance_ratio:
            log_parts.append(
                f"均衡: {balance_mode} FW:{balance_ratio['FW']}"
                f":TL:{balance_ratio['TL']}:TR:{balance_ratio['TR']}"
            )
        self.log(f"[处理] 启动 → " + ", ".join(log_parts))

        # 禁用按钮
        self.btn_review.config(state=tk.DISABLED)
        self.btn_process.config(state=tk.DISABLED)

        def worker():
            old_stdout = sys.stdout
            sys.stdout = LogRedirector(self.root, self.log)
            try:
                create_tub(input_dir, output_dir, aug_config,
                           replace_original=replace_original,
                           balance_ratio=balance_ratio,
                           balance_mode=balance_mode)
            except Exception as e:
                self.root.after(0, self.log, f"[-] 错误: {e}")
            finally:
                sys.stdout = old_stdout
                self.root.after(0, self._processing_done)

        threading.Thread(target=worker, daemon=True).start()

    def _processing_done(self):
        self.btn_review.config(state=tk.NORMAL)
        self.btn_process.config(state=tk.NORMAL)
        self.log("—" * 40)


# ==========================================
# 入口
# ==========================================

if __name__ == '__main__':
    app = DataLauncher()
    app.root.mainloop()
