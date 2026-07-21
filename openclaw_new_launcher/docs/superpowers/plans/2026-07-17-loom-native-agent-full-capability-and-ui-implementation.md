# 麓鸣原生智能体完整能力继承与交互升级实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让麓鸣原生中枢智能体自动继承并真实调用全部已连接能力，完成生图、图片编辑、视频生成、单机手机和多机矩阵闭环，同时交付会话级模型切换、自动范围、新输入区和可靠的“正在思考”反馈。

**Architecture:** `CapabilityRegistry` 是唯一能力事实源，统一合并 Internal、MCP、CLI 和 Skill，并只把已连接执行器的能力注入模型。第一方媒体、手机和矩阵能力通过服务适配层复用现有路由/任务实现；所有手机写操作在编排器中按能力元数据绑定 `requestScope`，继续经过 Policy、TaskGrant、租约、审批和急停。前端只负责模型与可选范围的人类控制，不再发送能力白名单。

**Tech Stack:** Python 3.11+、FastAPI、本地 JSON/JSONL 存储、OpenAI-compatible SSE、React 18、TypeScript、Zustand、Tailwind CSS、Tauri 2、Node test runner、Playwright。

## Global Constraints

- 产品基线为 LOOM `2.1.89 Hotfix`，不得改变既有 API 路径。
- 麓鸣原生 Agent 是唯一默认运行时，不重新引入外部 Agent 运行时选择器。
- 普通界面不得暴露 canonical 能力 ID、网关别名、英文权限代码或原始协议错误。
- 所有已连接 Internal、MCP、CLI、Skill 自动进入模型工具目录；不可用空壳不得注入模型。
- 生图、图片编辑、视频生成、单机手机和多机矩阵必须有真实执行器及闭环测试。
- 手机写操作不得扩大用户范围；继续执行 Policy、TaskGrant、矩阵租约、审批、取消和急停规则。
- 模型切换默认只影响当前会话；只有显式命令可以修改麓鸣全局默认模型。
- 页头删除 `</>` 和重复“新对话”；会话栏 `+` 是唯一常驻新建入口。
- 发送后 100 毫秒内显示“正在思考”，并支持 `prefers-reduced-motion` 和读屏。
- 不覆盖工作树中其他会话的未提交修改；每个任务只暂存其 `Files` 清单中的文件。

---

### Task 1: 固化模型工具别名双向映射

**Files:**
- Modify: `python/core/loom_model_client.py`
- Modify: `python/tests/test_loom_model_client.py`
- Modify: `python/tests/test_native_agent_integration.py`

**Interfaces:**
- Produces: `_model_tool_alias_maps(capabilities) -> tuple[dict[str, str], dict[str, str]]`
- Produces: `ChatAggregate.tool_name_map: dict[str, str]`
- Preserves: 模型侧工具名最长 64 字符，执行侧始终收到 canonical 能力 ID。

- [ ] **Step 1: 保留并复核当前失败测试**

测试必须覆盖点号转下划线、64 字符限制和归一化碰撞：

```python
def test_complete_restores_gateway_safe_tool_alias_to_capability_name(self):
    request = {"capabilities": [{"name": "loom.mcp.loom.loom_status", "inputSchema": {"type": "object"}}]}
    response = client.complete(request, lambda _event: None, threading.Event())
    self.assertEqual(response["toolCalls"][0]["name"], "loom.mcp.loom.loom_status")

def test_complete_keeps_normalized_tool_aliases_unique(self):
    aliases = _model_tool_alias_maps([
        {"name": "loom.mcp.a.b-c"},
        {"name": "loom.mcp.a.b.c"},
    ])[0]
    self.assertNotEqual(aliases["loom.mcp.a.b-c"], aliases["loom.mcp.a.b.c"])
    self.assertTrue(all(len(alias) <= 64 for alias in aliases.values()))
```

- [ ] **Step 2: 运行定向测试确认基线**

Run: `$env:PYTHONPATH='python'; python -m unittest discover -s python/tests -p "test_loom_model_client.py" -v`

Expected: 所有别名、流式聚合和脱敏测试通过。

- [ ] **Step 3: 确认请求编码与响应还原使用同一请求级映射**

实现保持以下合同，不做全局可变映射：

```python
canonical_to_alias, alias_to_canonical = _model_tool_alias_maps(capabilities)
payload_tool_name = canonical_to_alias[canonical_name]
canonical_name = aggregate.tool_name_map.get(provider_tool_name, provider_tool_name)
```

- [ ] **Step 4: 运行原生 Agent 工具闭环**

Run: `$env:PYTHONPATH='python'; python -m unittest discover -s python/tests -p "test_native_agent_integration.py" -v`

Expected: 模型返回安全别名后，`CapabilityRegistry.execute()` 收到 canonical ID，测试通过。

- [ ] **Step 5: 提交本任务**

```powershell
git add -- python/core/loom_model_client.py python/tests/test_loom_model_client.py python/tests/test_native_agent_integration.py
git commit -m "fix: restore native agent capability aliases"
```

---

