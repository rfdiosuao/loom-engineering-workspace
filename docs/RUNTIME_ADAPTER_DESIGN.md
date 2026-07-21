# Runtime Adapter 设计方案 —— 从 OpenClaw 启动器到多 Agent 工作台

> 状态：设计稿 v1（2026-06-10）
> 关联文档：[PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md)、[CI_CD_RELEASE.md](CI_CD_RELEASE.md)

---

## 0. 一句话定位

**不做"能装很多 Agent 的应用商店"，做"任何 Agent 装进来就获得手机控制、桌面 RPA、平台发布能力的工作台"。**

多运行时支持是入口，设备能力层（APKClaw / iOSClaw / SightFlow / 发布工作流）是护城河。所有架构决策以此为准绳：

- 运行时接入成本必须趋近于零（数据驱动，不写死代码）；
- 设备能力必须对所有运行时统一暴露（MCP 协议），而不是为每个运行时单独适配；
- 授权体系跟着能力层走，而不是跟着运行时走（基础启动免费/低价，设备能力按授权解锁）。

---

## 1. 现状问题（为什么要拆）

`python/services/process.py`（约 1850 行）是单个 `OpenClawProcessService` 类，混合了四种职责：

| 职责 | 代表方法 | 与 OpenClaw 耦合度 |
|---|---|---|
| A. 通用进程生命周期 | `start` / `stop` / `status` / `_read_output` / `_wait_until_ready` / `_mark_startup_stage` / `_write_startup_snapshot` | 低 —— 换个运行时逻辑完全一样 |
| B. OpenClaw 专属配置 | `_default_openclaw_config` / `_normalize_openclaw_config` / `_ensure_openclaw_workspace` / `_write_runtime_context` / `_openclaw_version` | 高 —— 这是 OpenClaw 的"知识" |
| C. 环境诊断与修复 | `diagnose_environment` / `_webview2_check` / `_python_runtime_check` / `_portable_integrity_check` / `_security_software_block_check` / `_storage_health_check` | 低 —— 大部分检查与运行时无关 |
| D. 端口/进程清理 | `_kill_port_processes` / `_clawpanel_processes` / `_openclaw_gateway_processes` / `_port_listeners` | 中 —— 机制通用，进程名/端口号是 OpenClaw 的 |

前端侧 `App.tsx` 的 `handleStart` 硬编码了 `http://127.0.0.1:18790`，`registry.ts` 的功能项虽是数据驱动但只描述"一个"运行时。

接入第二个运行时（Hermes 等）若直接复制 process.py，会得到第二个 84KB 文件，维护成本翻倍。**必须先抽接口，再接新运行时。**

---

## 2. RuntimeManifest —— 运行时即数据

每个 Agent 运行时是一份 JSON manifest，放在 `python/runtimes/manifests/<id>.json`（内置）或用户目录（第三方/后装）。启动器核心不认识任何具体运行时，只认识 manifest。

```jsonc
{
  "$schema": "./runtime-manifest.schema.json",
  "id": "openclaw",                      // 唯一 ID，作路由前缀与目录名
  "name": "OpenClaw",
  "version_pinned": "1.4.2",             // 交付版本锁定（可控发布）
  "description": "全能型 AI Agent 运行时",
  "icon": "openclaw.png",
  "tier": "builtin",                     // builtin | verified | community

  "install": {
    "type": "bundled",                   // bundled(随包) | npm | pip | archive
    "source": null,                      // npm包名 / pip包名 / 下载URL模板
    "sha256": null,                      // archive 类型必填，下载校验
    "post_install": []                   // 可选安装后脚本（白名单命令）
  },

  "process": {
    "command": ["{runtime_dir}/openclaw", "serve"],
    "cwd": "{workspace_dir}",
    "env": { "OPENCLAW_HOME": "{data_dir}" },
    "ports": { "main": 18790, "range": [18790, 18799] },
    "health": {
      "type": "http",                    // http | tcp | process
      "url": "http://127.0.0.1:{ports.main}/health",
      "startup_timeout_sec": 420
    },
    "process_markers": ["clawpanel", "openclaw-gateway"]  // 清理时按名匹配
  },

  "ui": {
    "web_console": "http://127.0.0.1:{ports.main}",      // 启动后可打开的页面，可为 null
    "features": ["phone", "desktop", "publish", "image", "video", "skills"]
    // 声明该运行时启用哪些启动器功能页；前端据此过滤导航
  },

  "config": {
    "schema": "configs/openclaw.schema.json",  // 配置项的 JSON Schema，前端自动渲染表单
    "api_key_slots": ["anthropic", "openai"]   // 共享密钥池中该运行时需要哪几类 key
  },

  "context": {
    "format": "openclaw-workspace",      // 工作区注入格式：openclaw-workspace | agents-md | env | none
    "mcp": true                          // 是否支持 MCP（决定设备能力的接入方式）
  },

  "license": {
    "required": false                    // 运行时本身是否需要授权（能力层另行门控）
  }
}
```

