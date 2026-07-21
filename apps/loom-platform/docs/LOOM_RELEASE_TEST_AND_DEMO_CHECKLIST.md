# LOOM 发布前测试与演示录制清单

更新时间：2026-06-30

本文用于 LOOM/麓鸣安装器发布前验收、问题修复排期、演示视频录制。当前重点不是扩功能，而是把已有链路做顺、做稳、做得像可交付产品。

## 1. 当前必须处理的问题

### P0：发布前必须修

1. 订阅页打不开网站
   - 入口：账号/订阅/套餐/余额相关按钮。
   - 期望：点击后能稳定打开中转站订阅页面，不能出现空白页、localhost、连接失败、开发环境地址。
   - 验收：未登录时引导登录；已登录时打开对应用户订阅页；断网时给中文提示，不显示技术报错。

2. OpenClaw 打不开网页版
   - 入口：OpenClaw 卡片里的打开网页版/控制台/管理页。
   - 期望：按钮点击后打开正确页面或内置 WebView，不出现无响应。
   - 验收：无网络、服务未启动、端口占用时都有明确状态；成功时能进入可用页面。

3. OpenClaw 无法一键配置模型
   - 入口：OpenClaw 卡片/模型配置区的一键配置。
   - 期望：登录中转站账号后，可从模型列表选择模型，一键写入 OpenClaw 所需配置。
   - 推荐默认：
     - 启动器/主模型：`qwen3.7-plus`
     - 手机 Agent：`agnes-2.0-flash`
   - 验收：配置后重启仍生效；失败时保留旧配置；不把真实 token 打到日志里。

4. 日志太长
   - 期望：默认只展示最近关键日志，不把用户淹没。
   - 建议：
     - 默认显示最近 200 行。
     - 支持“展开完整日志”。
     - 支持“复制日志”和“导出日志”。
     - 错误日志单独高亮。
     - 默认隐藏依赖下载刷屏、底层 debug、重复轮询日志。
   - 验收：普通用户一眼能看到当前步骤、是否成功、失败原因和下一步。

5. 安装页部分字体颜色太浅
   - 期望：浅色/深色主题下都清楚可读。
   - 验收：卡片副标题、状态、说明、禁用按钮、输入框 placeholder 不得低对比；不能出现灰到看不清的文字。

6. 桌面和任务栏 Logo 不够圆滑
   - 期望：桌面图标、任务栏图标、窗口左上角、安装包图标一致且圆滑。
   - 建议：
     - 使用透明背景的圆角图标。
     - 重新生成 `.ico`，至少包含 16、24、32、48、64、128、256 尺寸。
     - 小尺寸不要有毛边、黑边、锯齿。
   - 验收：Windows 桌面、任务栏、Alt-Tab、安装包文件图标都显示正常。

#### 2026-07-01 P0 修复状态

- 订阅页打不开网站：已补未登录引导、离线中文提示、本地/localhost URL 拦截；账号页合同测试通过。
- OpenClaw 打不开网页版：已将 OpenClaw 网页入口改为先检查/启动本地服务，再打开本地网页版；安装页合同测试通过。
- OpenClaw 无法一键配置模型：已纳入 OpenClaw 模型配置入口并复用 OpenClaw 模型同步写入逻辑；wire/config 合同测试通过。
- 日志太长：默认仅显示最近关键日志，完整日志折叠；已补复制日志、导出日志；安装页合同测试通过。
- 安装页部分字体颜色太浅：已提高浅色/深色主题下 `text_subtle` 对比度；主题合同测试通过。
- 桌面和任务栏 Logo 不够圆滑：当前 Tauri 图标已指向 2026-06-28 生成的多尺寸 LOOM 图标资源，32/128/public 图标已视觉抽检；仍需在下一次安装包构建后于 Windows 桌面、任务栏、Alt-Tab 做手工复验。

#### 2026-07-01 P0 复验记录

- P0 合同测试：`test_account_ui_contract`、`test_routes_account`、`test_agent_installer_page_contract`、`test_wire_config`、`test_busy_overlay_contract`、`test_settings_page_contract` 共 45 项通过。
- 全量 Python 合同测试：`python -m unittest discover -s openclaw_new_launcher\python\tests -p "test*.py"` 共 230 项通过。
- 前端构建：`cd openclaw_new_launcher && npm run build` 通过。
- 源码文本：`scripts\verify-source-text.ps1` 通过；指定品牌/乱码扫描未命中 `澶|鏅|绋|鍚|閿|Lumi Agent|LumiClaw|Lumi / OpenClaw`。
- 静态检查：`git diff --check` 通过，仅有 Git 行尾提示。
- 当前候选包校验：`release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable` 与 `release\LOOM-Portable-v2.1.32-20260630-rc1-ui-stable` 均通过 `scripts\verify-release.ps1`；运行日志、账号态、`*.pyc`、`__pycache__` 未混入包内。
- 剩余手工项：下一次安装包构建后必须在 Windows 桌面、任务栏、Alt-Tab 和安装包文件图标上复验 Logo；真实订阅页、OpenClaw 网页入口和一键模型配置仍需用实际登录态做一次点击录屏。

#### 2026-07-01 P0 再复核