### Task 2: 把能力注册表升级为唯一可执行目录

**Files:**
- Modify: `python/core/agent_capabilities.py`
- Modify: `python/core/agent_orchestrator.py`
- Modify: `python/services/agent_service.py`
- Modify: `python/tests/test_agent_capabilities.py`
- Modify: `python/tests/test_agent_orchestrator.py`
- Modify: `python/tests/test_agent_service.py`

**Interfaces:**
- Produces: `Capability.display_name: str`
- Produces: `Capability.domain: str`
- Produces: `Capability.target_scope: str`
- Produces: `CapabilityRegistry.list_capabilities(*, available_only: bool = False) -> list[Json]`
- Consumes: Task 1 的 canonical 工具名还原。

- [ ] **Step 1: 写目录可用性和中文元数据失败测试**

```python
def test_model_catalog_contains_only_connected_capabilities(self):
    registry = CapabilityRegistry(
        internal_operations={"loom.connected": {"executor": lambda _payload: {"ok": True}}},
        skill_provider=lambda: [],
        mcp_provider=lambda: [],
        cli_catalog_provider=lambda: {"domains": []},
    )
    all_names = {item["name"] for item in registry.list_capabilities()}
    model_names = {item["name"] for item in registry.list_capabilities(available_only=True)}
    self.assertIn("loom.media.image.generate", all_names)
    self.assertNotIn("loom.media.image.generate", model_names)
    self.assertIn("loom.connected", model_names)

def test_builtin_capabilities_have_chinese_display_metadata(self):
    for item in CapabilityRegistry().list_capabilities():
        if item["source"] == "internal":
            self.assertTrue(item["displayName"])
            self.assertTrue(item["description"])
            self.assertTrue(item["domain"])
```

- [ ] **Step 2: 运行测试确认失败原因**

Run: `$env:PYTHONPATH='python'; python -m unittest discover -s python/tests -p "test_agent_capabilities.py" -v`

Expected: FAIL，当前 `Capability` 没有中文元数据，列表也不能过滤未连接执行器。

- [ ] **Step 3: 扩展能力数据结构和列表接口**

实现以下字段和过滤行为：

```python
@dataclass(frozen=True)
class Capability:
    name: str
    source: str
    permission: str
    risk: str
    timeout_sec: float
    input_schema: Json = field(default_factory=lambda: {"type": "object"})
    output_schema: Json = field(default_factory=lambda: {"type": "object"})
    display_name: str = ""
    description: str = ""
    domain: str = "general"
    target_scope: str = "none"
    executor: Executor | None = field(default=None, compare=False, repr=False)

    def to_dict(self) -> Json:
        return {
            "name": self.name,
            "displayName": self.display_name or _fallback_display_name(self.name),
            "description": self.description,
            "domain": self.domain,
            "targetScope": self.target_scope,
            "source": self.source,
            "permission": self.permission,
            "risk": self.risk,
            "timeoutSec": self.timeout_sec,
            "inputSchema": dict(self.input_schema),
            "outputSchema": dict(self.output_schema),
            "available": self.executor is not None,
        }

def list_capabilities(self, *, available_only: bool = False) -> list[Json]:
    capabilities = self._capabilities().values()
    if available_only:
        capabilities = [item for item in capabilities if item.executor is not None]
    return [item.to_dict() for item in capabilities]
```

- [ ] **Step 4: 只向模型注入可执行目录**

在 `AgentOrchestrator._build_request()` 中替换为：

```python
built["capabilities"] = self.capabilities.list_capabilities(available_only=True)
```

`AgentService.bootstrap()` 继续返回完整目录及 `available`，供界面状态和诊断使用。

- [ ] **Step 5: 运行目录、编排器和服务测试**

Run: `$env:PYTHONPATH='python'; python -m unittest discover -s python/tests -p "test_agent_capabilities.py" -v; python -m unittest discover -s python/tests -p "test_agent_orchestrator.py" -v; python -m unittest discover -s python/tests -p "test_agent_service.py" -v`

Expected: 三组测试全部通过，模型请求中不再含 `executor is None` 的空壳能力。

- [ ] **Step 6: 提交本任务**

```powershell
git add -- python/core/agent_capabilities.py python/core/agent_orchestrator.py python/services/agent_service.py python/tests/test_agent_capabilities.py python/tests/test_agent_orchestrator.py python/tests/test_agent_service.py
git commit -m "feat: expose only connected agent capabilities"
```

---

### Task 3: 连接图片与视频真实执行器

**Files:**
- Create: `python/services/agent_builtin_capabilities.py`
- Create: `python/tests/test_agent_builtin_capabilities.py`
- Modify: `python/services/agent_service.py`
- Modify: `python/core/agent_capabilities.py`
- Modify: `python/tests/test_creative_media_contract.py`

**Interfaces:**
- Produces: `AgentBuiltinCapabilityProvider.operations() -> dict[str, Json]`
- Produces: `loom.media.image.generate` 和 `loom.media.video.generate` 的已连接异步任务执行器。
- Reuses: `api.routes_media._image_generate_payload`、`_video_generate_payload`、`_compact_media_job_result`。

