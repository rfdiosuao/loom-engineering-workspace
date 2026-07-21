# OpenClaw / Lumi 交接文档

更新时间：2026-05-25

这份文档给下一次会话窗口用。目标是让接手的人不需要重新翻半小时上下文，就能知道：

1. 现在做到哪了
2. 还缺什么 / 还没验证什么
3. 下一步先做什么
4. 代码风格和边界是什么

---

## 1. 当前定位

- 主启动器仓库：`D:\Axiangmu\AUSTART\openclaw_new_launcher`
- 手机端仓库：`D:\Axiangmu\AUSTART\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction`
- 授权服务端：`D:\Axiangmu\AUSTART\license_server`

当前主线不是再加单点生成能力，而是把“生成 -> 发布 -> 手机执行 -> 回传结果”这条链补完整。

当前重点是：

- 直连模式：桌面端直接指挥 APKClaw
- 反向通道模式：手机在代理/受限网络下也能接收任务

---

## 2. 已完成的内容

### 启动器侧

- 新增平台发布页
- 新增发布草稿 handoff
- 图片页 / 视频页成功后可以跳转到平台发布
- 新增发布 CLI：`scripts/openclaw-publish-phone.mjs`
- 新增发布 relay：`scripts/openclaw-publish-relay.mjs`
- 新增公网 relay check：`scripts/openclaw-publish-relay-check.mjs`
- 新增 relay smoke：`scripts/openclaw-publish-relay-smoke.mjs`
- 发布协议模型已定义：`openclaw.publish.packet.v1`
- `scripts/openclaw-context.mjs` 已暴露发布能力和 consumer endpoint
- `package.json` 已新增 `npm run phone:relay`
- `package.json` 已新增 `npm run phone:relay:check`
- `package.json` 已新增 `npm run phone:relay:smoke`
- `npm run build` 已通过
- `node --check scripts/openclaw-publish-phone.mjs` 已通过
- `node --check scripts/openclaw-publish-relay.mjs` 已通过
- `node --check scripts/openclaw-publish-relay-check.mjs` 已通过
- `node --check scripts/openclaw-publish-relay-smoke.mjs` 已通过
- `node --check scripts/openclaw-context.mjs` 已通过
- relay 本地 smoke 已通过：`packet -> poll -> complete -> status`
- relay 已支持共享 token 鉴权：`--auth-token` 或 `OPENCLAW_PUBLISH_RELAY_TOKEN`
- `scripts/openclaw-publish-phone.mjs` 反向模式已支持 `--wait-relay`，可等待手机 worker complete 后返回 `done/failed`
- `license_server/server.py` 已内置同名 relay API；线上授权服务可直接承载 `/api/lumi/relay/*`，未配置 `OPENCLAW_PUBLISH_RELAY_TOKEN` 时 fail-closed
- `license_server/openclaw-license.service` 已接入可选 env 文件：`/opt/openclaw-license/openclaw-license.env`
- `license_server/deploy_member_update.py` 和 `license_server/deploy.sh` 已支持写入 relay token env、安装 systemd drop-in，并在重启后验证 relay health

### 手机端（APKClaw）侧

- 已补 `/api/lumi/publish/execute`
- 已补 `/api/lumi/publish/packet`
- 这两个接口会把发布 packet 转成现有 Agent 任务 prompt，再复用现有执行器
- 已补 `PublishRelayManager`，手机端可按 relay base URL + channel ID 长轮询 packet
- 已补发布中转设置页：可配置 relay base URL、channel ID、relay token、enable/disable，自检通过后启动 worker
- 已接入启动链路：`AppViewModel.afterInit()` 启动/停止 worker，网络恢复时 `ClawApplication` 触发重连
- `./gradlew.bat :app:compileDebugKotlin` 已通过

### 文档侧

