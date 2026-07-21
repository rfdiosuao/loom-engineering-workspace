# 模块边界与协作规则

这份文档给后续二开、多人协作、Agent 编排使用。原则是：一次改动只认一个主模块，跨模块改动必须写清楚原因和验证方式。

## 模块边界

| 模块 | 路径 | 主要职责 | 风险等级 |
| --- | --- | --- | --- |
| 前端 UI | `openclaw_new_launcher/src/**` | 页面、交互、配置表单、状态展示 | 中 |
| Tauri 外壳 | `openclaw_new_launcher/src-tauri/**` | 桌面窗口、启动 Bridge、打包资源 | 高 |
| Python Bridge | `openclaw_new_launcher/python/bridge.py` | 本地 HTTP API 入口、路由转发 | 高 |
| OpenClaw 进程管理 | `openclaw_new_launcher/python/services/process.py` | Node/OpenClaw 启停、端口冲突处理、日志 | 极高 |
| AI 生图 | `openclaw_new_launcher/python/services/image_api.py` | 图片生成、图片编辑 API | 中 |
| AI 视频 | `openclaw_new_launcher/python/services/video_api.py` | 视频生成、任务轮询 | 中 |
| 授权客户端 | `openclaw_new_launcher/python/core/license_manager.py` | 授权激活、本地授权状态 | 高 |
| 授权服务器 | `license_server/**` | 授权码生成、激活、Web 管理页 | 极高 |
| 文档 | `openclaw_new_launcher/docs/**` | 架构、交付、二开说明 | 低 |
| 脚本 | `scripts/**` | CI、自检、打包辅助 | 中 |
| 交付包 | `release/**` | 生成产物，不进 Git | 高 |

## 协作规则

- 不要同时让多个 Agent 修改同一个高风险文件。
- `process.py`、`license_manager.py`、`license_server/**` 修改后必须做手动启动验证。
- 前端 UI 修改后必须执行 `npm run build`。
- Rust/Tauri 修改后必须执行 `cargo check`。
- 打包后必须执行 `scripts/verify-release.ps1`。
- 所有密钥、授权库、客户机器生成的授权状态只允许留在本地或服务器，不允许进 Git。

## 推荐 Agent 分工

| Agent | 负责范围 | 禁止范围 |
| --- | --- | --- |
| UI Agent | `src/**`、样式、页面文案 | 不改 Python/Rust 授权逻辑 |
| Bridge Agent | `python/bridge.py`、`python/services/**` | 不改授权服务器数据库 |
| License Agent | `license_server/**`、授权协议文档 | 不碰 UI 大改 |
| Packaging Agent | `scripts/**`、打包清单、离线包校验 | 不改业务逻辑 |
| Reviewer Agent | 只读审查、列风险、给验证命令 | 不直接重构核心文件 |

## 改动验收模板

每个 Agent 完成后必须回复：

```text
改动文件：
- ...

验证：
- ...

风险：
- ...
```

如果没有验证，必须明确写“未验证”以及原因。