- [ ] **Step 1: 写媒体能力从空壳变为已连接的失败测试**

```python
def test_default_agent_service_connects_media_capabilities(self):
    service = AgentService(paths, runtime=UnavailableRuntime(), context_factory=lambda: fake_ctx, job_manager=fake_jobs)
    try:
        capabilities = {item["name"]: item for item in service.bootstrap()["capabilities"]}
        self.assertTrue(capabilities["loom.media.image.generate"]["available"])
        self.assertTrue(capabilities["loom.media.video.generate"]["available"])
    finally:
        service.shutdown()
```

- [ ] **Step 2: 运行测试确认当前媒体能力不可用**

Run: `$env:PYTHONPATH='python'; python -m unittest discover -s python/tests -p "test_agent_builtin_capabilities.py" -v`

Expected: FAIL，Bootstrap 中两个媒体能力的 `available` 为 `False`。

- [ ] **Step 3: 创建第一方能力适配器**

核心结构如下，图片和视频都通过现有 `JobManager` 返回稳定 `jobId`：

```python
class AgentBuiltinCapabilityProvider:
    def __init__(self, *, context_factory, job_manager, matrix_factory):
        self.context_factory = context_factory
        self.job_manager = job_manager
        self.matrix_factory = matrix_factory

    def operations(self) -> dict[str, Json]:
        return {
            "loom.media.image.generate": {
                "executor": lambda payload: self._submit_media("image", payload),
                "displayName": "生成图片",
                "description": "根据文字提示生成或编辑图片，并保存到麓鸣媒体库",
                "domain": "media",
                "permission": "control",
                "risk": "control_safe",
                "timeoutSec": 30,
            },
            "loom.media.video.generate": {
                "executor": lambda payload: self._submit_media("video", payload),
                "displayName": "生成视频",
                "description": "根据文字或参考图片提交视频生成任务，并保存到麓鸣媒体库",
                "domain": "media",
                "permission": "control",
                "risk": "control_safe",
                "timeoutSec": 30,
            },
        }
```

`_submit_media()` 必须先检查 `context_factory`、`job_manager` 和受保护功能状态，再调用现有 payload helper；返回值固定包含 `jobId`、`kind`、`status`，后台结果继续由现有媒体库逻辑落盘。

- [ ] **Step 4: 为媒体能力补齐结构化 Schema**

图片输入至少声明 `prompt`、`count`、`ratio`、`size`、`model`、`editImagePath`；视频输入至少声明 `prompt`、`model`、`duration`、`ratio`、`imagePath`。`prompt` 为必填字符串，数量限制沿用现有路由的 1-9 张。

- [ ] **Step 5: 注入 AgentService**

```python
self._builtin_capabilities = AgentBuiltinCapabilityProvider(
    context_factory=self.context_factory,
    job_manager=self.job_manager,
    matrix_factory=self._matrix_factory,
)
self.capabilities = capabilities or CapabilityRegistry(
    internal_operations={**self._internal_operations(), **self._builtin_capabilities.operations()},
    skill_provider=self._skill_service.list_skills,
    skill_executor=self._load_skill_instructions,
)
```

- [ ] **Step 6: 验证生图、编辑和视频任务调用**

Run: `$env:PYTHONPATH='python'; python -m unittest discover -s python/tests -p "test_agent_builtin_capabilities.py" -v; python -m unittest discover -s python/tests -p "test_creative_media_contract.py" -v`

Expected: 图片、图片编辑和视频均提交到真实媒体 helper，返回任务 ID，受保护功能不可用时返回稳定中文错误。

- [ ] **Step 7: 提交本任务**

```powershell
git add -- python/services/agent_builtin_capabilities.py python/services/agent_service.py python/core/agent_capabilities.py python/tests/test_agent_builtin_capabilities.py python/tests/test_creative_media_contract.py
git commit -m "feat: connect native agent media generation"
```

---

### Task 4: 统一手机与矩阵能力的范围绑定

**Files:**
- Modify: `python/loom_mcp.py`
- Modify: `python/loom_cli.py`
- Modify: `python/core/agent_capabilities.py`
- Modify: `python/core/agent_orchestrator.py`
- Modify: `python/tests/test_loom_mcp_contract.py`
- Modify: `python/tests/test_loom_cli_contract.py`
- Modify: `python/tests/test_agent_orchestrator.py`
- Modify: `python/tests/test_agent_matrix_integration.py`

**Interfaces:**
- Produces: `Capability.target_scope` 值 `none | single-device-read | single-device-write | matrix-write | campaign-write`。
- Produces: `AgentOrchestrator._bind_execution_scope(session_id, run_id, call, capability, checkpoint) -> Json`。
- Consumes: `checkpoint.requestScope.targets.deviceIds/groups`。

- [ ] **Step 1: 写跨来源手机范围失败测试**

