# Phone Video Capture

更新时间：2026-05-11

用途：让 OpenClaw / Agent 协作层可以指挥 APKClaw 在手机端录屏，并把 MP4 拉回电脑，方便后续 AI 做演示素材、复盘、剪辑和标注。

## 核心边界

- OpenClaw / 专门 Agent 负责判断“为什么录、录多久、录完做什么”。
- APKClaw 只负责执行：申请录屏授权、录制、停止、列出文件、下载文件。
- 录屏必须有明确用户意图，不能默认偷偷录。
- Android 每次开始录屏都可能弹出系统授权框，需要用户在手机上确认。

## APKClaw API

```text
POST /api/lumi/media/record/start
POST /api/lumi/media/record/stop
GET  /api/lumi/media/record/status
GET  /api/lumi/media/videos
GET  /api/lumi/media/video?id=<filename>
```

所有接口继续使用：

```text
X-AGENT-PHONE-TOKEN: <token>
X-APKCLAW-TOKEN: <token>
X-LUMI-LAUNCHER-ID: <launcher-id>
X-LUMI-TIMESTAMP: <unix-ms>
X-LUMI-NONCE: <nonce>
X-LUMI-BODY-SHA256: <sha256>
X-LUMI-SIGNATURE: <hmac-sha256>
```

## 启动器 CLI

查看状态：

```powershell
npm run phone:video -- status --phone-url http://192.168.1.137:9527 --phone-token <token>
```

开始录屏：

```powershell
npm run phone:video -- start --max-seconds 60 --filename demo.mp4 --phone-url http://192.168.1.137:9527 --phone-token <token>
```

停止录屏：

```powershell
npm run phone:video -- stop --phone-url http://192.168.1.137:9527 --phone-token <token>
```

下载最新录屏到电脑：

```powershell
npm run phone:video -- download --latest --out-dir .\data\phone-videos --phone-url http://192.168.1.137:9527 --phone-token <token>
```

## 默认素材路径

```text
data/phone-videos/
```

## 推荐 Agent 用法

1. 先说明录屏目的，例如“收集一次任务失败过程用于复盘”。
2. 调用 `phone:video start`。
3. 等用户确认手机系统录屏授权。
4. 执行手机任务。
5. 调用 `phone:video stop`。
6. 调用 `phone:video download --latest`。
7. 报告本地 MP4 路径、文件大小、任务结论。
