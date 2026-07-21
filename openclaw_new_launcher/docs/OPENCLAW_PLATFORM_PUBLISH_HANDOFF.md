# OpenClaw 平台发布交接文档

更新时间：2026-05-25

## 目标

把“手机生成能力”补成“手机平台发布能力”：

1. 生成页的结果可以直接流转到发布页。
2. 发布页支持直连模式和反向通道模式。
3. 直连模式能把图片/视频先传到手机，再由 APKClaw 在目标平台里完成发布。
4. 反向通道模式把发布任务封成标准 packet，并可投递到 relay，由 APKClaw 轮询取走执行。

## 已落地的入口

- `src/services/publish.ts`
  - 发布平台模型
  - 发布草稿模型
  - 发布 prompt 生成
  - 反向通道 packet 生成
- `src/stores/publishStore.ts`
  - 生成页到发布页的草稿 handoff
- `src/components/publish/PublishPage.tsx`
  - 发布工作台
  - 直连 / 反向通道双栈
  - 手机相册上传
  - 发布任务摘要与历史
- `scripts/openclaw-publish-phone.mjs`
  - CLI 版发布入口
  - `direct`：上传素材并提交 APKClaw 任务
  - `reverse`：输出标准发布 packet，也可 POST 到 relay packet endpoint
- `scripts/openclaw-publish-relay.mjs`
  - Node 版 relay / queue 服务
  - 支持 packet ingest、long poll、complete、status、health
  - 支持 `--auth-token` / `OPENCLAW_PUBLISH_RELAY_TOKEN` 共享 token 鉴权
  - 默认状态目录：`data/.openclaw/publish-relay`
- `scripts/openclaw-publish-relay-smoke.mjs`
  - 启动带 token 的本地 relay
  - 验证未授权请求被 401 拒绝，授权请求能完成 `packet -> poll -> complete -> status(done)`
- `scripts/openclaw-publish-relay-check.mjs`
  - 对已经部署好的公网 relay 做 loopback 验收
  - 验证 health、鉴权、packet ingest、poll、complete、status
- `scripts/openclaw-context.mjs`
  - 运行时上下文新增 `platformPublish`
  - 可被 OpenClaw 读取到发布 CLI 和默认配置
- APKClaw `PublishRelayManager`
  - 手机端按 relay base URL + channel ID 长轮询 packet
  - 收到 packet 后复用 `/api/lumi/publish/packet` 本地执行，再向 relay 回传 complete
- APKClaw 发布中转设置页
  - 设置 relay base URL、channel ID、relay token、enable/disable
  - 保存时会先做 relay health/status 自检

## 链路说明

### 1. 直连模式

流程：

1. 用户在图片页或视频页生成内容。
2. 结果进入发布草稿。
3. 发布页读取草稿。
4. 若勾选“发送到手机相册”，先把素材传到手机。
5. 生成发布 prompt，调用 APKClaw 执行任务。
6. APKClaw 在手机端完成打开 App、选择入口、填写内容、检查预览、提交发布。

直连模式当前依赖：

- 手机端 `/api/lumi/*`
- `phoneApi.executeTask(...)`
- APKClaw 已配置 token / baseUrl

### 2. 反向通道模式

流程：

1. 发布页或 CLI 生成 `openclaw.publish.packet.v1`。
2. packet 记录平台、标题、正文、标签、媒体、relayUrl、channelId。
3. 发布页或 CLI 将 packet POST 到 relay 的 `/api/lumi/publish/packet`，公网 relay 启用鉴权时带 `Authorization: Bearer <token>` 或 `X-OpenClaw-Relay-Token`。
4. APKClaw 轮询 `/api/lumi/relay/poll?channelId=...`，同样带 relay token，拿到 packet 后本机执行。
5. APKClaw 执行完向 `/api/lumi/relay/complete` 回传结果。

说明：

- 现在已经有 packet 协议、CLI 输出、relay 服务和 APKClaw 轮询 worker。
- 当前还没完成的是公网 HTTPS 部署和手机开代理网络下的真机 E2E 验证。
- relay base URL 和 relay token 填给 APKClaw 设置页；packet endpoint URL 和同一个 token 填给发布页或 CLI。

## 生成页到发布页的 handoff

- 图片页生成成功后会出现“去平台发布”。
- 视频页生成成功后会出现“去平台发布”。
- 这两个入口会把当前结果写入发布草稿，再跳到发布页。
- 发布页能继续改标题、正文、标签、目标平台和传输模式。