- 已有平台发布交接文档：`D:\Axiangmu\AUSTART\openclaw_new_launcher\docs\OPENCLAW_PLATFORM_PUBLISH_HANDOFF.md`
- 已有任务总表：`D:\Axiangmu\AUSTART\openclaw_new_launcher\docs\task.md`

---

## 3. 现在还没补完 / 还没验完的关键缺口

### 3.1 公网部署和真实代理网络 E2E 还没验

现在代码层已经有 relay / queue 服务、APKClaw 轮询 worker、设置入口和本地 relay smoke。

还没完成的是：

- 选定真实公网 relay 部署地址，并用 HTTPS 暴露
- APK 真机填入 relay base URL 和 channel ID 后跑一次真实 publish packet
- 公网 relay 必须配置共享 token，并在发布页/CLI/APKClaw 设置页使用同一个 token
- 手机开代理/受限网络下的端到端验证
- 失败重试、租约超时、重复 complete 的真实设备验收

也就是说：

- 现在能“定义任务”
- 现在能“把任务交给 APKClaw 的执行入口”
- 现在也能“通过 relay 被手机轮询取走并回传结果”
- 但还不能算完成公网代理网络验收

### 3.2 APKClaw 侧配置入口已补，仍需真机 UI 验证

已补：

- relay base url
- channel id
- relay token
- enable/disable 开关
- 保存后的启动自检

还需要在真机上确认：

- 设置页文案和状态显示正常
- 自检失败时不会误启 worker
- 自检成功后重启 App 仍能自动恢复轮询

### 3.3 仍有明显的文档 / 编码债

当前仓库里还有不少历史文件存在 `????`、乱码、缺失元素 id、脚本和 HTML 不一致的问题。

这批问题暂时不要顺手扩大成大重构，优先做成“可用、可查、可回滚”的小修。

---

## 4. 下一窗口先做什么

优先级顺序如下：

1. 先做真实设备端 smoke
   - 直连模式
   - 反向模式
   - 代理网络模式
2. 确定公网 relay 部署方式
   - 先用 `npm run phone:relay -- --host 0.0.0.0 --port 8787 --auth-token <shared-token>`
   - 用公网域名/隧道/反代暴露 HTTPS
   - 或复用 `license_server`：把 `OPENCLAW_PUBLISH_RELAY_TOKEN=<shared-token>` 写入 `/opt/openclaw-license/openclaw-license.env` 后重启
   - 也可以让 `license_server/deploy_member_update.py` 处理 env/drop-in：本机设置 `OPENCLAW_PUBLISH_RELAY_TOKEN` 或 `LICENSE_RELAY_TOKEN` 后执行部署脚本
   - 跑 `npm run phone:relay:check -- --base-url https://<host> --relay-token <shared-token>` 验证公网 relay 自身闭环
   - APKClaw 设置页填写 relay 根地址和同一个 token，不要把 `/api/lumi/...` path 填进根地址
3. 用发布页或 CLI 发一条 reverse packet
   - channel ID 必须和 APKClaw 设置页一致
   - 发布页 relay URL 建议填 `https://<host>/api/lumi/publish/packet`
   - 发布页 / CLI 的 Relay Token 必须和 relay 服务、APKClaw 设置页一致
   - CLI 建议加 `--wait-relay`，等待手机执行后返回 relay 状态
4. 再回头清理文档和编码债
   - 先修会阻塞使用的文件
   - 不要一口气清空所有历史包袱

---

## 5. 反向通道栈状态

这里不是指整个项目缺少大框架，而是记录反向通道运行基础设施的当前状态。

### 5.1 当前已有的栈

- 启动器前端：TypeScript + React + Vite + Tailwind
- 启动器桥接：Python
- 桌面壳：Tauri + Rust
- 手机端：Android Kotlin / Java
- 脚本：PowerShell + Node `.mjs`
- 文档：UTF-8 中文 Markdown

### 5.2 反向通道栈当前状态