设计要点：

1. **`{占位符}` 路径模板**由核心统一解析（`runtime_dir`、`workspace_dir`、`data_dir`、`ports.*`），manifest 里不出现绝对路径——兼容便携盘交付（沿用现有 `core/paths.py` 的包路径解析）。
2. **`tier` 三级信任**：`builtin` 随安装包交付且版本锁定；`verified` 是我们测试签名过的清单（从官网拉取清单索引）；`community` 明确提示风险。配合现有授权体系：免费版只能用 builtin，付费可解锁 verified。
3. **`ui.features` 决定导航**：Hermes 若不支持视频生成，导航里就不出现"AI 视频"。功能页本身不变，变的是可见性——复用 `registry.ts` 已有的 `visible` 字段。
4. **`context.mcp` 是能力层开关**：见第 5 节。

---

## 3. Python 侧拆分方案

### 3.1 目标目录结构

```
python/
├── runtimes/                        # ★ 新增
│   ├── __init__.py
│   ├── manifest.py                  # Manifest 加载/校验/占位符解析
│   ├── registry.py                  # RuntimeRegistry：发现、安装状态、当前激活运行时
│   ├── adapter.py                   # RuntimeAdapter 基类（默认实现全部来自 manifest）
│   ├── installer.py                 # 按 install.type 分发：bundled/npm/pip/archive
│   ├── manifests/
│   │   ├── runtime-manifest.schema.json
│   │   └── openclaw.json
│   └── adapters/
│       ├── openclaw.py              # OpenClaw 专属逻辑（原 process.py 职责 B）
│       └── hermes.py                # 第二运行时（验证用，尽量空——逼自己把通用逻辑放对地方）
├── services/
│   ├── process_host.py              # ★ 通用进程宿主（原 process.py 职责 A+D 的机制部分）
│   ├── diagnostics.py               # ★ 环境诊断（原 process.py 职责 C，运行时无关部分）
│   ├── process.py                   # 过渡期保留为薄兼容层，最终删除
│   └── ...（desktop_agent / image_api / video_api / skills 不动）
└── api/
    ├── routes_runtimes.py           # ★ 新增：GET /runtimes、POST /runtimes/{id}/install|activate
    └── routes_process.py            # 改为操作"当前激活运行时"，对前端接口不变
```

### 3.2 RuntimeAdapter 接口

```python
class RuntimeAdapter:
    """一个 Agent 运行时的全部行为。默认实现完全由 manifest 驱动；
    只有 manifest 表达不了的逻辑才允许子类覆写。"""

    def __init__(self, manifest: RuntimeManifest, paths: AppPaths): ...

    # —— 安装 ——
    def is_installed(self) -> bool: ...
    def install(self, progress: ProgressCall) -> None: ...      # 委托 installer.py
    def installed_version(self) -> str | None: ...

    # —— 配置 ——
    def ensure_config(self) -> tuple[bool, str | None]: ...     # 默认：按 config.schema 校验+补默认值
    def ensure_workspace(self) -> None: ...                     # 默认：按 context.format 分发

    # —— 进程 ——（默认实现全部委托 ProcessHost，参数取自 manifest.process）
    def build_command(self) -> list[str]: ...
    def health_check(self) -> HealthStatus: ...
    def process_markers(self) -> list[str]: ...

    # —— 钩子 ——（默认空操作）
    def pre_start(self) -> None: ...                            # OpenClaw 在此写 runtime-context.json
    def post_stop(self) -> None: ...
    def extra_diagnostics(self) -> list[DiagnosticCheck]: ...   # 运行时专属诊断项
```

