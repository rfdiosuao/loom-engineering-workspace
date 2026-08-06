# LOOM Engineering Workspace 全项目代码审查

审查日期：2026-08-06  
审查基线：`main` / `afaaa8ca93f75ae9b421cb8539658413869bdb22`  
仓库：`rfdiosuao/loom-engineering-workspace`

## 结论

当前版本不建议直接作为稳定版发布。桌面端主体的更新签名、Bridge 监听地址、手机安全通道和授权域隔离整体设计较认真，但手机端局域网配置服务存在一个可直接泄露渠道密钥并远程改写配置的严重鉴权缺口；调试 APK 还暴露了未鉴权的设备工具执行与文件读取能力。发布前至少应关闭下文 P0、P1 项。

本次共确认 9 项问题：1 项 P0、4 项 P1、3 项 P2、1 项 P3。结论只记录能够从代码或本地复现得到证据的问题，不把猜测列为缺陷。

## 审查范围

仓库约 1,784 个文件，重点覆盖：

- `apps/loom-platform/openclaw_new_launcher`：React/Vite UI、Tauri/Rust 壳、FastAPI Bridge、Node CLI、更新与组件安装。
- `apps/loom-phone-agent`：Android Agent、NanoHTTPD 控制面、Lumi HMAC 安全通道、RPA 与渠道接入。
- `apps/loom-platform/license_server`：授权、账户、激活码、发布中继与管理后台。
- `apps/loom-platform/template_cloud_server`：获客模板云服务。
- `.github/workflows`、`packages/contracts`、`packages/skills`、发布脚本及项目文档。

严重度定义：P0 为可造成密钥/控制权直接失陷且利用门槛低；P1 为高影响安全或数据可靠性问题；P2 为边界受限但应修复的问题；P3 为维护与交付风险。

## 发现

### P0 — 手机配置服务可在局域网内未鉴权读取渠道密钥并改写配置

位置：

- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServer.kt:19-22`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServer.kt:43-47`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServer.kt:359-375`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServer.kt:378-487`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServer.kt:490-542`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServer.kt:702-708`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServerManager.kt:42-55`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServerManager.kt:83-95`

`ConfigServer` 使用 `NanoHTTPD(port)` 启动，管理器明确返回局域网地址并会在已有 LLM 配置时自动启动。`GET/POST /api/channels` 和 `GET/POST /api/llm` 没有调用 `TokenValidator` 或 `LumiSecurityController.authorize`。

其中 `GET /api/channels` 原样返回钉钉、飞书、QQ 的 Secret，以及 Discord、Telegram Bot Token；POST 接口可覆盖这些凭据并重新初始化渠道。LLM POST 接口还可把模型地址和 API Key 改到攻击者控制的服务。所有响应同时设置 `Access-Control-Allow-Origin: *`。

影响：同一 Wi-Fi、热点或可达局域网中的任意主机都能窃取机器人凭据、劫持渠道、破坏模型配置；在浏览器允许访问私网资源的情况下，恶意网页也可直接发起跨域请求。

建议：

1. 除一次性配对入口外，所有配置接口统一强制使用现有 Lumi Token + HMAC；不要逐个路由手工补鉴权。
2. GET 永不返回原始 Secret，只返回 `configured` 与固定长度掩码。
3. 默认仅绑定 loopback；需要 LAN 配置时由用户显式开启短时会话，并显示一次性口令/二维码。
4. 移除通配 CORS，限制到配对页面的精确来源，并加入 CSRF/重放保护。
5. 增加发布版集成测试：缺失、错误、过期 Token 访问每个配置路由均应为 401/403。

### P1 — 调试 APK 暴露未鉴权的设备控制、屏幕数据和目录穿越文件读取

位置：

- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServer.kt:266-271`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServer.kt:547-657`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServer.kt:660-684`
- `.github/workflows/phone-ci.yml:50-58`
- `apps/loom-phone-agent/README_CN.md:246-249`

`BuildConfig.DEBUG` 只决定路由是否存在，并没有增加鉴权。调试构建中的 `/api/debug/execute` 可直接调用 `ToolRegistry.executeTool`，`/api/debug/screen-full` 返回完整无障碍树，`/api/debug/file` 返回本地文件。

文件校验使用 `file.absolutePath.startsWith(cacheDir)`，没有 canonicalize。形如 `cache/../shared_prefs/...` 的路径在字符串检查时仍以 cache 目录开头，但打开文件时会解析 `..`，因此可越出 cache 目录。CI 同时构建并上传 debug APK，README 也把 `assembleDebug` 作为常规构建路径，不能把它视为永远不会安装到真实设备的死代码。

影响：安装 debug APK 的设备在局域网内可被远程操作，屏幕结构和应用私有文件可被读取；结合配置服务问题，风险进一步放大。

建议：删除网络调试执行面，或至少复用正式安全通道与显式的设备端确认；文件读取使用 `canonicalFile` 后再以路径组件判断父子关系；CI 调试包标注高风险并设置短保留期，避免把它当作可分发安装包。

### P1 — 模板云在并发上传时会报错、丢数据或错误覆盖版本

位置：

- `apps/loom-platform/template_cloud_server/server.py:18-60`
- `apps/loom-platform/template_cloud_server/server.py:63-83`
- `apps/loom-platform/template_cloud_server/server.py:333-336`

服务采用 `ThreadingHTTPServer`，但 `TemplateStore.upsert()` 的“读取整个 JSON → 修改 → 写回”过程没有任何锁或事务。所有线程还共用同一个 `${db}.tmp` 临时文件名。

本地用 20 个线程并发写入 100 个不同模板时，复现了 `PermissionError`（多个线程争用同一 `.tmp`）；在允许替换已打开文件的系统上仍存在旧快照覆盖新快照的问题，因此会静默丢模板或回退版本号。

建议：迁移到 SQLite 并用事务/唯一键完成 upsert；短期方案至少为整个 read-modify-write 临界区加进程锁，为每次写入创建唯一临时文件，并在读取失败时 fail closed，不能把损坏文件当作空库继续覆盖。

### P1 — 授权服务无请求体上限和读取超时，可被远程耗尽内存与线程

位置：

- `apps/loom-platform/license_server/luming_license/http/responses.py:12-15`
- `apps/loom-platform/license_server/luming_license/cli.py:34`
- `apps/loom-platform/license_server/luming_license/config.py:75-76`
- `apps/loom-platform/license_server/openclaw-license.service:7-16`

`read_json()` 完全信任 `Content-Length`，直接执行 `self.rfile.read(length)`，没有最大值、分块限制或 socket 读取超时。生产配置使用 `ThreadingHTTPServer` 监听 `0.0.0.0`，systemd 服务还以 root 运行。

影响：未认证攻击者可向任意公开 POST 路由发送超大请求体造成内存压力，或以多个慢速请求长期占用线程；服务以 root 运行会放大任何后续服务端漏洞的影响。

建议：统一限制 JSON 请求体（例如 1 MiB，确有批量需求的路由单独放宽），在读取前返回 411/413，设置连接与读取超时；生产环境由反向代理再次限制 body/连接；systemd 改为专用低权限用户并启用 `NoNewPrivileges`、`ProtectSystem`、`PrivateTmp` 等隔离。

### P1 — Android 全局允许明文 HTTP，模型 API Key 和内容可能被明文发送

位置：

- `apps/loom-phone-agent/app/src/main/res/xml/network_security_config.xml:3`
- `apps/loom-phone-agent/app/src/main/AndroidManifest.xml:31-35`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/ui/settings/LlmConfigActivity.kt:34-46`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/agent/llm/OpenAiLlmClient.kt:43-52`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/agent/llm/OpenAiLlmClient.kt:271-277`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/agent/llm/AnthropicLlmClient.kt:43-50`

网络安全配置对整个应用设置 `cleartextTrafficPermitted="true"`。设置页不校验 Base URL 协议，OpenAI/Anthropic 客户端会把 API Key 放进请求头后直接请求该 URL。

影响：用户误填或被未鉴权配置接口改写为 `http://` 地址后，API Key、提示词、屏幕信息和模型回复均可在网络中被窃听或篡改。

