# CLAUDE.md

## Git 推送规则

**必须完成并完整验证一个新功能后，才能执行 `git push`。**

具体而言，满足以下所有条件才算"完成并完整验证"：

1. 代码已编写完毕，无已知 bug
2. 新功能已通过实际运行验证（非仅静态检查）
3. 相关文档（README.md）已同步更新，反映最新功能和行为
4. 如有新增的 CLI 参数、配置项或数据格式变更，已在文档中说明

禁止在以下情况下 push：
- 功能只写了一半、存在 TODO 或 placeholder
- 未经过端到端测试验证
- 已知有 bug 尚未修复

## 项目概述

这是 AutoCar 自动驾驶小车的数据处理流水线（`data_pipeline`），包含三个模块：

| 文件 | 功能 |
|------|------|
| `data_reviewer.py` | 人工审核清洗 — OpenCV 幻灯片式逐帧审查，标记垃圾图片 |
| `data_processor.py` | 数据标准化与增强 — 散装图片 → tub 格式 + 可选数据增强 |
| `data_launcher.py` | GUI 统一启动面板 — 一键串联审核与处理流程 |

## 开发约定

- Python 3.12，依赖 `opencv-python`，tkinter 内置
- 数据传输规范详见 README.md，修改时需同步更新文档
- `data_reviewer` 和 `data_processor` 均可独立 CLI 运行，也可被 `data_launcher` GUI 调用
- 代码注释和文档使用中文
- 提交信息使用中文描述 + 英文 type 前缀（如 `feat:`, `fix:`, `docs:`）