```python
def test_single_phone_write_cannot_escape_request_scope(self):
    capability = registry.get("loom.mcp.loom.loom_phone_quick_task")
    self.assertEqual(capability.target_scope, "single-device-write")
    with self.assertRaisesRegex(PolicyViolationError, "phone_target_scope_required"):
        orchestrator._bind_execution_scope(session_id, run_id, {
            "toolCallId": "phone-write",
            "name": capability.name,
            "input": {"deviceId": "P99", "prompt": "打开应用"},
        }, capability, {"requestScope": {"targets": {"deviceIds": ["P01"]}}})
```

- [ ] **Step 2: 给第一方 MCP 与 CLI 声明目标策略**

MCP 定义增加 `targetScope`：手机截图/读取为 `single-device-read`，手机 quick task 为 `single-device-write`，矩阵 dispatch 为 `matrix-write`，取消/重试为 `campaign-write`。CLI 目录写入同名字段，注册表原样保留。

- [ ] **Step 3: 将范围绑定移动到能力解析之后**

```python
capability = self.capabilities.get(call["name"])
call = self._bind_execution_scope(session_id, run_id, call, capability, checkpoint)
decision = self.policy.evaluate(capability, call["input"])
```

`single-device-write` 必须有且只有一个已解析设备；`matrix-write` 继续使用确定的设备/组集合；`campaign-write` 只能操作当前运行已关联 campaign；读操作若声明了设备，则不能超出已解析范围。

- [ ] **Step 4: 保持单机与多机控制路径清晰**

单台手机控制可以调用 `loom_phone_quick_task`，多台手机必须调用 `loom.matrix.dispatch`。系统不把多设备目标偷偷截成第一台；遇到多设备调用单机工具时返回 `phone_single_target_required`，让模型改用矩阵。

- [ ] **Step 5: 运行 MCP、CLI、编排器和矩阵测试**

Run: `$env:PYTHONPATH='python'; python -m unittest discover -s python/tests -p "test_loom_mcp_contract.py" -v; python -m unittest discover -s python/tests -p "test_loom_cli_contract.py" -v; python -m unittest discover -s python/tests -p "test_agent_orchestrator.py" -v; python -m unittest discover -s python/tests -p "test_agent_matrix_integration.py" -v`

Expected: 单机读写和矩阵写入均受范围约束，原有审批、租约、取消、重试测试不回归。

- [ ] **Step 6: 提交本任务**

```powershell
git add -- python/loom_mcp.py python/loom_cli.py python/core/agent_capabilities.py python/core/agent_orchestrator.py python/tests/test_loom_mcp_contract.py python/tests/test_loom_cli_contract.py python/tests/test_agent_orchestrator.py python/tests/test_agent_matrix_integration.py
git commit -m "feat: bind phone tools to agent request scope"
```

---

### Task 5: 中文系统提示词与完整能力继承合同

**Files:**
- Create: `python/core/agent_system_prompt.py`
- Create: `python/tests/test_agent_capability_inheritance.py`
- Modify: `python/core/loom_model_client.py`
- Modify: `python/core/agent_capabilities.py`
- Modify: `python/tests/test_loom_model_client.py`
- Modify: `python/tests/test_native_agent_integration.py`

**Interfaces:**
- Produces: `build_agent_system_prompt(capabilities: list[Json]) -> str`
- Produces: `AGENT_SYSTEM_PROMPT_VERSION = "loom-native-agent.v2"`
- Consumes: Tasks 2-4 的可执行目录、中文元数据和目标策略。

- [ ] **Step 1: 写系统提示词与能力全集失败测试**

```python
def test_system_prompt_teaches_autonomous_capability_routing_in_chinese(self):
    prompt = build_agent_system_prompt(connected_capabilities)
    self.assertIn("麓鸣原生中枢智能体", prompt)
    self.assertIn("生成图片", prompt)
    self.assertIn("生成视频", prompt)
    self.assertIn("单台手机", prompt)
    self.assertIn("多台手机", prompt)
    self.assertNotIn("让用户勾选能力", prompt)

def test_every_connected_capability_is_injected_exactly_once(self):
    payload = build_chat_payload(profile, {"capabilities": connected_capabilities, "prompt": "生成海报"})
    tool_names = [item["function"]["name"] for item in payload["tools"]]
    self.assertEqual(len(tool_names), len(set(tool_names)))
    self.assertEqual(len(tool_names), len(connected_capabilities))
```

- [ ] **Step 2: 建立中文编排合同**

系统提示词必须明确：自行判断能力；状态查询优先只读；图片/视频使用媒体能力；单台手机与多台矩阵分流；工具失败后调整方案；不可编造工具；不向用户暴露内部 ID；任何提示词都无权放宽审批、范围和急停。

- [ ] **Step 3: 让模型 payload 使用动态系统提示词**

```python
capabilities = request.get("capabilities") if isinstance(request.get("capabilities"), list) else []
messages = [{"role": "system", "content": build_agent_system_prompt(capabilities)}]
```

工具仍通过结构化 `tools` Schema 注入，提示词只负责路由规则和中文行为，不把参数退化为自由文本命令。

- [ ] **Step 4: 建立完整继承一致性测试**

