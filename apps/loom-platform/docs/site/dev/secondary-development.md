# 二次开发指南

二次开发建议先判断变更所属层级，再选择对应的实现位置和测试命令。

<div class="copy-line">建议按层级小步变更，每次改动后完成对应验证，再进入下一层。</div>

## 改 UI

适合：

- 页面布局。
- 按钮文案。
- 表单字段展示。
- 折叠配置。
- Toast 提示。

主要目录：

```text
openclaw_ui_integration/src/redesign/
├─ components/
├─ pages/
├─ services/
├─ stores/
└─ styles/
```

验证：

```powershell
cd D:\Axiangmu\AUSTART\openclaw_ui_integration
npm run build
npm run dev
```

UI 改动需要同时检查桌面宽度和窄屏宽度，不能只以 1200px 宽度作为验收依据。

## 加 Bridge API

适合：

- 新增启动器本地能力。
- 聚合多个服务状态。
- 代理桌面或手机组件。
- 读写本地配置文件。

建议步骤：

1. 在 `services/` 写业务逻辑。
2. 在 `api/routes_*.py` 暴露路由。
3. 在前端 `services/` 写调用封装。
4. 页面只消费封装后的结果。
5. 给失败返回明确错误码和 detail。

React 页面应通过服务封装访问复杂业务路径。

## 加手机能力

先确认能力属于哪一类：

| 类型 | 示例 | 校验 |
| --- | --- | --- |
| 只读 | 状态、截图、节点树、录屏列表 | Token + 签名 |
| 有界动作 | 点击、输入、打开应用 | mode、确认、任务日志 |
| 外发动作 | 发布、发送消息 | 用户确认、平台回执 |

CLI 优先：

```powershell
npm run phone:agent -- run --prompt "读取当前屏幕" --mode observe --json
npm run phone:vision -- status --json
```

## 加桌面能力

桌面 RPA 必须先写 policy。

推荐新增能力顺序：

1. status。
2. health。
3. screenshot。
4. read-only data。
5. confirmed action。
6. auto action。

写操作要能回答：

- 哪个配置项允许它？
- 哪个参数表示用户确认？
- 失败时如何告诉用户被谁拦截？
- 日志里是否留下动作、时间和目标？

## 加 Skill

Skill 应该调用启动器已有 CLI，而不是复制一套实现。

推荐结构：

```text
name: openclaw-something
description: 触发词和能力边界

# 使用前
先运行 npm run openclaw:context -- --json

# 命令
固定给出 npm run ... --json

# 安全
写操作需要确认
```

## 改打包

打包脚本改动要额外谨慎，因为它影响交付包。

改动前先列清楚：

| 问题 | 要确认 |
| --- | --- |
| 新文件是否要进包 | runtime、assets、templates、scripts |
| 是否需要清理状态 | token、license、设备、缓存 |
| 是否影响 Mac | Windows 二进制、路径分隔符、shell |
| 是否影响 GitHub Actions | workflow 参数、缓存、artifact 名称 |

## 二开注意事项

<div class="check-grid">
  <div class="check-card"><strong>路径由配置推导</strong><span>使用 AppPaths 或配置推导路径。</span></div>
  <div class="check-card"><strong>业务规则下沉服务层</strong><span>页面只负责展示和调用服务封装。</span></div>
  <div class="check-card"><strong>能力调用经过 Bridge</strong><span>手机和桌面能力都要走已有鉴权和策略。</span></div>
  <div class="check-card"><strong>预览状态明确标注</strong><span>mock 截图和预览模式必须标注清楚。</span></div>
</div>

## 提交前检查

```powershell
git status --short
cd D:\Axiangmu\AUSTART\openclaw_ui_integration
npm run build
cd D:\Axiangmu\AUSTART
powershell -ExecutionPolicy Bypass -File scripts\ci-check.ps1
```

如果只是文档站改动，还要跑：

```powershell
cd D:\Axiangmu\AUSTART\docs\site
npm run docs:build
```