`OpenClawAdapter` 覆写的内容就是现 process.py 的职责 B：`_normalize_openclaw_config`（约 50 行的兼容性修正逻辑）、`_ensure_openclaw_workspace`、`_write_runtime_context`、`_runtime_context_check` 与 `_phone_agent_apk_check` 两个专属诊断项。预计 300 行以内。

### 3.3 ProcessHost（通用进程宿主）

从 process.py 原样迁移、按 adapter 参数化的部分：

- `start_background` / `_background_start_worker` / `stop` / `status`（启动锁、退出回调、状态机不变）
- `_read_output` / `_append_output_tail`（日志管道，按 `runtime_id` 分文件：`logs/{runtime_id}/...`）
- `_mark_startup_stage` / `_write_startup_snapshot` / `_read_startup_snapshot`（启动阶段快照，前端进度条依赖它）
- `_wait_until_ready` / `_is_port_listening` / `_port_listeners` / `_kill_port_processes` 系列（端口与清理机制；**端口号和进程名从 adapter 取**，删掉 `_clawpanel_processes` / `_openclaw_gateway_processes` 这种硬编码命名，改为 `manifest.process.process_markers` 驱动）

### 3.4 diagnostics.py

`_webview2_check`、`_python_runtime_check`、`_portable_integrity_check`、`_security_software_block_check`、`_storage_health_check`、`_drive_type_label` 等与运行时无关，平移即可。诊断结果聚合时追加 `adapter.extra_diagnostics()`。

### 3.5 多实例与端口策略

- v1 约束：**同一时刻只允许一个运行时处于 running**（产品上简单，资源上安全，低配机器跑不动两个）。`RuntimeRegistry.activate(id)` 切换激活运行时，切换前必须 stop 当前的。
- 端口冲突：manifest 声明 `ports.range`，ProcessHost 启动前用现有 `_port_range_listeners` 检查并清理本运行时 markers 匹配的残留进程；不属于本运行时的占用进程报诊断错误而不是强杀。

### 3.6 API 与前端兼容

`routes_process.py` 的 `/process/start|stop|status` 语义改为"当前激活运行时"，**请求/响应结构不变**——现有前端零改动也能跑。新增：

```
GET  /runtimes                    → [{id, name, installed, version, active, tier, features}]
POST /runtimes/{id}/install       → 流式进度（复用日志通道）
POST /runtimes/{id}/activate
GET  /runtimes/{id}/config        / PUT 同路径
```

---

## 4. 前端改动

1. **新增"Agent 管理"页**（`group: '扩展'`，排在 Skills 旁边）：卡片列表展示可用运行时（图标/简介/已装版本/tier 徽章），按钮 = 安装 / 激活 / 配置。安装进度复用 BotInstallConsole 的控制台样式。
2. **`registry.ts` 按激活运行时过滤**：`appStore` 增加 `activeRuntime`（含 `features` 数组），`normalizeFeatureNavItems` 据此设置 `visible`。功能页代码不动。
3. **去掉硬编码 18790**：`App.tsx` 启动成功后打开的 URL 改为从 `/process/status` 返回的 `web_console` 字段读取（status 响应里加一个字段即可）。
4. **侧边栏品牌区**显示当前激活运行时的名字/图标（theme 系统已支持动态品牌，复用）。
5. 顺手项（与本方案无强依赖，见 UI 优化清单）：启动按钮渲染 `startupStage` 进度、原生 `confirm` 换自绘 Dialog。

---

## 5. 设备能力层 —— 统一走 MCP

这是整个方案的价值核心：**手机控制、桌面 RPA、平台发布不再是"OpenClaw 的功能页"，而是"工作台提供给任何运行时的工具服务"。**

```
┌─────────────────────────────────────────────┐
│  任意 Agent 运行时 (OpenClaw / Hermes / …)   │
│            │ MCP (stdio 或 SSE)              │
├────────────▼────────────────────────────────┤
│  lumi-device-mcp（新增，Bridge 内置 MCP 服务）│
│  工具集：                                     │
│   phone.screenshot / phone.run_task          │
│   phone.record / phone.import_media          │
│   publish.post(platform, media, text)        │
│   desktop.observe / desktop.act              │
├──────┬──────────────┬───────────────────────┤
│ phoneApi 通道       │ desktop_agent.py       │
│ (APKClaw/iOSClaw)   │ (SightFlow)            │
└──────┴──────────────┴───────────────────────┘
```

实施要点：