- P0 合同测试再次通过：`python -m unittest openclaw_new_launcher.python.tests.test_account_ui_contract openclaw_new_launcher.python.tests.test_routes_account openclaw_new_launcher.python.tests.test_agent_installer_page_contract openclaw_new_launcher.python.tests.test_wire_config openclaw_new_launcher.python.tests.test_busy_overlay_contract openclaw_new_launcher.python.tests.test_settings_page_contract`，45 项 OK。
- 全量 Python 合同测试再次通过：`python -m unittest discover -s openclaw_new_launcher\python\tests -p "test*.py"`，230 项 OK。
- 前端构建再次通过：`cd openclaw_new_launcher && npm run build`。
- 静态检查再次通过：`git diff --check` 无空白错误，仅有 Git 行尾提示；`scripts\verify-source-text.ps1` 通过；品牌/乱码扫描未命中。
- 候选包再次通过：`scripts\verify-release.ps1` 校验在线包与便携包，`scripts\verify-portable-smoke.ps1` 校验便携包。
- 说明：包内 `release-manifest.json` 是已签名的组件安装源 manifest，版本号不等同于启动器包版本；启动器版本以 `package.json`、`tauri.conf.json`、`launcher_runtime.json` 和包名为准。
- 剩余项仍为人工验收：安装后 Windows 桌面/任务栏/Alt-Tab 图标复验，真实登录态下订阅页、OpenClaw 网页入口、一键模型配置点击录屏。

#### 2026-07-01 P0 完整构建与实启复验

- 修复发布前发现的 MCP 版本硬编码风险：`loom_mcp.py` 现在从随包 `package.json` 读取版本；包内在线版与便携版均返回 `2.1.32`。
- 重新执行完整 Tauri 构建，不再复用旧 seed EXE；`build-portable.ps1` 生成的应用为 `app v2.1.32`，并产出 MSI、NSIS 与便携包。
- 新便携包：`release\LOOM-Portable-v2.1.32-20260630-rc1-ui-stable.zip`，SHA256 `CC73AF61E961F6F99A88D59893551DA17274A7E09A190479618D5D9673E8A690`。
- 新在线包：`release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable.zip`，SHA256 `BAEAE35D41C213CD14EDFFF747081B8834AC24513666BAA47E0DE64A0FD9211B`。
- 发布验证通过：在线目录、在线 zip、便携目录、便携 zip 均通过 `scripts\verify-release.ps1`；便携目录通过 `scripts\verify-portable-smoke.ps1`。
- 包实启通过：启动 `release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable\LOOM.exe` 后，窗口进程路径指向当前在线包，bridge-session 刷新为当前进程，首页显示 `LOOM 2.1.32`。
- 安装页实测：检测中主按钮禁用，中央检测动画覆盖当前页面；检测完成后显示 `前置环境已就绪`，日志默认短文案，OpenClaw 卡片显示 `安装并启动`、`打开网页`、模型配置、回滚配置和带锁的一键配置。
- 账号页实测：中转站登录弹窗为麓鸣内置样式，提供验证码登录、密码登录、邮箱注册、访客浏览、订阅页与旧授权码入口。
- 手机页实测：页面按“下载 App -> 连接手机 -> 输入任务 -> 查看结果”组织；未配置设备时检测/截图按钮禁用，任务状态和最近任务区域可见。
- 在线一键安装器已刷新：`release\LOOM-Online-Setup-v2.1.32-20260630-rc1-ui-stable.exe`，SHA256 `860F39893CD8C7428BE52D7634E572469670CB1BF0A33ABDF39B6ED9C21BBD7A`。
- GitHub RC 渠道已推送到 `rfdiosuao/loom-release-channel`，commit `59084d8`；远端 raw manifest、远端在线 zip、远端在线 setup exe 的 hash/size 均已重新下载校验。
- 在线安装器 smoke 通过：用 `--silent --install-dir <临时目录> --no-shortcuts --no-launch` 安装到临时目录，生成 `LOOM.exe`、`LOOMFiles`，`LOOMFiles\package.json` 版本为 `2.1.32`，测试目录已清理。
- 剩余项：真实账号登录、真实订阅页、OpenClaw 网页实际打开、一键模型写入、真机手机任务、Windows 桌面/任务栏/Alt-Tab 图标仍需在测试机上人工录屏复验。

#### 2026-07-01 P0 包卫生补丁与复验

- 发现问题：直接用随包 Python 启动 Bridge/CLI 的验证动作会在展开后的便携目录生成 `__pycache__`、`*.pyc` 和 `jobs-state.json`，导致展开目录 `verify-release.ps1` 失败；在线 zip 与便携 zip 本身仍为干净包。
- 修复：`bridge.py`、`loom_cli.py`、`loom_mcp.py` 在入口最早阶段设置 `sys.dont_write_bytecode = True`；`AppPaths.process_env()` 为后端子进程注入 `PYTHONDONTWRITEBYTECODE=1`，防止 CLI/MCP/子进程把发布目录写脏。
- 恢复：已从已校验通过的 `release\LOOM-Portable-v2.1.32-20260630-rc1-ui-stable.zip` 重新解出便携目录，移除本地验证留下的污染目录。
- 复验通过：`python -m py_compile openclaw_new_launcher\python\bridge.py openclaw_new_launcher\python\loom_cli.py openclaw_new_launcher\python\loom_mcp.py openclaw_new_launcher\python\core\paths.py`。
- 复验通过：P0 合同测试 45 项 OK；CLI/MCP/Task Ledger 合同测试 30 项 OK；全量 Python 合同测试 231 项 OK。
- 复验通过：`cd openclaw_new_launcher && npm run build`、`git diff --check`、`scripts\verify-source-text.ps1`、品牌/乱码扫描均通过。
- 复验通过：在线目录、便携目录、在线 zip、便携 zip 均通过 `scripts\verify-release.ps1`；便携目录通过 `scripts\verify-portable-smoke.ps1`，smoke 后再次严格验证仍无 `__pycache__`、审计日志、任务状态和账号态污染。
- 凭据扫描：排除第三方示例文档后未发现真实 `sk-`、GitHub token、AWS key、私钥、长 token、密码等高危形态；第三方 OpenClaw companion docs 中仍有 `xoxb-...`、`your-password` 等示例占位符，不作为 LOOM 真实凭据。
- 说明：源码侧入口防污染补丁已完成；若要让该补丁进入已上传的在线安装包，需要下一次重新打包并刷新 release channel manifest。

