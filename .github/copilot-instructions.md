# smol_rugv — Copilot 工作规范

## 项目背景

本项目将 SmolVLA 模型部署到基于 Jetson Orin Nano 的 UGV 小车上，使用 ROS2 Humble 框架。
小车具备单 USB 摄像头、麦克风和四轮底盘（ESP32 串口驱动），目标是通过摄像头图像与语音指令实现端到端自动控制。
这是一个**以学习为主的项目**。

## 每次对话开始时

1. 主动读取 `to-do.md`，了解当前 Sprint 任务状态和未完成项
2. 主动读取 `current_progress.md`，了解最近已完成的工作
3. 如果任务涉及具体模块，读取 `design_doc/` 下对应的设计文档作为架构基线

## 回答与任务处理规范

- **学习优先**：每一步操作需说明目的和原因，不只给结果
- **先分析后动手**：正式变更前先输出任务分析和方案，确认可行后再执行
- **架构基线**：以 `design_doc/` 为唯一架构基线，先框架后细节，不擅自偏离
- **接口一致性**：每次改动前确认接口契约与数据流与设计文档一致
- **复用优先**：优先复用现有代码，不引入无关代码
- **降级验证**：架构设计需反复验证可用性与降级策略

## 变更后必做

每次完成功能实现或代码变更后：
1. 对照 `to-do.md` 检查哪些任务已完成
2. 将完成状态同步更新到 `current_progress.md`
3. 提示用户是否需要提交（使用 git-commit skill）

## 项目结构速查

```
src/          # ROS2 功能包（camera / speech / chassis / vla / smol_bringup）
tools/        # 独立工具（ugv_ctrl_tester / ugv_data_collector）
design_doc/   # 架构设计文档（唯一基线）
ref_code/     # LeRobot SmolVLA 源码引用（只读，不修改）
to-do.md          # 主任务列表（Sprint 结构）
current_progress.md  # 已完成事项流水账
```

## 技术栈

- ROS2 Humble · Python 3.10 · Jetson Orin Nano · JetPack
- SmolVLA / LeRobot（`ref_code/` 引用，不复制）
- 底盘串口协议：ESP32，115200 baud，`/dev/ttyTHS1`