建议：凭据型出站客户端强制 HTTPS；若必须支持本机开发服务，只允许 loopback/明确私网地址并要求用户单独开启“允许不安全连接”，同时显示不可忽略的风险提示。局域网手机控制所需的 HTTP 例外不应通过全局放开来实现。

### P2 — `/api/storyboard/generate` 漏掉 Bridge Token 校验

位置：

- `apps/loom-platform/openclaw_new_launcher/python/api/routes_storyboard.py:66-83`
- `apps/loom-platform/openclaw_new_launcher/python/api/fastapi_routes.py:36-41`
- `apps/loom-platform/openclaw_new_launcher/python/bridge.py:866-871`

同文件的参数读取和导入路由会先调用 `ctx.auth_error(request)`，但生成路由只检查商业功能权限，随后直接取得已登录 Agent 的 `model_client` 发起生成。FastAPI 的全局 middleware 只做商业功能拦截，不做 Bridge Token 校验，所以这里没有其他保护层兜底。

Bridge 仅监听 `127.0.0.1` 且响应 CORS 限制为 Tauri 来源，因此风险小于手机端问题；但本机其他进程仍可绕过随机 Bridge Token，读取用户工程输入并消耗其模型账户额度。

建议：把 Bridge Token 校验提升到全局 middleware，明确列出无需鉴权的健康检查/预检路由；为所有路由建立自动化 inventory 测试，断言缺失或错误 Token 时均被拒绝。

### P2 — 授权登录限流可通过伪造代理头绕过，审计 IP 也不可信

位置：

- `apps/loom-platform/license_server/luming_license/http/handler.py:78-90`
- `apps/loom-platform/license_server/luming_license/http/routes_auth.py:45-64`

`request_ip()` 无条件优先采用 `CF-Connecting-IP`、`X-Real-IP`、`X-Forwarded-For`，不验证直接连接者是否为可信反向代理。登录限流键为 `request_ip + username`。

影响：直接访问服务的攻击者可以每次更换 `X-Real-IP` 绕过同一账户的登录限流；管理审计中记录的来源地址也可伪造。

建议：只有当 TCP peer 位于显式可信代理列表时才解析转发头；否则只使用 `client_address`。由边缘代理覆盖而不是追加外部传入的相关头，并增加直接连接伪造头的测试。

### P2 — 构建依赖存在一个已知高危 DoS 漏洞

位置：

- `apps/loom-platform/openclaw_new_launcher/package-lock.json:1534-1543`
- `apps/loom-platform/openclaw_new_launcher/package-lock.json:4096-4105`

2026-08-06 执行 `npm audit` 报告 1 个 high：`brace-expansion@5.0.8` 受 GHSA-rgw5-rvv9-x895 影响。依赖链为：

`javascript-obfuscator@4.1.1 → multimatch@5.0.0 → minimatch@10.2.5 → brace-expansion@5.0.8`

它主要位于受保护发行构建链，不是已安装桌面应用的直接远程入口，因此列为 P2。修复版本可用。

建议：刷新 lockfile 到 `brace-expansion >= 5.0.9`，重新执行 build/contract/release 校验；CI 增加 `npm audit --audit-level=high`，并注意 devDependency 也参与正式发行构建。

### P3 — 文档仍把旧 UI 树描述为当前主启动器，存在构建错误版本的风险

位置：

- `apps/loom-platform/docs/LOOM_FRONTEND_BACKEND_SEPARATION_GOAL.md:41`
- `apps/loom-platform/docs/validation/LOOM_COMMERCIAL_STABLE_2.1.56_20260710.md:26`
- `apps/loom-platform/docs/site/dev/architecture.md:22-25`
- `apps/loom-platform/docs/site/advanced/release-packaging.md:9-69`
- `apps/loom-platform/docs/site/guide/install-update.md:101`