- 反向通道 relay / queue 服务栈：已补 Node `.mjs` 小服务
- 公网鉴权栈：已补共享 token header 鉴权，公网部署时必须启用
- 任务持久化和重试栈：已补 JSON 状态文件、lease、retry、failed/done 状态
- Android 轮询 worker 栈：已补 `PublishRelayManager`
- 代理网络下的端到端验收栈：未验，下一步做真机公网 smoke

### 5.3 不建议现在额外引入的新栈

不要为了这个问题再引一套新的重服务架构。优先复用当前已有技术栈：

- relay 可以先用 Node 或 Python 小服务实现
- 手机端用现有网络层和定时轮询补齐
- 不要为了“看起来更正式”先上复杂中间件

---

## 6. 代码风格和实现约定

### 启动器前端

- 用 TypeScript + React 函数组件
- 新状态优先放到 Zustand store 或明确的 service 文件里
- 能拆就拆，不要把页面写成一坨
- 业务数据和 UI 逻辑分开
- 新功能优先走现有的页面 / service / store 结构

### 启动器后端

- Python 侧继续保持“小服务 + 明确函数边界”
- Rust / Tauri 只做必要壳层，不把业务逻辑往 Rust 里堆
- CLI 和脚本保持显式参数，不要藏默认行为

### 手机端 APKClaw

- Kotlin / Java 保持 controller / service / tool 分层
- 配置继续走 `KVUtils`
- 新接口统一放在 `server/`
- 工具类继续放在 `tool/`
- 网络接口保持 `/api/lumi/*` 命名风格

### 文档和脚本

- 文档必须 UTF-8
- 中文说明优先，不要再混入乱码占位
- Windows 下的构建 / 验证尽量用 PowerShell
- Node 脚本继续用 `.mjs`
- 验证动作尽量固定成：
  - `npm run build`
  - `cargo check`
  - `node --check ...`
  - `python -m py_compile ...`

### 修改原则

- 尽量做小改动
- 先补边界和数据入口
- 不要为了一个 bug 顺手重构整个页面
- 不要到处加特殊判断

---

## 7. 当前建议的验证方式

### 启动器

```powershell
cd D:\Axiangmu\AUSTART\openclaw_new_launcher
npm run build
```

### 手机端

```powershell
cd D:\Axiangmu\AUSTART\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction
./gradlew assembleDebug
```

### Node 脚本

```powershell
node --check D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-publish-phone.mjs
node --check D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-publish-relay.mjs
node --check D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-publish-relay-check.mjs
node --check D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-publish-relay-smoke.mjs
node --check D:\Axiangmu\AUSTART\openclaw_new_launcher\scripts\openclaw-context.mjs
```

### Relay 本地 smoke

```powershell
cd D:\Axiangmu\AUSTART\openclaw_new_launcher
npm run phone:relay -- --host 127.0.0.1 --port 8799 --wait-ms 0
npm run phone:relay:smoke
npm run phone:relay:check -- --base-url https://<public-relay-host> --relay-token <shared-token>
```

`phone:relay:smoke` 会启动一个带 token 的本地 relay，验证未授权请求是 `401`，授权链路最终为 `done`。

### Python

```powershell
python -m py_compile D:\Axiangmu\AUSTART\openclaw_new_launcher\python\core\license_manager.py
python -m py_compile D:\Axiangmu\AUSTART\license_server\server.py
```

---

## 8. 交接给下一窗口的直接指令

下一窗口不用重新分析大背景，直接接这几个动作：

1. 不要再从“缺 relay 服务”开始；relay 服务和 APK 轮询 worker 已经补上
2. 先在真机 APKClaw 设置页填公网 relay 根地址、channel ID 和 relay token
3. 用发布页或 CLI 发送 reverse packet，带同一个 relay token；CLI 可加 `--wait-relay` 确认手机 complete 回传
4. 在代理网络下做一次真实发布验证
5. 再回头修文档和编码债

不要把直连模式删掉。
不要把发布协议改回仅 CLI 输出。
不要为了这次交接去做大范围重构。