测试至少断言已连接目录包含并可执行：图片、视频、手机状态、手机截图、手机读取、手机 quick task、矩阵状态、矩阵分发、Skill、MCP、CLI；禁用 Skill、未连接空壳和缺失安全元数据的第三方工具按规则排除或失败关闭。

旧客户端发送的 `capabilityHints` 在一个兼容发布周期内继续被 API 接受，但编排器必须忽略该字段，不能据此缩小完整能力目录；新前端不再发送该字段。

- [ ] **Step 5: 运行模型、能力和集成测试**

Run: `$env:PYTHONPATH='python'; python -m unittest discover -s python/tests -p "test_agent_capability_inheritance.py" -v; python -m unittest discover -s python/tests -p "test_loom_model_client.py" -v; python -m unittest discover -s python/tests -p "test_native_agent_integration.py" -v`

Expected: 所有已连接能力恰好注入一次，模型能自动选择媒体和手机工具，普通回复使用简体中文。

- [ ] **Step 6: 提交本任务**

```powershell
git add -- python/core/agent_system_prompt.py python/core/loom_model_client.py python/core/agent_capabilities.py python/tests/test_agent_capability_inheritance.py python/tests/test_loom_model_client.py python/tests/test_native_agent_integration.py
git commit -m "feat: internalize loom capabilities in native agent"
```

---

### Task 6: 实现会话级模型路由

**Files:**
- Modify: `python/core/agent_sessions.py`
- Modify: `python/services/agent_service.py`
- Modify: `python/core/loom_model_client.py`
- Modify: `python/tests/test_agent_session_repository.py`
- Modify: `python/tests/test_agent_service.py`
- Modify: `python/tests/test_loom_model_client.py`
- Modify: `python/tests/contract_schemas/agent-session.v1.schema.json`
- Modify: `python/tests/contract_schemas/agent-run.v1.schema.json`

**Interfaces:**
- Produces: `AgentSession.modelId?: str`
- Produces: `AgentRun.modelId?: str` 和 `modelSource?: "session" | "account-default"`
- Produces: Bootstrap `models[]` 和 `defaultModelId`。
- Produces: `profile_from_session(session, *, model_id="") -> LoomModelProfile`。

- [ ] **Step 1: 写会话模型继承和验证失败测试**

```python
def test_session_model_is_snapshotted_into_run(self):
    session = service.create_session({"title": "招聘", "modelId": "qwen3.7-plus"})
    sent = service.send_message(session["sessionId"], {"clientMessageId": "m1", "text": "检查状态"})
    self.assertEqual(sent["run"]["modelId"], "qwen3.7-plus")
    self.assertEqual(sent["run"]["modelSource"], "session")

def test_rejects_model_not_in_current_account_text_models(self):
    with self.assertRaisesRegex(ValueError, "AGENT_MODEL_NOT_AVAILABLE"):
        service.update_session(session_id, {"modelId": "removed-model"})
```

- [ ] **Step 2: 扩展存储白名单和合同 Schema**

`create_session()` 接受 `model_id`；`update_session()` 的 allowed 集合增加 `modelId`；只保存模型名称，不保存 Provider、Token 或网关 URL。

- [ ] **Step 3: 从账号公开快照生成模型目录**

```python
account = self.account_manager.public_session() if self.account_manager else {}
text_models = list((account.get("models") or {}).get("text") or [])
default_model = str((account.get("selectedModels") or {}).get("text") or "")
```

Bootstrap 返回 `{modelId, name, available}`；服务端在创建、更新和发送前验证当前账号模型集合。

- [ ] **Step 4: 固化运行模型并覆盖模型网关 profile**

`LoomModelClient.complete()` 使用运行请求的 `modelId` 覆盖 `profile.model`，不调用 `select_models()`；正在运行的请求不受会话后续切换影响。

- [ ] **Step 5: 运行存储、服务和网关测试**

Run: `$env:PYTHONPATH='python'; python -m unittest discover -s python/tests -p "test_agent_session_repository.py" -v; python -m unittest discover -s python/tests -p "test_agent_service.py" -v; python -m unittest discover -s python/tests -p "test_loom_model_client.py" -v`

Expected: 会话级选择持久化、运行快照稳定、无效模型被拒绝、全局默认不被隐式修改。

- [ ] **Step 6: 提交本任务**

```powershell
git add -- python/core/agent_sessions.py python/services/agent_service.py python/core/loom_model_client.py python/tests/test_agent_session_repository.py python/tests/test_agent_service.py python/tests/test_loom_model_client.py python/tests/contract_schemas/agent-session.v1.schema.json python/tests/contract_schemas/agent-run.v1.schema.json
git commit -m "feat: add conversation model routing"
```

---

### Task 7: 实现自动设备范围解析

**Files:**
- Create: `python/core/agent_scope.py`
- Create: `python/tests/test_agent_scope.py`
- Modify: `python/services/agent_service.py`
- Modify: `python/core/agent_orchestrator.py`
- Modify: `python/tests/test_agent_service.py`
- Modify: `python/tests/test_agent_matrix_integration.py`