1. **lumi-device-mcp 是 Bridge 的一个子模块**（`python/mcp_server/`），把现有 `phoneApi` 通道和 `services/desktop_agent.py` 的能力包装成 MCP 工具。不重写设备通道，只加协议壳。
2. manifest 的 `context.mcp: true` 的运行时，`ensure_workspace` 时自动把 MCP server 注册进该运行时的配置（各家配置格式由 adapter 的 `ensure_workspace` 负责写入——这是 adapter 子类少数需要"懂"运行时的地方）。
3. **授权门控在 MCP 工具层执行**：调用 `phone.*` / `desktop.*` 时校验 license（复用 `license_manager`），未授权返回明确的购买引导信息。这实现了"运行时免费、能力收费"的商业结构，且对所有运行时一视同仁。
4. OpenClaw 现有的直连方式保持不动，MCP 是增量路径；等 MCP 路径稳定后 OpenClaw 也切过去，删掉专用通道。

---

## 6. 落地顺序（四个 Phase，每个独立可交付）

| Phase | 内容 | 验收标准 | 风险 |
|---|---|---|---|
| **P0 纯重构** | 拆 process.py → process_host + diagnostics + openclaw adapter + manifest；routes 兼容层 | 现有功能零回归：启动/停止/诊断/修复全通过现有验收脚本（scripts/ 下的 smoke test）；前端不改一行 | 低。纯搬运，CI 已有 Python compile 检查 |
| **P1 运行时管理** | RuntimeRegistry + installer + `/runtimes` API + 前端 Agent 管理页 | OpenClaw 以 manifest 形式出现在管理页；可停用/激活 | 低 |
| **P2 第二运行时** | 写 hermes.json manifest（install.type=npm 或 archive）+ 最小 adapter；跑通 安装→配置→启动→健康检查→打开 web console | Hermes 在干净虚拟机上全流程可用；`adapters/hermes.py` 不超过 100 行（超了说明通用层抽得不对，返工通用层而不是堆 adapter） | 中：上游版本变动。靠 `version_pinned` + sha256 锁定 |
| **P3 能力层 MCP 化** | lumi-device-mcp（先 phone.screenshot + publish.post 两个工具）+ license 门控 + Hermes 注册 MCP | 在 Hermes 里发指令"截图我的手机并发到平台"全链路成功；未授权时返回购买引导 | 中：MCP 各家支持度差异。先支持 stdio，SSE 后补 |

P0/P1 建议连续做（P1 很薄）；P2 做完就有对外可讲的"多 Agent"故事；P3 是商业价值兑现，可以和 P2 并行启动设计。

### 不做的事（边界）

- ❌ 不做运行时市场/评分/上传（没有生态密度之前是空壳功能）；
- ❌ 不做多运行时同时运行（v1 单激活，省掉端口仲裁和资源争抢的整类问题）;
- ❌ 不为不支持 MCP 的运行时写专用能力桥（`context.mcp: false` 的运行时只有启动管理，没有设备能力——用脚投票，让 MCP 成为接入门槛）;
- ❌ P0 期间不顺手加任何新功能（重构和功能混在一起是回归事故的头号来源）。

---

## 7. 对授权与交付体系的影响

- license server / `license_manager.py` / `license.rs` **均不需要改动**：门控点从"功能页"平移到"功能页 + MCP 工具"，校验逻辑复用。
- 打包脚本（scripts/）：P1 后安装包内置 `manifests/` 目录；bundled 运行时照旧打进包里；verified 清单索引从官网拉取（lumiu-official-site 加一个静态 JSON 即可，无后端改动）。
- `version_pinned` 进入 CI 的版本一致性检查（.github/workflows/ci.yml 已有 version consistency 步骤，扩一条规则）。

---

## 8. 开放问题（实施前需拍板）

1. Hermes 选哪个发行版/安装通道作为 P2 验证对象？（影响 installer 先实现 npm 还是 archive）
2. 共享 API 密钥池（`config.api_key_slots`）v1 是否做？不做的话每个运行时单独配 key，体验差但实现简单。**建议 v1 做读共享、不做写同步**：API 配置对话框存的 key 各运行时 ensure_config 时按 slot 注入。
3. "Agent 管理"页是否对未授权用户可见？**建议可见但 verified 运行时的安装按钮带锁**——让免费用户看到付费能解锁什么。