#### 2026-07-01 P0 包卫生补丁入包复验

- 版本更新：启动器从 `2.1.32` 提升到 `2.1.33`，用于发布前 P0 包卫生小版本修复。
- 新便携包：`release\LOOM-Portable-v2.1.33-20260701-rc2-p0-hygiene.zip`，SHA256 `0760A6672E689A12129E7717264ED0F6387C72065144AACA25EF905A992C57D7`。
- 新在线包：`release\LOOM-Online-v2.1.33-20260701-rc2-p0-hygiene.zip`，SHA256 `2C9D288A1227DB61C7E53AA06BDA253F75D8BACF0D36E05F4F300AF71DF71653`。
- 安装器产物：Tauri 重新产出 `openclaw_new_launcher\src-tauri\target\release\bundle\msi\LOOM_2.1.33_x64_en-US.msi` 与 `openclaw_new_launcher\src-tauri\target\release\bundle\nsis\LOOM_2.1.33_x64-setup.exe`。
- MCP 配置修复：包内 `.mcp.json` 现在使用 `python -B LOOMFiles/_up_/python/loom_mcp.py`，并注入 `PYTHONDONTWRITEBYTECODE=1`，避免 Codex/Claude Code 调 MCP 时把随包目录写脏。
- 包内 CLI/MCP smoke：`status --json`、`phone status --json`、`phone run-task --dry-run --json`、MCP tool import 均返回结构化 JSON；未启动 Bridge 时为结构化 `bridge_unavailable`，不出现堆栈。
- 运行污染复验：对 `2.1.33 rc2` 便携目录执行带 `-B` 的 CLI/MCP smoke 后，`__pycache__`、`*.pyc`、审计日志、任务状态、账号态污染数量为 0；随后 `scripts\verify-release.ps1` 仍通过。
- 发布验证通过：`2.1.33 rc2` 的便携目录、便携 zip、在线目录、在线 zip 均通过 `scripts\verify-release.ps1`；便携目录通过 `scripts\verify-portable-smoke.ps1`。
- 测试通过：`python -m unittest discover -s openclaw_new_launcher\python\tests -p "test*.py"` 共 231 项 OK；`npm run build` 通过；`git diff --check` 通过。
- 未上传说明：`2.1.33 rc2` 目前为本地候选包，尚未刷新 GitHub release channel；在线安装器 exe 也未指向该新包，需上传后再生成/验证最终在线安装器。

#### 2026-07-01 P0 版本显示修复与 rc3 复验

- 发现问题：Computer Use 启动 `2.1.33 rc2` 在线包后，总览页仍显示 `LOOM 2.1.32`；根因是 `DashboardPage.tsx` 与 `SettingsPage.tsx` 内仍硬编码旧版本。
- 修复：新增 `src\version.ts`，从根 `package.json` 读取 `APP_VERSION`；总览状态卡和设置关于页均改为使用 `APP_VERSION`；补 `test_frontend_version_contract.py` 防止前端版本再次硬编码。
- 新便携包：`release\LOOM-Portable-v2.1.33-20260701-rc3-version-fix.zip`，SHA256 `528A323B75D9EC4330BFFE914A534802809A82253544F4F2F944FC565DBE839D`。
- 新在线包：`release\LOOM-Online-v2.1.33-20260701-rc3-version-fix.zip`，SHA256 `9821E24E758628B9E23B7DA161A2CA04AD9C37CE9F223E104B5214171D503675`。
- 发布验证通过：`rc3` 便携 zip、在线 zip、在线展开目录均通过 `scripts\verify-release.ps1`；便携构建过程内的 strict -> smoke -> strict 验证通过。
- 包内 smoke：`loom_cli.py status --json` 返回结构化 JSON；`loom_mcp.py` 包内加载版本为 `2.1.33`，工具数量为 20；执行后运行污染计数为 0。
- Computer Use 复验：显式启动 `release\LOOM-Online-v2.1.33-20260701-rc3-version-fix\LOOM.exe`，进程路径正确，首页可访问树和截图均显示 `LOOM 2.1.33`。
- Computer Use 入口点击：总览、安装、模型账号、手机、其他、系统设置均能打开；安装页检测期间会锁住误点，检测完成后恢复；模型账号入口打开麓鸣原生中转站登录弹窗；其他能力显示 `暂未开放` 稳定页；设置页显示外观/更新/数据/关于。
- 仍未上传说明：`rc3` 仍为本地候选包，尚未刷新 GitHub release channel；在线安装器 exe 仍需在上传后按最终下载 URL 重建。