## 当前支持的平台

- X / Twitter
- 小红书
- 抖音
- 微信朋友圈
- 自定义平台

## 关键限制

- 直连模式仍然要求手机在线、token 有效、APKClaw 可访问。
- 反向通道仍然要求 relay 可被桌面端和手机端同时访问。
- 当前 relay 是轻量 Node 服务，适合先做 smoke 和小规模验证；公网长期运行还需要 HTTPS、访问控制、日志和部署守护。
- 现有 `license_server/server.py` 也已经内置同名 relay API，可直接挂在授权服务公网域名下；它默认 fail-closed，必须配置 `OPENCLAW_PUBLISH_RELAY_TOKEN` 或 `PUBLISH_RELAY_TOKEN` 才允许 packet/poll/complete/status。
- 公网 relay 建议必须设置 `--auth-token`，不要裸露 packet/poll/complete 接口。
- 代理网络模式还没有真机验收，不要把“本地 smoke 已过”等同于“公网生产可用”。

## 常用命令

```bash
npm run phone:publish -- --platform xiaohongshu --title "标题" --body "正文" --image .\a.png
npm run phone:publish -- --transport reverse --platform douyin --packet-out .\publish-packet.json
npm run phone:publish -- --transport reverse --platform douyin --relay-url https://relay.example.com/api/lumi/publish/packet --relay-token <shared-token> --channel publish-channel-01 --wait-relay
npm run phone:relay -- --host 0.0.0.0 --port 8787 --auth-token <shared-token>
npm run phone:relay:check -- --base-url https://relay.example.com --relay-token <shared-token>
npm run phone:relay:smoke
npm run openclaw:context -- --write
```

如果复用线上授权服务，推荐使用授权服务的 env 文件，不要把 token 写进仓库：

```bash
sudo install -m 600 /dev/null /opt/openclaw-license/openclaw-license.env
echo 'OPENCLAW_PUBLISH_RELAY_TOKEN=<shared-token>' | sudo tee /opt/openclaw-license/openclaw-license.env >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart openclaw-license
```

当前仓库里的 `license_server/openclaw-license.service` 已接入 `EnvironmentFile=-/opt/openclaw-license/openclaw-license.env`。如果线上机器还是旧 unit，`license_server/deploy_member_update.py` 在传入 `OPENCLAW_PUBLISH_RELAY_TOKEN` / `PUBLISH_RELAY_TOKEN` / `LICENSE_RELAY_TOKEN` 时，会自动写入 env 文件并安装 `openclaw-license.service.d/publish-relay.conf` drop-in。

Windows 本机部署时可直接把 token 交给部署脚本：

```powershell
$env:LICENSE_SSH_PASSWORD="<ssh-password>"
$env:OPENCLAW_PUBLISH_RELAY_TOKEN="<shared-token>"
python D:\Axiangmu\AUSTART\license_server\deploy_member_update.py
```

然后用授权服务域名跑：

```bash
npm run phone:relay:check -- --base-url https://license.heang.top --relay-token <shared-token>
```

## 验证

```bash
cmd /c npm run build
node --check scripts/openclaw-publish-phone.mjs
node --check scripts/openclaw-publish-relay.mjs
node --check scripts/openclaw-publish-relay-check.mjs
node --check scripts/openclaw-publish-relay-smoke.mjs
node --check scripts/openclaw-context.mjs
npm run phone:relay:smoke
cd ..\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction
.\gradlew.bat :app:compileDebugKotlin
```

## 后续接手建议

1. 先部署一个公网可访问的 relay，使用 `--auth-token`，再跑 `npm run phone:relay:check -- --base-url <url> --relay-token <token>`。
2. 在 APKClaw 设置页填 relay 根地址、channel ID 和同一个 token。
3. 用发布页或 CLI 发 reverse packet，带同一个 relay token；CLI 可加 `--wait-relay` 等待手机 complete 回传。
4. 再做手机开代理/受限网络下的真实发布 smoke。
5. 若要覆盖更多平台，把平台差异继续收敛到 `src/services/publish.ts`。

## 手机侧消费入口

- `POST /api/lumi/publish/execute`
- `POST /api/lumi/publish/packet`

这两个接口都会把发布 packet 转成现有的 Agent 任务 prompt，再复用 APKClaw 的任务执行器。
