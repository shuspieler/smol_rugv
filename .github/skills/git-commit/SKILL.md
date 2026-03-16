---
name: git-commit
description: "Use when: user asks to commit, push, submit changes, or sync to remote. Handles summarizing changes, writing Conventional Commits messages, managing .gitignore for artifacts, and pushing to origin. Triggers on: '提交', '上传', 'commit', 'push', '按规范提交', 'git 提交', 'sync changes'."
---

# Git 规范提交工作流

## 目标
自动完成从"查看变更 → 起草提交信息 → 暂存 → 提交 → 推送"的完整流程，确保提交信息符合 Conventional Commits 规范。

---

## 步骤

### Step 1 — 查看当前变更
```bash
git status
git diff --stat
```
- 区分 **已跟踪文件的修改**（modified）和 **新文件**（untracked）
- 识别哪些是源码/文档，哪些是构建产物/测试输出（后者应排除）

### Step 2 — 检查并更新 .gitignore
若发现以下类型的文件出现在 untracked 列表中，应先加入 `.gitignore`，**不提交**：
- 测试运行输出目录（`output/`, `logs/`, `*.log`）
- 编译产物（`__pycache__/`, `*.pyc`, `build/`, `dist/`）
- 模型权重（`*.pt`, `*.pth`, `*.onnx`, `*.pkl`）
- 机密信息（`.env`, 硬编码 token）

### Step 3 — 暂存文件
只暂存有意义的源文件，**不要用 `git add .`** 除非确认所有文件都应提交：
```bash
git add <具体文件或目录>
git status   # 再次确认 staging 区正确
```

### Step 4 — 起草提交信息（Conventional Commits）

格式：
```
<type>(<scope>): <简短描述（中英文均可，≤72字符）>

- 变更点 1
- 变更点 2
```

**type 选择规则：**

| type | 使用场景 |
|------|---------|
| `feat` | 新增功能或模块 |
| `fix` | 修复 Bug |
| `docs` | 仅文档变更（README、注释、设计文档） |
| `refactor` | 重构（不改变功能） |
| `test` | 添加或修改测试 |
| `chore` | 构建配置、依赖、工具脚本等杂项 |
| `style` | 代码格式（不影响逻辑） |
| `perf` | 性能优化 |

**scope 规则（本项目）：**

| scope | 覆盖范围 |
|-------|---------|
| `tools` | `tools/` 下任意工具 |
| `chassis` | `src/chassis/` |
| `camera` | `src/camera/` |
| `speech` | `src/speech/` |
| `vla` | `src/vla/` |
| `bringup` | `src/smol_bringup/` |
| `docs` | `design_doc/`, `README.md` |
| `ci` | `.github/`, 构建脚本 |

**示例：**
```
feat(vla): implement shared_buffer with thread-safe snapshot API
fix(chassis): correct odom frame_id to base_link
docs: add project README with architecture and quickstart
chore(tools): add .gitignore rules for test output directories
```

### Step 5 — 提交
```bash
git commit -m "<提交信息>"
```

### Step 6 — 推送
```bash
git push origin main
```
确认输出包含 `main -> main` 表示推送成功。

---

## 注意事项

- **不提交**：`output/`、`__pycache__/`、`*.pyc`、硬编码密钥
- **提交信息语言**：scope/type 用英文，描述中英文均可
- 若有多个逻辑独立的变更，优先拆分为多次提交，而非打包成一个大 commit
- 推送前确认远端分支（`git remote -v`）