#### 2026-07-01 P0 MCP stdio 首包兼容修复与 rc4 复验

- 发现问题：Windows PowerShell/cmd 管道在首行 JSON-RPC 前带 BOM 或把 `UTF-8 BOM + {` 解成 `锘縶`，导致 MCP 第一条 `tools/list` 请求返回 `Parse error`；后续工具调用可执行，但 Codex/Claude Code 首次发现工具可能不稳定。
- 修复：`loom_mcp.py` 在 JSON-RPC 边界增加 `_normalize_rpc_line()`，兼容标准 `\ufeff` 与 Windows mojibake BOM，并补 `test_mcp_accepts_utf8_bom_on_first_stdio_line`、`test_mcp_accepts_windows_mojibake_bom_on_first_stdio_line`。
- 新便携包：`release\LOOM-Portable-v2.1.33-20260701-rc4-mcp-stdio-fix.zip`，SHA256 `9E74D68E432B10678ED768346FB2E01F0301C72B2B23CE7D87CC39FA8701EB69`。
- 新在线包：`release\LOOM-Online-v2.1.33-20260701-rc4-mcp-stdio-fix.zip`，SHA256 `017DE34E8FDA82FAAC08EF82668BCCA5D68E13D79943DEA7676166F0F9E21B95`。
- 发布验证通过：`rc4` 便携 zip 与在线 zip 均通过 `scripts\verify-release.ps1`；便携构建流程内 strict -> smoke -> strict 全部通过。
- 包内 CLI smoke：`status --json`、`phone read-screen --dry-run --json` 返回结构化 JSON。
- 包内 MCP stdio smoke：首包 `tools/list` 返回 20 个工具；`loom_phone_read` 返回 `/api/phone/read`；高风险 `批量私信所有客户` 返回 `safety_confirmation_required`。
- 包污染复验：`rc4` 在线展开目录与便携展开目录运行污染计数均为 0。
- Secret scan：源码与 `rc4` 在线/便携包高危形态扫描未命中真实 `sk-*`、GitHub token、AWS key、Slack token 或私钥块；宽泛 `token/password` 关键词仅命中文档、变量名与测试占位符。
- 仍未上传说明：`rc4` 仍为本地候选包，尚未刷新 GitHub release channel；在线安装器 exe 仍需在上传后按最终下载 URL 重建。

#### 2026-07-01 P0 rc9 收尾复验

- 修复：`routes_phone.py` 中剩余手机任务/截图进度乱码已改为 `手机任务进入 Agent 兜底`、`手机截图缓存命中`、`手机截图`、`手机截图缓存已命中`；未改动 `/api/lumi/*`、`X-LUMI-*`、`lumiLauncherId`、`lumiLauncherSecret` 等手机兼容签名字段。
- 最新便携包：`release\LOOM-Portable-v2.1.33-20260701-rc9-phone-text-final.zip`，SHA256 `BE968979F2C0838F32294F98986AF22185D4F6E97AE1863B2B7E5EA3AE92D137`。
- 最新在线包：`release\LOOM-Online-v2.1.33-20260701-rc9-phone-text-final.zip`，SHA256 `7184B646E2299343CB724F52F146DF8416AF915C3E694918EAF3C0B5D6CE5135`。
- 验证通过：源码文本检查、品牌/乱码扫描、手机合同测试 60 项、全量 Python 合同测试 249 项、`npm run build`、便携/在线目录与 zip 的 `verify-release.ps1`、便携 smoke、CLI smoke、MCP stdio smoke。
- 包卫生复验：rc9 在线/便携展开目录中 `__pycache__`、`*.pyc`、`mcp-audit.jsonl`、`task-ledger.jsonl`、`jobs-state.json`、账号快照/会话文件计数均为 0。
- 剩余人工项：真实账号登录后的订阅页、OpenClaw 网页入口、一键模型配置、真实手机任务、Windows 桌面/任务栏/Alt-Tab 图标仍需在测试机录屏复验；rc9 尚未上传 GitHub release channel。

#### 2026-07-01 P0 rc9 真窗口入口复验

- 实启路径确认：运行中的 `LOOM.exe` 进程路径为 `release\LOOM-Online-v2.1.33-20260701-rc9-phone-text-final\LOOM.exe`，窗口标题为 `LOOM - 麓鸣智能体安装与手机控制启动器`。
- 安装页复验：前置环境检测完成后显示 `前置环境已就绪`；检测期间遮罩覆盖完整业务区域，按钮禁用且页面无半透明断层；日志默认显示短文案。
- 订阅页复验：未登录状态点击 `打开订阅页` 后显示 `请先登录中转站账号，再打开订阅页`，未出现空白页、`localhost` 或浏览器原生错误。
- OpenClaw 网页入口复验：选择 OpenClaw 后可见 `打开网页`；未安装状态点击后显示 `请先安装 OpenClaw，再打开网页版`，没有静默无响应。
- OpenClaw 一键配置复验：未登录/未同步模型时 `一键配置` 显示带锁禁用态，说明为 `登录后解锁：请先同步中转站模型`；模型默认显示 `qwen3.7-plus`。
- 手机页复验：主流程按 `下载 App -> 连接手机 -> 输入任务 -> 查看结果` 展示；未配置设备时检测/截图按钮禁用，任务结果、执行记录、最近任务区域可见。
- 本轮验证再次通过：P0 合同测试 45 项、全量 Python 合同测试 251 项、`npm run build`、`git diff --check`、`scripts\verify-source-text.ps1`、品牌/乱码扫描。
- 仍需真实环境录屏：真实账号登录后的订阅页、OpenClaw 已安装后的实际网页打开和一键模型写入、真实手机任务、Windows 桌面/任务栏/Alt-Tab 图标。

