---
name: update-progress
description: "Use when: user completes a task, finishes a sprint item, or asks to update progress, record what was done, mark todo as done, sync progress files. Triggers on: '更新进度', '记录进度', '标记完成', '完成了', 'update progress', 'mark done', '更新 to-do', '进度同步'."
---

# 进度更新工作流

## 目标
同步更新项目的两个进度文件，保持一致：
- `current_progress.md` — 流水账式已完成事项列表
- `to-do.md` — Sprint 结构化任务清单（`[ ]` / `[x]`）

---

## 文件格式规范

### current_progress.md

每行一条，格式固定为：
```
- 已完成 Sprint X：<简短描述>
```
或描述跨 Sprint 的独立事项：
```
- 已<动作>：<描述>
```

新条目追加到**文件末尾**，不修改已有行。

### to-do.md

按 Sprint 分组，每个任务用 GitHub Flavored Markdown checkbox：
```markdown
# Sprint N：<Sprint 名称>
- [x] 已完成的任务
- [ ] 未完成的任务
```

将完成的任务从 `- [ ]` 改为 `- [x]`，**不删除任何行**。

---

## 步骤

### Step 1 — 理解用户描述的变更
从用户输入中提取：
- 完成了哪些任务（一条或多条）
- 属于哪个 Sprint
- 是否有备注（如 TBD、移至后续 Sprint 等）

### Step 2 — 读取当前文件状态
```
读取 current_progress.md — 了解最后一条记录，避免重复
读取 to-do.md — 找到对应 Sprint 和任务行
```

### Step 3 — 更新 to-do.md
- 找到对应 Sprint 下的任务行
- 将 `- [ ]` 改为 `- [x]`
- 若任务不存在，在对应 Sprint 末尾**新增**一行 `- [x] <描述>`
- 若 Sprint 不存在，在文件末尾新增 Sprint 块

### Step 4 — 更新 current_progress.md
在文件末尾追加一行或多行，格式：
```
- 已完成 Sprint X：<与 to-do.md 中任务描述一致的简短说明>
```

### Step 5 — 确认并展示 diff
展示两个文件的变更内容，让用户确认后再决定是否提交。

---

## 注意事项

- **不删除**任何已有条目（包括已完成的 `[x]` 行）
- `current_progress.md` 只追加，不修改历史行
- Sprint 编号和名称以 `to-do.md` 中的命名为准
- 若用户描述的内容跨多个 Sprint，逐一更新每个 Sprint 对应的任务
- 更新完成后，可提示用户是否需要接着提交（调用 git-commit skill）
