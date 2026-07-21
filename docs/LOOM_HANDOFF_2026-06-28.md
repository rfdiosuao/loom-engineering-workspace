# LOOM / 麓鸣交接文档

日期：2026-06-28

当前分支：`codex/xinflo-style-super-installer`

项目根目录：`D:\Axiangmu\AUSTART`

## 当前状态

这是一个大范围 WIP 分支，工作区很脏。不要直接打包、不要直接发布、不要直接推主线。

已经发生的主要变化：

- 启动器方向从 OpenClaw 专用壳改成多智能体安装器。
- 新增/整理了智能体安装页、能力中心页、组件安装后端、Job API、CLI 网关。
- 删除了一批旧页面：飞书/微信弹窗、发布页、旧手机页、旧图片页、旧视频页、旧 Skills 页等。
- 包链路开始从 `OpenClawFiles` 迁到 `LOOMFiles`，主程序开始迁到 `LOOM.exe`。
- `data/themes/lumi` 已移动为 `data/themes/loom`。
- 开始把主品牌从 Lumi Agent 改成 LOOM，但还没做完，也未完成最终验证。

## 重要提醒

用户已经要求停止继续盲改，先固化 UI 方案和交接。下一位 Codex 接手时，必须先读：

1. `docs/LOOM_UI_BASELINE.md`
2. `docs/LOOM_HANDOFF_2026-06-28.md`
3. `git status --short --branch`
4. `git diff --stat`

不要继续发散 UI。UI 已固定为“心流式浅色专业安装器”。

## 当前已知风险

### 1. LOOM 改名未完成

仍可能残留：

- `Lumi Agent`
- `LumiClaw`
- `Lumi-Desktop`
- `Lumi-Agent-Launcher`
- `Luminode` 用户可见文案
- `lumi:*` npm script 主入口
- Mac 在线包脚本中的 `lumi`
- README、docs、文档站中的旧品牌

允许保留但只能作为协议兼容：

- `/api/lumi/*`
- `X-LUMI-*`
- `lumiLauncherId`
- `lumiLauncherSecret`
- `Invalid Lumi signature`

这些不能改坏，否则手机 APK 安全通道会断。

### 2. 主题和中文文案可能仍有乱码

重点检查：

- `openclaw_new_launcher/python/core/theme_manager.py`
- `openclaw_new_launcher/src/components/agents/AgentInstallerPage.tsx`
- `openclaw_new_launcher/src/App.tsx`
- `openclaw_new_launcher/data/themes/*/theme.json`

必须清掉类似：

- `澶`
- `鏅`
- `绋`
- `鍚`
- `閿`

### 3. 安装器还不是真正可交付

子智能体审查结论：

- 现有安装接口没有产品级 dry-run。
- `installer` / `tgz` 类型没有真正安装，只是保存文件。
- `healthCheck` 解析了但没有执行。
- 取消、重试、回滚状态不完整。
- 示例 manifest 有占位 URL / sha / signature，不能当正式发布源。

下一步不要急着打包，先把安装状态机补实。

### 4. NewAPI 登录和模型选择还需要完整验证

目标流程：

1. 用户用中转站账号登录。
2. 启动器自动创建或读取 API Token。
3. 同步文本模型和图片模型。
4. 用户只选模型，不手填 API Key。
5. 默认文本模型建议走 `qwen3.7-plus`。
6. 手机同步按钮可以把 `agnes-2.0-flash` 写到手机配置。
7. 视频模型先展示，不自动切 provider。

必须真实测试 `api.heang.top`，但不要在文档或源码里写入账号密码。

## 下一位 Codex 的执行顺序

### 第一阶段：止血

1. 不改功能，先跑：

```powershell
git status --short --branch
rg -n "澶|鏅|绋|鍚|閿|Lumi Agent|LumiClaw|Lumi / OpenClaw" openclaw_new_launcher/src openclaw_new_launcher/data openclaw_new_launcher/python
```

2. 修复乱码文案和 LOOM 主品牌残留。
3. 只保留协议层 `lumi` 残留。
4. 跑：

```powershell
cd openclaw_new_launcher
npm run build
```

### 第二阶段：安装器状态机

实现后端模拟安装：

- `/api/components/install` 支持 `mode: "simulate"` 或 `dryRun: true`。
- 模拟安装不访问网络，不写真实安装目录。
- 同一条流程要走：准备、下载、校验、安装、配置、检测、已就绪。
- UI 增加“模拟安装”按钮。
- 真实安装继续保留，但不要默认点真实下载。

补真实安装语义：

- zip：解压并检查 entry。
- tgz：明确支持或标为暂不支持。
- installer：不要假装安装成功，必须有真实执行策略或明确“下载完成，等待用户安装”。
- healthCheck：执行并写状态。
- rollback：按 manifest 的 installPath 找回滚路径，不要只按 component_id 猜。

### 第三阶段：账号和模型

1. 确认账号登录按钮有效。
2. 确认兼容授权码入口还在。
3. 登录后拉取模型列表。
4. 增加模型选择 UI。
5. 保存后写入启动器文本模型与图片模型配置。
6. 手机同步模型按钮单独做，别混在登录流程里。

### 第四阶段：真实用户体感测试

优先源码调试，不要频繁打包。

必须测试：

- 首次打开不是空白页。
- 登录弹窗能打开。
- 访客模式可浏览。
- 智能体页能模拟安装五个 agent。
- 页面切换后图片/视频任务不丢。
- 桌面 RPA 启停按钮不能卡死。
- 所有主按钮点一遍，没用的删，有用的留下。

## 工作区清理建议

先不要物理删除文档，先归档。建议新建：

```text
docs/_archive/openclaw-history/
docs/_archive/lumi-history/
docs/_archive/old-designs/
```

优先归档这些噪声：

- `docs/OPENCLAW_RUNTIME_CONSOLE_MIGRATION_ARCHITECTURE.md`
- `docs/OPENCLAW_SUPER_INSTALLER_ARCHITECTURE.md`
- `docs/OPENCLAW_SUPER_INSTALLER_IMPLEMENTATION_PLAN.md`
- `openclaw_new_launcher/docs/LUMI_AGENT_PLATFORM_ROADMAP.md`
- `openclaw_new_launcher/docs/LUMI_PERSONAL_UI_DESIGN.md`
- `openclaw_ui_integration/docs/LUMI_AGENT_PLATFORM_ROADMAP.md`
- `openclaw_ui_integration/docs/LUMI_PERSONAL_UI_DESIGN.md`
- 旧的 `LumiClaw-*` 发布记录可留在历史归档，不要放在当前新手文档入口。

保留这些：

- `docs/LOOM_UI_BASELINE.md`
- `docs/LOOM_HANDOFF_2026-06-28.md`
- 发布 SOP
- 手机 APK 安全通道协议文档
- NewAPI 登录与模型同步设计
- 当前 docs 站源码

## 验证命令

接手后不要跳过这些：

```powershell
git diff --check
python -m py_compile `
  openclaw_new_launcher/python/bridge.py `
  openclaw_new_launcher/python/api/routes_components.py `
  openclaw_new_launcher/python/api/routes_account.py `
  openclaw_new_launcher/python/core/component_installer.py `
  openclaw_new_launcher/python/core/newapi_account_manager.py

cd openclaw_new_launcher
npm run build
```

如果 build 未通过，不要打包。

## 给下一位 Codex 的一句话

先把 LOOM / 麓鸣这套 UI 和产品边界收紧，再补安装器状态机，最后才做打包和服务器发布。不要再把旧 OpenClaw 页面、飞书微信入口、星空背景和长文案塞回去。