较新的交付文档明确规定 `openclaw_new_launcher` 是当前事实源，`openclaw_ui_integration` 是旧 UI；但站点架构、发布和开发指南仍将旧目录称为“当前主启动器”，并给出从旧目录构建的命令。两个树同时保留了大量近似代码。

影响：新成员或自动化脚本可能修复、测试或发布错误的代码树，导致新安全修复没有进入交付物。

建议：在旧目录根增加明确的 deprecated 标识，CI 禁止它进入正式包；统一更新站点文档和命令，长期将旧树移到归档分支或单独仓库。

## 其他安全观察

- QQ Bot 调试日志会输出完整 access-token 响应以及 Authorization 前 20 个字符：`QBotApiClient.java:147`、`QBotWebSocketManager.java:189-190`。建议即使在 debug 构建也只记录状态码、过期时间和不可逆指纹，不记录任何 Token 内容。
- 源码凭据扫描未发现明显的真实 GitHub PAT、私钥或生产 API Key；命中的 `sk-...` 均位于测试夹具。但聊天中曾提供过一个 GitHub PAT，本报告未复制该值，仍建议立即在 GitHub 中撤销并重新生成。

## 做得较好的部分

- 桌面 Bridge 默认绑定 `127.0.0.1`，由 Tauri 生成随机 Token；大多数路由已显式校验。
- Lumi 手机正式控制面使用 Token、HMAC、时间戳、nonce 与请求体摘要，并为配对/凭据轮换建立了独立流程。
- 桌面更新同时校验 SHA-256、Ed25519 清单签名和 Windows Authenticode，并限制安装包必须位于外部更新缓存。
- 组件归档处理验证相对路径；TGZ 拒绝链接等非普通文件；失败安装有 staging/rollback/health-check 状态。
- 授权服务使用 PBKDF2、随机会话、哈希化会话存储、HttpOnly/Secure/SameSite Cookie、角色隔离、危险操作确认和脱敏审计。
- 测试覆盖面较广，特别是 Agent 副作用幂等、批准流程、手机签名、更新回滚和授权租户隔离。

## 验证记录

已执行：

- 前端生产构建：通过（Vite 处理 2,128 个模块）。
- Node 手机/发布契约测试：66/66 通过。
- 模板云单元测试：5/5 通过。
- 授权服务测试：162 个中 160 个通过；2 个 CLI 兼容用例因源码归档不含测试硬编码期待的 `openclaw_new_launcher/python-runtime/python.exe` 而无法启动，不是断言失败。
- 安装完整 Python 依赖后，模板云同步、媒体能力、Matrix 无 job-id 三个定向回归用例：3/3 通过。
- 模板云并发复现：20 线程写入 100 个模板时触发共享 `.tmp` 文件争用异常。
- `npm audit`：1 个 high，详见依赖问题。

未完整执行：

- 全量 Launcher Python 测试在本地 120 秒审查窗口内未跑完；已运行部分不能替代 CI 全量结果。
- 前端契约测试在当前宿主 Node 24 环境中于 `tsx` 初始化阶段触发 `uv_os_get_passwd ENOMEM`，测试代码尚未开始执行；生产构建与不依赖 tsx 的 Node 契约测试均通过。
- Android Gradle 构建/真机测试、Rust `cargo check` 和完整安装器烟测未在本次本地审查中执行。

## 建议修复顺序

1. 立即停用或隔离手机配置服务的未鉴权路由；旋转可能已暴露的所有渠道密钥。
2. 移除/加固 debug HTTP 工具面，并修复 canonical path 校验。
3. 修复模板云并发存储与授权服务的请求体/超时边界。
4. 强制模型凭据只走 HTTPS；补全 Storyboard Bridge 鉴权。
5. 修复代理头信任和构建依赖告警。
6. 清理旧 UI 事实源和发布文档，随后跑完整 CI、Android release 构建和安装器烟测。