#### 2026-07-01 MCP/CLI 安全补丁提醒

- 源码侧已补：`phone read-screen` 可作为安全定时任务命令；手机 quick/run-task 与 Matrix 一样拦截批量私信、评论、自动回复、群发等外发高风险提示，返回 `safety_confirmation_required`。
- 源码侧已补：`.mcp.json`、打包脚本生成的 `.mcp.json` 和 Agent 接入页示例都加入 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`，避免 Windows MCP stdio 中文 prompt 被系统代码页打成问号。
- 验证通过：CLI/MCP/Task Ledger/scheduler/Matrix/phone fast-path 合同测试 49 项、全量 Python 合同测试 257 项、`npm run build`、CLI smoke、MCP stdio smoke、secret scan。
- 打包提醒：当前 rc9 展开包仍通过 `verify-release.ps1`，但不包含上述 MCP UTF-8/安全门源码补丁；上传或分发前必须重新打 rc10 包。

#### 2026-07-01 P0 rc10 打包复验

- 最新便携包：`release\LOOM-Portable-v2.1.33-20260701-rc10-mcp-utf8-safety.zip`，SHA256 `BEACA2DA3456695B860824884B36F48F63B425BC2376B276A86997F752BB6EFD`。
- 最新在线包：`release\LOOM-Online-v2.1.33-20260701-rc10-mcp-utf8-safety.zip`，SHA256 `00BFFB3EEAB5A6EE117FE8F230DC2BBE5F5D7B55C632DF3941168D1FC62F5C35`。
- rc10 包内 `.mcp.json` 已确认包含 `PYTHONDONTWRITEBYTECODE=1`、`PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`，并通过 `python -B LOOMFiles/_up_/python/loom_mcp.py` 启动 MCP。
- 发布验证通过：rc10 便携目录、便携 zip、在线目录、在线 zip 均通过 `scripts\verify-release.ps1`；便携目录通过 `scripts\verify-portable-smoke.ps1`。
- 包内 CLI smoke 通过：`status --json`、`phone read-screen --dry-run --json` 返回结构化 JSON；`phone run-task --prompt "批量私信所有客户" --dry-run --json` 在 `control` 权限下返回 `safety_confirmation_required`。
- 包内 MCP stdio smoke 通过：`tools/list` 返回 20 个工具；`loom_phone_quick_task` 传入中文高风险 prompt 后返回 `safety_confirmation_required`，未被 Windows 编码绕过。
- 包卫生复验：rc10 在线展开目录运行 smoke 后，`__pycache__`、`*.pyc`、`mcp-audit.jsonl`、`task-ledger.jsonl`、`jobs-state.json`、账号快照/会话文件计数为 0。
- 剩余人工项不变：真实账号登录后的订阅页、OpenClaw 已安装后的网页入口和一键模型写入、真实手机任务、Windows 桌面/任务栏/Alt-Tab 图标仍需在测试机录屏复验。

### P1：演示前建议修

1. 检测动画跟随滚动异常
   - 问题：上半部分虚化、后半部分清晰，视觉割裂。
   - 期望：检测中要么锁定页面滚动，要么 overlay 固定在视口，不能跟内容错位。

2. 安装过程体感不顺
   - 期望：每个安装卡片都有明确状态：未安装、检测中、可安装、安装中、已安装、失败可重试。
   - 验收：按钮点击后 300ms 内有反馈，不能像卡死。

3. 错误提示不应出现英文堆栈
   - 期望：用户看到中文原因和下一步。
   - 验收：真实错误可在“开发者日志/导出日志”里查，但主界面不露堆栈。

4. OpenClaw 字眼收敛
   - 期望：LOOM 是多 Agent 安装器，不是 OpenClaw 专属启动器。
   - 验收：主导航、首页标题、安装器主文案不再围绕 OpenClaw 展开；OpenClaw 只作为一个可安装组件出现。

## 2. 发布前完整测试路径

### A. 首次启动

1. 双击打开 LOOM。
2. 确认不是开发者模式，不出现 `localhost`、Vite、React 开发错误页。
3. 检查窗口标题、Logo、任务栏图标、版本号。
4. 检查首页加载速度：不能长时间白屏。
5. 检查检测动画：不能错位，不能遮挡按钮，不能半透明割裂。

### B. 账号与订阅

1. 点击登录。
2. 测试邮箱/用户名登录。
3. 测试注册入口。
4. 测试验证码入口，如果当前版本支持。
5. 登录后显示账号状态、余额/额度/订阅状态。
6. 点击订阅页，确认能打开正确网站。
7. 退出登录，再重新登录。
8. 断网后打开账号页，确认显示上次快照或明确提示。

### C. 安装智能体

1. 检测 Codex。
2. 检测 Claude Code。
3. 检测 opencode。
4. 检测 OpenClaw。
5. 检测 Hermes。
6. 未安装时按钮状态正确。
7. 已安装时显示“已安装/运行中”。
8. 点击安装时进入安装状态，有进度反馈。
9. 安装失败时可以重试，不显示英文堆栈。
10. 日志默认不刷屏，只展示关键步骤。

### D. 模型配置

1. 登录中转站账号。
2. 同步模型列表。
3. 给 Codex 配置模型。
4. 给 Claude Code 配置模型。
5. 给 OpenClaw 一键配置模型。
6. 手机 Agent 默认选择 `agnes-2.0-flash`。
7. 启动器默认主模型为 `qwen3.7-plus`。
8. 重启 LOOM 后模型配置仍存在。
9. 配置失败时不清空旧配置。
10. 日志不得泄露 API Key、token、密码。

### E. 手机控制

1. 连接手机。
2. 检查设备在线状态。
3. 截图预览能正常刷新。
4. 执行一次简单点击任务。
5. 执行一次打开 App 任务。
6. 执行一次模板任务。
7. 执行中切换页面再回来，任务状态不能丢。
8. 执行失败时显示失败原因、当前步骤、可重试动作。
9. 长任务异步执行时，UI 不阻塞。
10. 多设备能力如果未完成，必须明确显示暂未开放，不要假装可用。

### F. 日志与诊断

1. 普通日志默认折叠或截断。
2. 错误日志清楚可见。
3. 支持复制日志。
4. 支持导出日志。
5. 日志里不出现真实密钥。
6. 失败时能定位到模块：账号、订阅、安装、模型、手机、网络。

### G. UI 体感

1. 所有按钮点击都有反馈。
2. 禁用按钮有原因。
3. 字体颜色足够清楚。
4. 卡片状态不混乱。
5. 页面没有大段废话。
6. 主页面只保留必要标题和必要状态。
7. 暂未开放的模块统一上锁，不让用户误点。
8. 页面切换不闪白、不重置正在执行的任务。

## 3. 演示视频录制脚本

建议录制 3 到 5 分钟版本，给别人看“这东西能干什么”，不要录成长教程。

### 镜头 1：打开 LOOM

展示点：
- 桌面图标。
- 启动速度。
- 首页干净。
- 当前版本号。

一句话介绍：
“这是 LOOM，一套面向 AI Agent 的安装、配置和手机自动化工作台。”

### 镜头 2：登录中转站账号

展示点：
- 点击登录。
- 输入账号。
- 登录成功。
- 显示订阅/余额/模型能力。

重点：
- 用户不需要手动填 API Key。
- 登录后自动同步可用模型。

### 镜头 3：安装智能体

展示点：
- Codex 卡片。
- Claude Code 卡片。
- opencode/OpenClaw/Hermes 卡片。
- 已安装/未安装/运行中状态。

重点：
- LOOM 不是单一启动器，而是多 Agent 安装器。
- 安装状态清晰，日志不刷屏。

### 镜头 4：一键配置模型

展示点：
- 选择模型。
- 一键配置 Codex/Claude/OpenClaw。
- 手机 Agent 使用 `agnes-2.0-flash`。

重点：
- 不需要用户理解复杂配置文件。
- 模型来自中转站账号。

### 镜头 5：手机控制

展示点：
- 连接手机。
- 查看截图。
- 发起一个简单任务。
- 任务执行中切换页面再回来，状态仍在。

重点：
- 手机 Agent 可以异步执行。
- 后续可扩展到手机矩阵。

### 镜头 6：订阅页

展示点：
- 点击订阅。
- 打开中转站订阅页面。
- 展示套餐/余额入口。

重点：
- 商业闭环在 LOOM 内可以走通。

### 镜头 7：结束页

展示点：
- 回到安装智能体或手机控制页。
- 展示所有关键模块稳定。

一句话收尾：
“LOOM 的目标是让 Agent 从安装、模型、执行到手机自动化形成一条可交付链路。”

## 4. 录制前禁止出现的内容

1. `localhost` 页面。
2. Vite/React/Tauri 开发报错。
3. 英文堆栈。
4. 真实 API Key、token、密码。
5. 大面积 OpenClaw 专属文案。
6. 看不清的浅灰字。
7. 点按钮无反馈。
8. 日志刷屏超过主内容。
9. 订阅页打不开。
10. 手机任务执行中状态丢失。

## 5. 给修复会话的提示词

```text
请阅读 D:\Axiangmu\AUSTART\docs\LOOM_RELEASE_TEST_AND_DEMO_CHECKLIST.md，然后按 P0 优先级修复 LOOM 发布前问题。