**Interfaces:**
- Produces: `resolve_request_scope(text, explicit_scope, matrix_status) -> ScopeResolution`
- Produces: `ScopeResolution.status: "not_required" | "resolved" | "ambiguous"`
- Produces: 请求字段 `scopeMode: "auto" | "manual"` 和 `requestScope`。

- [ ] **Step 1: 写确定性范围解析失败测试**

```python
def test_resolves_explicit_device_group_against_matrix_facts(self):
    result = resolve_request_scope("让招聘一组筛选简历", {"mode": "auto"}, matrix_status)
    self.assertEqual(result.status, "resolved")
    self.assertEqual(result.groups, ["招聘一组"])

def test_ambiguous_phone_reference_does_not_dispatch(self):
    result = resolve_request_scope("让那几台手机继续", {"mode": "auto"}, matrix_status)
    self.assertEqual(result.status, "ambiguous")
    self.assertEqual(result.device_ids, [])
```

- [ ] **Step 2: 实现事实约束解析器**

解析器只匹配真实设备 ID、真实设备组和明确的“全部在线”表达。普通问答返回 `not_required`；多匹配、指代不明和不存在目标返回 `ambiguous`，不得猜测设备。

- [ ] **Step 3: 在发送时固化 requestScope**

手动范围直接验证并固化；自动范围读取 `MatrixControlPlane.status()` 后解析。`allOnline` 只有用户明确表达或手动选择时为真。

- [ ] **Step 4: 为模糊范围生成澄清而非工具错误**

运行请求增加安全的范围摘要和澄清指令；当用户请求明显涉及手机写操作但范围为 `ambiguous` 时，模型只能返回一次简短澄清，不创建 TaskGrant 或矩阵 campaign。

- [ ] **Step 5: 运行范围、服务和矩阵测试**

Run: `$env:PYTHONPATH='python'; python -m unittest discover -s python/tests -p "test_agent_scope.py" -v; python -m unittest discover -s python/tests -p "test_agent_service.py" -v; python -m unittest discover -s python/tests -p "test_agent_matrix_integration.py" -v`

Expected: 设备、组、全部在线、普通问答、无匹配和多匹配场景全部通过，模型工具参数只能缩小范围。

- [ ] **Step 6: 提交本任务**

```powershell
git add -- python/core/agent_scope.py python/services/agent_service.py python/core/agent_orchestrator.py python/tests/test_agent_scope.py python/tests/test_agent_service.py python/tests/test_agent_matrix_integration.py
git commit -m "feat: resolve native agent phone scope"
```

---

### Task 8: 重构输入区、模型菜单和执行范围

**Files:**
- Modify: `package.json`
- Modify: `package-lock.json`
- Create: `src/components/agent/AgentModelMenu.tsx`
- Create: `src/components/agent/AgentScopeMenu.tsx`
- Modify: `src/components/agent/AgentComposer.tsx`
- Modify: `src/components/agent/AgentWorkbenchPage.tsx`
- Modify: `src/types/agent.ts`
- Modify: `src/stores/agentStore.ts`
- Modify: `src/stores/agentStore.test.ts`
- Modify: `src/services/api.ts`
- Modify: `src/components/agent/agentFrontendIntegrity.test.ts`

**Interfaces:**
- Produces: `AgentDraft.scopeMode` 和 `AgentDraft.scope`。
- Produces: `AgentModelMenu` 的会话切换、设为默认、管理模型命令。
- Consumes: Task 6 Bootstrap 模型目录和 Task 7 范围协议。

- [ ] **Step 1: 安装统一图标库**

Run: `npm install lucide-react`

Expected: `package.json` 和 `package-lock.json` 增加 `lucide-react`，不改变 React 主版本。

- [ ] **Step 2: 写前端合同失败断言**

断言 Composer 不再包含“设备”“设备组”“能力”常驻字段和 `capabilityHints`，并包含模型菜单、范围入口、附件图标、发送/停止图标；所有按钮有真实 `onClick`、`aria-label` 和 disabled 状态。

- [ ] **Step 3: 扩展 TypeScript 协议**

```ts
export interface AgentModelSummary {
  modelId: string;
  name: string;
  available: boolean;
}

export interface AgentScopeSelection {
  mode: 'auto' | 'manual';
  deviceIds: string[];
  groups: string[];
  allOnline: boolean;
}
```

`AgentSession`/`AgentRun` 增加模型字段，Bootstrap 增加 `models`/`defaultModelId`，发送请求删除 `capabilityHints` 并增加 `scopeMode`/`scope`。

- [ ] **Step 4: 实现紧凑模型菜单**

菜单列出真实文本模型，点击后调用 `agentApi.updateSession(sessionId, {modelId})`；“设为麓鸣默认模型”单独调用 `accountApi.selectModels({textModel: modelId})`；“管理模型”跳转现有模型页面。正在运行的请求只更新下一条消息。

- [ ] **Step 5: 实现执行范围渐进披露**

