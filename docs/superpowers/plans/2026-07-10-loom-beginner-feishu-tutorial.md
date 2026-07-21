# 麓鸣 2.1.56 保姆级飞书教程实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建一份带真实 UI 红框截图、逐按钮说明和故障处理的飞书云文档新手教程。

**Architecture:** 子智能体输出教程正文与漏步审查，主智能体从 2.1.56 本地界面抓取带 DOM 红框覆盖层的真实截图。教程先在本地保存源稿与图片资产，再通过 lark-cli docs v2 分段创建和回读验证飞书文档。

**Tech Stack:** React/Vite 本地界面、浏览器截图、lark-cli docs v2、飞书 Docx、PNG。

## Global Constraints

- 不展示授权码、token、密码、设备令牌、真实客户数据或生产表格标识。
- 不虚构按钮和状态；按钮原文以 2.1.56 当前 UI 为准。
- 不执行真实发布、评论、私信、加好友、加微或批量触达。
- 所有真实外发继续要求草稿、人工确认、白名单、频控和日志留痕。

---

### Task 1: 建立教程资料清单

**Files:**
- Create: `docs/tutorials/LOOM_2.1.56_BEGINNER_GUIDE.md`

- [ ] 核对导航、页面标题、按钮原文和成功状态。
- [ ] 合并子智能体正文初稿和漏步清单。
- [ ] 写出完整教程骨架、步骤、成功判断与故障处理。

### Task 2: 抓取并标注真实 UI 截图

**Files:**
- Create: `docs/assets/tutorial/2.1.56/*.png`

- [ ] 启动本地 2.1.56 前端并进入安全视觉状态。
- [ ] 依次打开授权、安装、AI 接入、手机、矩阵、获客、飞书、日志与诊断页面。
- [ ] 在目标控件外叠加红色线框和编号后截图。
- [ ] 检查每张图无隐私、无重叠、按钮文字清晰。

### Task 3: 创建飞书文档骨架

- [ ] 使用 `lark-cli docs +create --api-version v2` 创建标题、导读和章节骨架。
- [ ] 保存返回的文档 ID 和 URL，不记录任何 token 或授权信息。
- [ ] 使用 `docs +fetch --api-version v2 --detail with-ids` 获取章节 block ID。

### Task 4: 分段写入正文和截图

- [ ] 按章节 block ID 逐段写入步骤、成功判断和故障处理。
- [ ] 使用 `docs +media-insert` 插入每张本地 PNG。
- [ ] 在图片前后写清红框编号所代表的动作。
- [ ] 增加安全边界和每日检查清单。

### Task 5: 交叉审查与交付

- [ ] 回读完整飞书文档并检查章节、图片与顺序。
- [ ] 让子智能体按完全新手视角检查漏步、歧义和虚构按钮。
- [ ] 修正文案后再次回读。
- [ ] 向用户提供飞书文档链接、本地源稿与截图目录。