约束：
1. 主线围绕 D:\Axiangmu\AUSTART\openclaw_new_launcher。
2. 不要重构无关模块。
3. 不要破坏已有 NewAPI 登录、旧授权码回退、手机控制接口。
4. 不要把真实 token、密码、API Key 写进源码或日志。
5. UI 文案保持克制，不添加大段解释。
6. 修完后逐项更新该文档的验收状态。

优先修：
1. 订阅页打不开。
2. OpenClaw 打不开网页版。
3. OpenClaw 一键配置模型。
4. 日志太长。
5. Logo 桌面/任务栏圆滑度。
6. 安装页字体颜色太浅。
7. 检测动画滚动错位。

验收：
1. npm build 或项目现有前端构建通过。
2. 相关 Python/Node contract tests 通过。
3. 手动点击所有本次修复入口。
4. 确认打包后不是开发者模式，不出现 localhost。
5. 输出一份修复清单和剩余风险。
```

## 6. 最小发布口径

如果时间紧，演示版只承诺这些：

1. 支持中转站账号登录。
2. 支持订阅页入口。
3. 支持安装/检测 Codex、Claude Code、opencode、OpenClaw、Hermes。
4. 支持模型同步与一键配置。
5. 支持手机连接、截图、基础任务执行。
6. 支持任务执行中页面切换不丢状态。
7. 其他模块显示暂未开放。

不要承诺：

1. 全自动手机矩阵稳定获客已经完成。
2. 所有 Agent 都能真实全自动安装成功。
3. 所有平台自动化都已稳定。
4. OpenClaw 视频/图像/桌面 RPA 全链路都已交付。

## 7. 发布前最终检查

1. 版本号正确。
2. 安装包名称正确。
3. Logo 正确。
4. 首屏不是开发者页面。
5. 登录可用。
6. 订阅可打开。
7. 模型可同步。
8. OpenClaw 可打开网页。
9. OpenClaw 可一键配置模型。
10. 手机控制可跑一个最小任务。
11. 日志不泄密。
12. UI 无明显浅色看不清。
13. 打包后在另一台 Windows 上能打开。
14. Windows 安全警告如仍存在，需要在交付说明里解释签名状态。
15. 演示视频录制完成并保存到发布资料目录。

## 8. 2026-07-01 P0 rc13 公开包复验

- rc11/rc12 处理结论：rc11 已废弃，因为 MCP stdio 在 Windows 管道乱码时可能把高风险中文任务变成 `????????`；rc12 验证发现便携包误带内部测试 APK，因此不作为公开候选包。
- 源码修复：CLI/MCP 对疑似乱码控制任务增加安全拦截，`phone run-task` 与 `phone quick-task` 在中文高风险任务或 `????` 类乱码 prompt 下都返回结构化 `safety_confirmation_required`。
- 公开候选包：`release\LOOM-Portable-v2.1.34-20260701-rc13-public-clean.zip`，SHA256 `E5C535375FCBD182EEBF0610F1498C7B321BCE6B5C8F7D853286901F5515C911`。
- 在线候选包：`release\LOOM-Online-v2.1.34-20260701-rc13-public-clean.zip`，SHA256 `B4B4A3D3AE5C24C3A9DE2A27C3FB3815E9FB11A0F3A09C726F54B700F15D1983`。
- 验证通过：`python -m unittest discover -s openclaw_new_launcher\python\tests -p "test*.py"` 共 268 项 OK；`npm run build` 通过；`git diff --check` 通过；品牌/乱码扫描无命中。
- 包验证通过：rc13 便携目录、便携 zip、在线目录、在线 zip 均通过 `scripts\verify-release.ps1`；便携目录通过 `scripts\verify-portable-smoke.ps1`；安装 manifest 通过 `scripts\verify-installer-manifest.ps1`。
- 包内 smoke 通过：随包 CLI `status --json`、`phone read-screen --dry-run --json` 返回结构化 JSON；高风险中文任务和乱码任务均返回 `safety_confirmation_required`；随包 MCP `tools/list` 返回 20 个工具，`loom_phone_quick_task` 乱码任务返回结构化安全拦截。
- 包卫生通过：rc13 在线包与便携包均未发现 `mcp-audit.jsonl`、`task-ledger.jsonl`、`jobs-state.json`、`*.pyc`、`__pycache__`、`*.apk`、账号会话或模型同步运行态文件。
- Computer Use 点击复验：显式启动 rc13 在线包后，首页显示 `LOOM 2.1.34`，安装页检测态可见且按钮禁用，检测完成后显示前置环境已就绪；手机页按“下载 App -> 连接手机 -> 输入任务 -> 查看结果”组织；模型账号弹窗包含验证码登录、密码登录、邮箱注册、访客、订阅页、旧授权码；设置页更新文案已改为“智能体运行时更新”。
- 剩余人工验收：真实中转站账号登录后的订阅页、OpenClaw 已安装状态下网页入口和一键模型写入、真机手机任务、Windows 桌面/任务栏/Alt-Tab 图标仍需在测试机录屏确认。

## 9. 2026-07-01 P0 rc14 CLI UTF-8 补丁入包复验

- rc14 取代 rc13 的原因：裸 Windows 环境下直接调用随包 CLI/MCP 时，如果没有外部设置 `PYTHONUTF8` 或 `PYTHONIOENCODING`，中文 JSON stdout 可能按系统代码页输出；已在 `loom_cli.py` 与 `loom_mcp.py` 入口自配置标准流为 UTF-8，并补回归测试。
- 新便携包：`release\LOOM-Portable-v2.1.34-20260701-rc14-cli-utf8.zip`，SHA256 `07E09383BEFBEDFE73C277D57C35E801981DC01A1125B40422B5C37C4A70D12D`。
- 新在线包：`release\LOOM-Online-v2.1.34-20260701-rc14-cli-utf8.zip`，SHA256 `9A1090C200E3708865AE204FB5A3E4161DD615516D6A93D00CFA89D29A9DC0FA`。
- 源码验证通过：`python -m unittest discover -s openclaw_new_launcher\python\tests -p "test*.py"` 共 269 项 OK；`npm run build` 通过；`git diff --check` 通过；`py_compile` 覆盖 Bridge、CLI、MCP、账号、组件、手机和配置写入相关文件。
- 文本验证通过：`scripts\verify-source-text.ps1` 通过；品牌/乱码扫描未命中 `澶|鏅|绋|鍚|閿|Lumi Agent|LumiClaw|Lumi / OpenClaw`。
- 发布验证通过：rc14 便携目录、便携 zip、在线目录、在线 zip 均通过 `scripts\verify-release.ps1`；便携目录通过 `scripts\verify-portable-smoke.ps1`；在线包内 `release-manifest.json` 通过 `scripts\verify-installer-manifest.ps1`。
- 包内 UTF-8 smoke 通过：在移除 `PYTHONUTF8` 与 `PYTHONIOENCODING` 的环境下，随包 CLI `phone read-screen --dry-run --json` 可被严格 UTF-8 解码，并保留中文 prompt；`status --json`、`phone status --json`、`phone run-task --prompt ???????? --permission control --dry-run --json` 均返回结构化 JSON，乱码控制任务被 `safety_confirmation_required` 拦截。
- 包内 MCP smoke 通过：`LOOM_MCP_PERMISSION=control` 下，随包 MCP `tools/list` 返回 20 个工具；`loom_phone_quick_task` 对乱码控制任务返回结构化 `safety_confirmation_required`。
- 包卫生通过：rc14 在线包与便携包未发现 `mcp-audit.jsonl`、`task-ledger.jsonl`、`jobs-state.json`、`*.pyc`、`__pycache__`、`*.apk`、账号会话、账号快照、模型同步运行态或 `openclaw_ui_integration` 路径。
- 凭据扫描通过：rc14 在线/便携 zip 文本扫描未发现意外真实 `sk-*`、GitHub PAT、AWS key、Slack token；仅 Pillow 第三方字体数据存在一个 AWS-key 形态假阳性，已记录为第三方库噪声。
- 实启 smoke 通过：显式启动 `release\LOOM-Online-v2.1.34-20260701-rc14-cli-utf8\LOOM.exe`，进程路径指向 rc14 在线包，窗口标题为 `LOOM - 麓鸣智能体安装与手机控制启动器`；随后已清理旧 release 测试残留 Python bridge 进程，避免端口误判。
- 剩余人工验收不变：真实中转站账号登录后的订阅页、OpenClaw 已安装状态下网页入口与一键模型写入、真机手机任务、Windows 桌面/任务栏/Alt-Tab 图标仍需在测试机录屏确认；在线一键 EXE 安装器仍需在上传 rc14 zip 到稳定 URL 后再重建。

## 10. 2026-07-01 P0 源码侧再复验与凭据扫描修正

- 已按本清单 P0 顺序复核当前主线：订阅页、OpenClaw 网页入口、一键模型配置、短日志、字体对比、检测遮罩、CLI/MCP/手机任务安全门均已有源码或合同测试覆盖。
- 修正 `scripts\verify-release-secrets.ps1`：启用 `-Source` 后若再次显式传入 `openclaw_new_launcher`、`scripts`、`docs` 源码根，不再把这些源码根当成发布包目录重复扫描；避免将已忽略的 `agents`、`target` 等第三方/构建产物误判为发布包内容。正式 zip/目录扫描逻辑不变。
- 源码凭据扫描通过：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-release-secrets.ps1 -Source -Path openclaw_new_launcher scripts docs`，检查 343 个文本文件，未发现真实 token、密码、API Key、私钥或 GitHub/AWS/Slack 凭据。
- rc14 包凭据扫描通过：`scripts\verify-release-secrets.ps1 -Source -Path release\LOOM-Online-v2.1.34-20260701-rc14-cli-utf8.zip release\LOOM-Portable-v2.1.34-20260701-rc14-cli-utf8.zip`，检查 2056 个文本文件，仅保留 2 个已允许的第三方库噪声。
- P0/手机/MCP 合同复验通过：`python -m unittest openclaw_new_launcher.python.tests.test_account_ui_contract openclaw_new_launcher.python.tests.test_routes_account openclaw_new_launcher.python.tests.test_agent_installer_page_contract openclaw_new_launcher.python.tests.test_wire_config openclaw_new_launcher.python.tests.test_busy_overlay_contract openclaw_new_launcher.python.tests.test_settings_page_contract openclaw_new_launcher.python.tests.test_matrix_control_plane openclaw_new_launcher.python.tests.test_routes_matrix openclaw_new_launcher.python.tests.test_loom_cli_contract openclaw_new_launcher.python.tests.test_loom_mcp_contract openclaw_new_launcher.python.tests.test_task_ledger_contract openclaw_new_launcher.python.tests.test_phone_signature_contract`，97 项 OK。
- 全量 Python 合同复验通过：`python -m unittest discover -s openclaw_new_launcher\python\tests -p "test*.py"`，269 项 OK。
- 前端构建复验通过：`cd openclaw_new_launcher && npm run build`。
- 静态与文本复验通过：`git diff --check` 通过，仅有 Git 行尾提示；`scripts\verify-source-text.ps1` 通过；品牌/乱码扫描未命中 `澶|鏅|绋|鍚|閿|Lumi Agent|LumiClaw|Lumi / OpenClaw`。
- 剩余人工验收不变：真实中转站账号登录后的订阅页、OpenClaw 已安装状态下网页入口与一键模型写入、真机手机任务、Windows 桌面/任务栏/Alt-Tab 图标仍需在测试机录屏确认；本轮未重新打包、未上传 GitHub。