默认按钮显示“自动范围”。展开后提供自动、全部在线、真实设备组和可搜索设备；手动选择写入草稿，关闭菜单不丢失。普通问答无需选择范围。

- [ ] **Step 6: 重构 Composer**

布局固定为“附件、范围、模型、发送/停止”，最大宽度与对话正文一致。附件、范围、模型均使用图标或图标+短文本；发送使用 `ArrowUp`，运行中使用 `Square`。输入框保持稳定最小/最大高度，`Enter` 发送，`Shift+Enter` 换行。

- [ ] **Step 7: 运行 TypeScript 与平台合同测试**

Run: `npm run test:platform-contracts`

Expected: 类型检查和 Agent 前端合同全部通过，普通输入区不再出现英文能力列表。

- [ ] **Step 8: 提交本任务**

```powershell
git add -- package.json package-lock.json src/components/agent/AgentModelMenu.tsx src/components/agent/AgentScopeMenu.tsx src/components/agent/AgentComposer.tsx src/components/agent/AgentWorkbenchPage.tsx src/types/agent.ts src/stores/agentStore.ts src/stores/agentStore.test.ts src/services/api.ts src/components/agent/agentFrontendIntegrity.test.ts
git commit -m "feat: rebuild native agent composer"
```

---

### Task 9: 添加思考反馈并清理页头和调试入口

**Files:**
- Create: `src/components/agent/AgentThinkingIndicator.tsx`
- Modify: `src/components/agent/AgentHeader.tsx`
- Modify: `src/components/agent/AgentDebugger.tsx`
- Modify: `src/components/agent/AgentRunAttachment.tsx`
- Modify: `src/components/agent/ConversationStream.tsx`
- Modify: `src/components/agent/messageBlocks.tsx`
- Modify: `src/components/agent/AgentWorkbenchPage.tsx`
- Modify: `src/components/agent/agentViewModel.ts`
- Modify: `src/components/agent/agentViewModel.test.ts`
- Modify: `src/components/agent/agentFrontendIntegrity.test.ts`
- Modify: `tests/e2e/agent-matrix-production.spec.ts`

**Interfaces:**
- Produces: `shouldShowThinking(messages, run, sending) -> boolean`。
- Produces: `AgentThinkingIndicator`，带 `role="status"` 和 `aria-live="polite"`。
- Produces: 每个运行附件中的“运行详情”入口。

- [ ] **Step 1: 写思考状态纯函数测试**

```ts
assert.equal(shouldShowThinking([userMessage], null, true), true);
assert.equal(shouldShowThinking([userMessage], queuedRun, false), true);
assert.equal(shouldShowThinking([userMessage, assistantDelta], runningRun, false), false);
assert.equal(shouldShowThinking([userMessage], failedRun, false), false);
assert.equal(shouldShowThinking([userMessage], cancelledRun, false), false);
```

- [ ] **Step 2: 实现稳定的三点思考状态**

三个圆点只动画 `opacity` 和 `transform`，状态行预留高度；`motion-reduce:animate-none` 关闭循环动画。读屏文本为“麓鸣正在思考”，圆点本身 `aria-hidden="true"`。

- [ ] **Step 3: 删除页头双按钮及其属性**

`AgentHeaderProps` 删除 `debuggerOpen`、`onToggleDebugger`、`onNewSession`；页头只显示身份、连接状态和模型摘要。更新完整性测试，明确断言 Header 不含 `</>` 和“新对话”。

- [ ] **Step 4: 下沉运行详情入口并修复透明面板**

运行附件提供“运行详情”，调用 `setDebuggerOpen(true)` 并选择对应运行。`AgentDebugger` 根节点背景改为 `bg-surface`，禁止 `/95`；添加 `Escape` 关闭和焦点返回。没有运行时不显示入口。

普通消息块把工具调用映射为“正在生成图片”“正在提交视频任务”“正在读取手机屏幕”“正在分发矩阵任务”等中文动作；同一运行的重复协议错误聚合为一个可恢复错误。canonical ID、别名、模型快照、范围证据和脱敏原始错误只在运行详情显示。

- [ ] **Step 5: 更新端到端交互**

Playwright 先点击运行附件中的“运行详情”，再断言不透明调试面板可见；断言页头双按钮不存在、左侧 `+` 能创建对话、慢响应时思考状态出现并在首个事件后消失。

- [ ] **Step 6: 运行前端合同和 Agent E2E**

Run: `npm run test:platform-contracts; npx playwright test tests/e2e/agent-matrix-production.spec.ts`

Expected: 思考状态生命周期、唯一新建入口、运行详情和不透明调试面板全部通过。

- [ ] **Step 7: 提交本任务**

```powershell
git add -- src/components/agent/AgentThinkingIndicator.tsx src/components/agent/AgentHeader.tsx src/components/agent/AgentDebugger.tsx src/components/agent/AgentRunAttachment.tsx src/components/agent/ConversationStream.tsx src/components/agent/messageBlocks.tsx src/components/agent/AgentWorkbenchPage.tsx src/components/agent/agentViewModel.ts src/components/agent/agentViewModel.test.ts src/components/agent/agentFrontendIntegrity.test.ts tests/e2e/agent-matrix-production.spec.ts
git commit -m "feat: refine native agent response experience"
```

