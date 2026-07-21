# Luminode Desktop Agent 集成方案

## 定位

Luminode 不合并进启动器本体，而是作为可选 sidecar：

- 启动器负责发现、配置、启动、停止、健康检查和日志；
- Luminode 负责桌面截图、点击、输入和微信相关 RPA；
- OpenClaw 通过启动器 Bridge 调用 `/api/desktop-agent/*`，不直接读取 token。

## 配置

私有配置文件：

```text
data/.openclaw/launcher/desktop-agent.json
```

主要字段：

- `agentDir`: Luminode 目录，留空时自动查找相邻 `agents/luminode-desktop`
- `port`: 默认 `21900`
- `token`: 启动器自动生成，不展示明文
- `appType`: `weixin` 或 `wework`
- `autoStartHttpApi`: 启动 Luminode 时自动拉起本地 HTTP API

## Bridge API

- `GET/POST /api/desktop-agent/status`
- `POST /api/desktop-agent/config`
- `POST /api/desktop-agent/start`
- `POST /api/desktop-agent/stop`
- `GET/POST /api/desktop-agent/health`
- `POST /api/desktop-agent/screenshot`
- `POST /api/desktop-agent/click`
- `POST /api/desktop-agent/type`
- `POST /api/desktop-agent/wechat/send`
- `POST /api/desktop-agent/wechat/unread`

## 安全

- Luminode 只监听 `127.0.0.1`
- 本地 HTTP API 支持 `X-Desktop-Agent-Token` 和 `Authorization: Bearer`
- OpenClaw 不应该拿 token，必须走启动器 Bridge
- 自动回复和真实联系人消息发送必须有用户明确意图

## 后续债

- 补齐 WebSocket OpenClaw Node 协议
- 给 Luminode 打独立便携包并放入 `OpenClawFiles/agents/luminode-desktop`
- 桌面 Agent 加环境诊断：端口占用、Electron 缺失、robotjs 原生模块损坏、微信窗口不可见
- 给 OpenClaw 增加桌面执行 CLI helper