---

### Task 10: 全能力闭环、视觉审查与受保护安装包验收

**Files:**
- Create: `python/tests/test_native_agent_full_capability_e2e.py`
- Modify: `python/tests/test_protected_release_contract.py`
- Modify: `python/tests/test_nsis_smoke_script_contract.py`
- Modify: `scripts/smoke-test-tauri-nsis.ps1`
- Modify: `tests/e2e/agent-matrix-production.spec.ts`
- Create: `docs/release-notes/2.1.90.md`

**Interfaces:**
- Consumes: Tasks 1-9 的模型、能力、范围、UI 和运行详情合同。
- Produces: 可复现的图片、视频、单机手机和多机矩阵验收证据。

- [ ] **Step 1: 写完整能力闭环测试**

用脚本模型依次请求并验证：状态读取、图片生成、图片编辑、视频生成、手机截图、手机读取、单机 quick task、矩阵 dispatch。每次调用都断言 canonical ID、已连接执行器、中文显示名、结构化输入、Policy 决策和最终结果。

- [ ] **Step 2: 运行 Python 定向回归**

Run: `$env:PYTHONPATH='python'; python -m unittest discover -s python/tests -p "test_agent*.py" -v; python -m unittest discover -s python/tests -p "test_native_agent*.py" -v; python -m unittest discover -s python/tests -p "test_creative_media_contract.py" -v; python -m unittest discover -s python/tests -p "test_routes_phone.py" -v; python -m unittest discover -s python/tests -p "test_routes_matrix.py" -v`

Expected: 全部通过，没有 `capability_not_found`、空壳能力注入或范围扩大。

- [ ] **Step 3: 运行全部前端测试和构建**

Run: `npm run test:platform-contracts; npm run build; npx playwright test tests/e2e/agent-matrix-production.spec.ts`

Expected: TypeScript、Vite 构建和 Agent E2E 全绿。

- [ ] **Step 4: 执行三档视觉截图审查**

使用 Playwright 在 `1600x1000`、`1280x800`、`1100x720` 截图。检查页头无重复按钮、输入区不重叠、模型长名称截断、思考状态稳定、调试面板不透底、中文能力结果可读。发现重叠或正文透入时先修复再重跑截图。

- [ ] **Step 5: 构建并冒烟受保护 NSIS 包**

Run: `npm run package:protected:nsis`

Expected: staging、保护合同、Rust/Tauri 和 NSIS 全部成功。

Run: `$installer = Get-ChildItem -LiteralPath 'src-tauri\target\release\bundle\nsis' -Filter '*.exe' | Sort-Object LastWriteTime -Descending | Select-Object -First 1; powershell -NoProfile -ExecutionPolicy Bypass -File ..\scripts\smoke-test-tauri-nsis.ps1 -InstallerPath $installer.FullName`

Expected: 安装后 Bootstrap 报告原生 Agent 在线，图片、视频、手机和矩阵核心能力均为 `available: true`，真实工具调用不再出现能力名映射错误。

- [ ] **Step 6: 写更新日志**

`docs/release-notes/2.1.90.md` 必须列出：完整能力自动继承、生图/视频/手机闭环、会话模型切换、自动范围、新 Composer、思考动画、页头清理、调试面板修复和兼容性说明。

- [ ] **Step 7: 提交验收和发布合同**

```powershell
git add -- python/tests/test_native_agent_full_capability_e2e.py python/tests/test_protected_release_contract.py python/tests/test_nsis_smoke_script_contract.py scripts/smoke-test-tauri-nsis.ps1 tests/e2e/agent-matrix-production.spec.ts docs/release-notes/2.1.90.md
git commit -m "test: verify full native agent capability release"
```

---

## Dependency And Parallelism Map

- Task 1 和 Task 6 可以并行；二者都修改 `loom_model_client.py`，合并时先落 Task 1，再把 Task 6 的模型覆盖重放到最新文件。
- Task 2 完成后，Task 3、Task 4 可以并行。
- Task 5 依赖 Tasks 1-4。
- Task 7 依赖 Task 4 的统一范围绑定。
- Task 8 依赖 Task 6/7 的 API 类型，但可先完成纯组件和 Store 测试。
- Task 9 可与 Tasks 3-7 并行，最终在 Task 8 后合并 Composer/Workbench 交叉修改。
- Task 10 必须在 Tasks 1-9 全部合并后执行。

## Final Verification Commands

```powershell
Set-Location D:\Axiangmu\LOOM-Workspace\worktrees\platform\18-stability-spine\openclaw_new_launcher
$env:PYTHONPATH='python'
python -m unittest discover -s python/tests -v
npm run test:platform-contracts
npm run build
npx playwright test tests/e2e/agent-matrix-production.spec.ts
```

全部命令通过后才能构建 `2.1.90` 受保护安装包；任何媒体、手机或矩阵能力显示 `available: false` 都视为发布阻断。
