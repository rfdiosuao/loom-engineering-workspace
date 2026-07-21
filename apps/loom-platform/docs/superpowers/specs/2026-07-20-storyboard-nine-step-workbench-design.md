# 全案九步创作工作台 · 设计方案

- 日期：2026-07-20
- 分支：`codex/18-stability-spine`
- 范围：在「创作」栏新增「全案九步」工作台，把产品定位 → 风格 → 全案 → 文案 → 分镜 → 人物/产品/场景图 → 视频提示词的全流程结构化、智能化；设置页提供 `全案九步_参数配置.json` 导入接口。
- 参考材料：`视频生成.docx`（模块一~十字段定义）、`video-generation-ui.html`（视觉原型）、`全案九步_参数配置.json`（选项参数结构）。

## 1. 已锁定的关键决策

| # | 决策 | 选择 |
|---|---|---|
| 1 | 文案/分镜等文本生成模型来源 | 复用托管网关 `LoomModelClient`（模型账号页登录） |
| 2 | 人物/产品/场景图生图复用方式 | 直接复用创作页 `imageApi`（同份配置 + 媒体库 + 手机传送） |
| 3 | 模块九 / 模块十范围 | 模块九做「视频提示词」并可选用 `videoApi` 生成；模块十本次不做，留占位 |
| 4 | 九步入口位置 | 创作栏顶部新增第三个 tab「全案九步」 |
| 5 | 中间产物持久化 | 完整保存项目到 `data/.openclaw/storyboard/projects/{projectId}.json` |
| 6 | 导入 JSON 空值处理 | 空值由后端 `DEFAULT_OPTION_HINTS` 兜底成内置默认系统提示词 |
| 7 | 上下文组装方式 | 拼接所有用户选中项及其提示词（含模块一/二/三）成上下文 |

## 2. 总体架构

复用现有「前端 → Tauri `invoke('proxy_request')` → Rust → Python Bridge」链路，新增一个垂直功能域 `storyboard`。**不新建**生图/视频通道、文本模型通道、Job 机制、媒体库；只做「选项组装上下文 → 调 LLM 出文本产物 → 提取提示词 → 复用 imageApi/videoApi」。

```
创作栏顶部「全案九步」tab
   └─ StoryboardWorkbench.tsx（向导：目标对象 → 九步）
        ├─ configApi.read/write  → data/.openclaw/storyboard/projects/*.json + param-config.json
        ├─ storyboardApi.*       → /api/storyboard/*
        │     ├─ GET  /param-config         读取已兜底的参数结构
        │     ├─ POST /import-param-config   设置页导入 JSON（写入 param-config.json）
        │     ├─ POST /generate              stage=script|storyboard|videoPrompt → LoomModelClient
        │     └─ （素材提取在前端基于分镜结构完成，不走后端）
        └─ imageApi.submit / videoApi.submit → 复用创作页生图/视频链路
```

## 3. 数据模型

### 3.1 参数配置 `data/.openclaw/storyboard/param-config.json`

保留用户导入 JSON 的原始结构：`模块X → 类目 → 选项 → 字符串|null`。

- 导入时空值保持 `null`（不篡改用户文件）。
- 前端读取走 `GET /param-config`，后端在响应里对每个 `null` 用 `DEFAULT_OPTION_HINTS` 兜底返回完整字符串，前端永远拿到「选项 → 非空提示词」。
- `DEFAULT_OPTION_HINTS` 是后端内置的中文提示词模板字典，键为 `"{模块}\u0000{类目}\u0000{选项}"`，覆盖 docx/JSON 里全部选项；未命中时回退通用模板「当选择「{选项}」时，请在文案中体现该方向的核心特征」。

### 3.2 项目 `data/.openclaw/storyboard/projects/{projectId}.json`

```jsonc
{
  "projectId": "sb_<uuid8hex>",
  "title": "冷萃咖啡液 · 30秒种草",
  "createdAt": "2026-07-20T10:00:00Z",
  "updatedAt": "2026-07-20T10:30:00Z",

  "target": {                       // 需求一：目标对象（中心点）
    "category": "食品饮料",
    "object": "专为上班族设计的3秒冷萃咖啡液"
  },

  "selections": {                   // 各模块用户选中的选项；类目→选项数组
    "模块一": { "产品/服务类型": ["实物商品"], "所属品类": ["食品饮料"], "核心卖点（多选）": ["品质用料","效果功效"], "...": [...] },
    "模块二": { "内容大类": ["种草测评类"], "人设语气": ["亲切邻家"], "...": [...] },
    "模块三": { "可勾选生成的全案板块": ["选题库","变现漏斗"], "全案激进度": ["平衡"], "...": [...] },
    "模块四": { "视频类型": ["种草测评"], "视频时长": ["30 秒"], "开头钩子": ["痛点式"], "文案结构": ["黄金3秒+痛点+方案+案例+引导"], "转化动作 CTA": ["点购物车","关注"], "卖点融入": [true] },
    "模块五": { "分镜颗粒度": ["中（6–10 镜）"], "拍摄/成片方式": ["AI 生成画面"], "节奏卡点": ["中速"], "特效风格": ["简约"], "运镜偏好": ["含基础运镜"], "字幕与音效": ["生成逐镜字幕"] },
    "模块六": { "性别": ["女"], "年龄段": ["25–30"], "气质风格": ["亲和邻家"], "...": [...] },
    "模块七": { "出图类型": ["场景实拍感"], "视觉风格": ["电商精致"], "画幅比例": ["9:16"], "...": [...] },
    "模块八": { "场景类型": ["厨房"], "光线氛围": ["明亮通透"], "画幅": ["9:16"], "...": [...] },
    "模块九": { "成片方式": ["AI 视频生成"], "配音音色": ["女声（甜美）"], "语速": ["正常"], "字幕样式": ["简约白字"], "背景音乐": ["热门卡点"], "转场特效": ["简约"], "画幅": ["9:16"], "片头尾": ["无"] }
  },

  "script": {                       // 模块四产物（需求三：可改可存）
    "content": "（完整口播文案）",
    "versions": [ { "content": "...", "savedAt": "..." } ],
    "generatedAt": "2026-07-20T10:05:00Z",
    "rewrittenAt": null
  },

  "storyboard": {                   // 模块五产物（需求三：自动同步文案；需求四：自动提取素材）
    "shots": [
      { "num": 1, "time": "0–3s", "scene": "...", "voice": "...", "subtitle": "...", "effect": "...", "shotType": "特写", "camera": "固定", "transition": "硬切", "bgm": "...", "assetType": "产品图", "shootTip": "..." }
    ],
    "generatedAt": "2026-07-20T10:10:00Z"
  },

  "assetPrompts": {                 // 需求四：从分镜自动分类出的提示词
    "人物图": [ "镜头1：25-30岁亲和邻家气质女性，手持咖啡杯，明亮厨房背景，9:16..." ],
    "产品图": [ "镜头1：冷萃咖啡液产品特写，撕开注入冰水瞬间，水花，电商精致风格，9:16..." ],
    "场景图": [ "镜头1：明亮通透的现代厨房，自然日光，9:16..." ]
  },

  "generatedAssets": [              // 模块六/七/八产物（引用媒体库）
    { "shotNum": 1, "kind": "产品图", "mediaId": "...", "path": "...", "createdAt": "..." }
  ],

  "videoPrompt": {                  // 模块九产物
    "content": "（组装好的视频生成提示词）",
    "generatedAt": "2026-07-20T10:20:00Z"
  }
}
```

项目列表/CRUD 通过 `configApi` 实现（路径已在 `data` 允许范围内）；项目索引文件 `projects/index.json` 存 `[{projectId, title, updatedAt}]` 便于侧边栏加载。

## 4. 模块职责与生成边界

严格对齐需求一~四：

| 模块 | 输入 | 生成接口 | 产物 |
|---|---|---|---|
| 目标对象（需求一） | 品类下拉 + 对象名称文本框 | 无 | `target` |
| 一·定位 / 二·风格 / 三·全案 | 类目选项 | **无**（需求二：仅作模块四上下文） | `selections` |
| 四·文案 | 视频类型/时长/钩子/结构/CTA/卖点融入 | **有** → `/generate stage=script` | `script.content`（可编辑保存，需求三） |
| 五·分镜 | 颗粒度/成片方式/节奏/特效/运镜/字幕 | **有** → `/generate stage=storyboard`（自动注入 script，需求三） | `storyboard.shots` + `assetPrompts`（需求四自动分类） |
| 六·人物图 / 七·产品图 / 八·场景图 | 各自类目选项 + 参考图（选填） | **有** → 复用 `imageApi.submit` | `generatedAssets`（落媒体库） |
| 九·视频提示词 | 成片方式/配音/字幕/BGM/画幅/片头尾 | **有** → `/generate stage=videoPrompt` + 可选 `videoApi.submit` | `videoPrompt.content`（+可选视频） |
| 十·发布 | — | **本次不做**，占位 | — |

## 5. 上下文组装（核心）

新增 `python/services/storyboard.py`，纯函数 `build_context(stage, project, param_config)`：

```python
def build_context(stage, project, param_config) -> tuple[str, str]:
    """返回 (system_prompt, user_prompt)。"""
    parts = []

    # 1. 目标对象（需求一：中心点）
    target = project.get("target", {})
    parts.append(f"【目标对象】\n品类：{target.get('category','')}\n对象：{target.get('object','')}")

    # 2. 模块一/二/三 所有选中项（需求二：作为模块四上下文）
    context_modules = ["模块一", "模块二", "模块三"]
    if stage == "storyboard":
        context_modules += ["模块四"]            # 分镜需要文案参数
    if stage == "videoPrompt":
        context_modules += ["模块四", "模块五"]   # 视频提示词需要文案+分镜

    for mod in context_modules:
        for category, opts in project.get("selections", {}).get(mod, {}).items():
            for opt in opts:
                hint = resolve_hint(param_config, mod, category, opt)  # null → DEFAULT_OPTION_HINTS
                parts.append(f"【{mod} · {category} · {opt}】\n{hint}")

    # 3. stage 专属指令 + 已生成的上游产物
    if stage == "script":
        system = SCRIPT_SYSTEM_TEMPLATE      # 「你是短视频文案专家，按上下文产出可直接口播的文案…」
        user = "\n\n".join(parts) + f"\n\n请按以上设定产出完整口播/剧情文案。"
    elif stage == "storyboard":
        script = project.get("script", {}).get("content", "")
        system = STORYBOARD_SYSTEM_TEMPLATE
        user = "\n\n".join(parts) + f"\n\n【定稿文案】\n{script}\n\n请逐镜拆解为分镜脚本，JSON 数组。"
    elif stage == "videoPrompt":
        script = project.get("script", {}).get("content", "")
        shots = project.get("storyboard", {}).get("shots", [])
        system = VIDEO_PROMPT_SYSTEM_TEMPLATE
        user = "\n\n".join(parts) + f"\n\n【文案】\n{script}\n\n【分镜】\n{json.dumps(shots, ensure_ascii=False)}\n\n请产出可直接用于视频生成的提示词。"

    return system, user
```

`resolve_hint(param_config, mod, category, opt)`：查 `param_config[mod][category][opt]`，为字符串且非空则返回；否则查 `DEFAULT_OPTION_HINTS`；最后回退通用模板。

调用：通过 `ctx.get_agent_service().model_client.complete({ "prompt": user, "history": [], "capabilities": [] }, emit=lambda _: None, cancel=threading.Event())` 拿 `result["text"]`。`build_chat_payload` 已自动注入 system（用我们的 system 覆盖默认 agent system 的方式见下）。

> 注：`build_chat_payload` 默认用 `build_agent_system_prompt([])`。我们通过传一个名为 `systemOverride` 的字段（在 `build_chat_payload` 里识别并替换）来注入九步专属 system prompt；这是一个对 `loom_model_client.py` 的小增强，保持后向兼容。

## 6. 后端新增

### 6.1 `python/core/paths.py`
新增：
```python
@property
def storyboard_dir(self) -> str:
    return os.path.join(self.state_dir, "storyboard")

@property
def storyboard_param_config(self) -> str:
    return os.path.join(self.storyboard_dir, "param-config.json")

@property
def storyboard_projects_dir(self) -> str:
    return os.path.join(self.storyboard_dir, "projects")

@property
def storyboard_projects_index(self) -> str:
    return os.path.join(self.storyboard_projects_dir, "index.json")
```

### 6.2 `python/services/storyboard.py`
- `DEFAULT_OPTION_HINTS: dict[str, str]` — 内置默认提示词（覆盖全部选项，键 `"{mod}\u0000{category}\u0000{opt}"`）
- `SCRIPT_SYSTEM_TEMPLATE / STORYBOARD_SYSTEM_TEMPLATE / VIDEO_PROMPT_SYSTEM_TEMPLATE` — 三套 system prompt
- `class StoryboardService`:
  - `__init__(self, paths)` 读 `param-config.json`
  - `get_param_config() -> dict` 返回兜底后的完整结构
  - `import_param_config(payload: dict) -> dict` 校验 + 保存原始（保留 null）+ 返回兜底结果与统计 `{ok, optionCount, updatedAt}`
  - `build_context(stage, project) -> tuple[str, str]`
  - `generate(stage, project, model_client) -> dict` 组装上下文 → 调 `model_client.complete()` → 文本后处理（分镜要求 JSON，做容错解析）→ 返回 `{stage, result, rawText}`
- 纯函数 `extract_asset_prompts(shots: list) -> dict`：从分镜的 `assetType`/`scene` 字段把每个镜头归到 `人物图/产品图/场景图`，并拼上对应模块（六/七/八）用户选中的风格参数 → 返回三类提示词数组。**此函数在前端也有一份镜像实现**（用于即时预览），后端版本仅在 `generate(stage=storyboard)` 后写回项目时调用。

校验规则（`import_param_config`）：
- 顶层必须包含 `模块一`~`模块九` 至少（`模块十` 可选）
- 每个模块是「类目 → 选项 → 字符串|null」三层
- 缺失的模块/类目记入 `warnings`，不阻断导入

### 6.3 `python/api/routes_storyboard.py`
```python
def register_storyboard_routes(app, ctx) -> None:
    @app.get("/api/storyboard/param-config")
    async def get_param_config(request): ...          # 返回 {config: <兜底后>, importedAt, optionCount}

    @app.post("/api/storyboard/import-param-config")
    async def import_param_config(request): ...       # body={config} → 写文件 + 返回兜底结果

    @app.post("/api/storyboard/generate")
    async def generate(request): ...                  # body={stage, project} → 受 license 保护 → 调 service.generate
```
- `GET` 走 `ctx.auth_error`；`POST /generate` 路径加入 `commercial_feature_denial` 保护：在 `core/feature_access.py` 的 `FEATURE_PATH_RULES` 里新增 `("/api/storyboard/generate", "matrix.devices")`（与 `/api/agent` 同一 feature，二者都是 LLM 文本生成）。生图本身已由 `/api/image/generate` → `image` feature 保护，无需重复。
- 在 `python/api/fastapi_routes.py` 的 `register_fastapi_routes` 里 `register_storyboard_routes(app, ctx)`。
- 在 `python/bridge.py` 的 `_build_fastapi_context()` 加 `get_storyboard_svc=_get_storyboard_svc` + 新增 `_get_storyboard_svc()` 单例 getter（仿 `_get_image_client`）。

### 6.4 `loom_model_client.py` 增强
`build_chat_payload` 识别 `request.get("systemOverride")`：若为非空字符串，用它替换默认 system message。其余行为不变。约 3 行改动。

## 7. 前端新增

### 7.1 目录结构 `src/components/storyboard/`
```
storyboard/
├── StoryboardWorkbench.tsx          // 顶层：项目侧边栏 + 目标对象 + 步骤条 + 当前步骤面板
├── StoryboardProjectsSidebar.tsx    // 项目列表（新建/切换/重命名/删除）
├── StoryboardOptionGroups.tsx       // 通用「类目→选项」渲染器（tag/dropdown/radio/toggle/contentTypes）
├── StoryboardScriptPanel.tsx        // 模块四：生成按钮 + 可编辑 textarea + 保存
├── StoryboardShotsPanel.tsx         // 模块五：分镜表 + 自动提取的素材提示词卡片
├── StoryboardAssetPanel.tsx         // 模块六/七/八共用：风格选项 + 参考图 + imageApi 提交 + 结果网格
├── StoryboardVideoPanel.tsx         // 模块九：成片配置 + 生成提示词 + 可选 videoApi 生成
├── storyboardSteps.ts               // 九步元数据（单一数据源，结构对齐 HTML 原型 steps[]）
└── storyboardTypes.ts               // TS 类型（StoryboardProject / Selections / Shot / ParamConfig）
```

### 7.2 `src/services/storyboardApi.ts`
```ts
export const storyboardApi = {
  getParamConfig: (): Promise<{config, importedAt?, optionCount?}> => api('/api/storyboard/param-config'),
  importParamConfig: (config: unknown): Promise<{config, optionCount, warnings?}> => api('/api/storyboard/import-param-config', 'POST', { config }),
  generate: (params: {stage: 'script'|'storyboard'|'videoPrompt', project: StoryboardProject}): Promise<{stage, result, rawText}> => api('/api/storyboard/generate', 'POST', params),
};
```

### 7.3 `CreativeMediaPage.tsx` 改造
- 顶部 tab 从 2 个变 3 个：`生图 / 生视频 / 全案九步`
- tab === 'storyboard' 时懒加载 `<StoryboardWorkbench />`
- 九步用的生图/视频配置直接复用本页已有的 `config`（imageBaseUrl/imageApiKey/...），不重复

### 7.4 `SettingsPage.tsx` 改造
「数据」tab 新增一行 `SettingRow`「全案九步参数配置」：
- 说明文字：「导入 `全案九步_参数配置.json`，每个选项对应一条系统提示词，用于组合九步生成的上下文。」
- 「导入 JSON」按钮 → 隐藏 `<input type="file" accept=".json">` → 读文件 `JSON.parse` → `storyboardApi.importParamConfig` → toast 结果（选项数 / 缺失项）
- 显示已导入状态（`importedAt` / `optionCount`），无则显示「未导入」

### 7.5 九步步骤条交互
- 步骤条数据来自 `storyboardSteps.ts`（id/label/icon/goal/subTabs/sections）
- 点击步骤切换面板；步骤完成状态由项目数据推导（如模块四完成 = `script.content` 非空）
- 模块一/二/三面板无生成按钮（需求二）；模块四/五/九面板有「生成」按钮

### 7.6 生图复用（模块六/七/八）
点「生成 {人物图/产品图/场景图}」：
1. 取 `assetPrompts[该类]` 的提示词（来自分镜，需求四）+ 当前模块选中风格参数 → 拼成最终 prompt
2. `imageApi.submit({ baseUrl, apiKey, model, size, prompt, editImagePath?, source:'storyboard' })`（参数从 `mediaApi.config()` 取）
3. 复用创作页 `pollJob` 模式轮询；完成后写 `generatedAssets`，素材落媒体库（`source:'storyboard'`）
4. 参考图复用 `ReferenceImagePicker`

## 8. 错误处理与边界

- **未登录模型账号**：`LoomModelClient` 抛 `AGENT_ACCOUNT_LOGIN_REQUIRED` → `routes_storyboard` 捕获 → 返回 `{error: '请先在「模型账号」页登录', code}` → 前端 toast + 跳转按钮
- **生图未配置**：检查 `config.image.hasApiKey`，未配置则提示去创作页配置
- **分镜 JSON 解析失败**：后端做容错（正则提取 `[...]` 段），仍失败则把 `rawText` 原样返回，前端展示原始文本并提示「格式异常，可手动调整」
- **导入 JSON 结构不符**：`import_param_config` 返回 `{ok:false, missing:[...], warnings:[...]}`，前端高亮缺失模块
- **受保护功能未授权**：`/api/storyboard/generate` 走 `commercial_feature_denial`（`matrix.devices` feature，与 `/api/agent` 一致）
- **项目文件损坏**：读取失败时项目侧边栏标记该条「损坏」，不阻断其他项目

## 9. 测试

### 后端（pytest，参照仓库已有 `python/tests/` 风格）
- `services/test_storyboard.py`：
  - `build_context` 各 stage 的上下文包含目标对象 + 正确模块的选中项
  - `resolve_hint` 对 null / 缺失 / 非空字符串三种情况
  - `extract_asset_prompts` 把分镜按 `assetType` 正确分类，且拼上了风格参数
  - `import_param_config` 校验：缺模块记 warning 不阻断
- mock `model_client.complete` 验证 `generate` 把上下文正确传入 payload 且 `systemOverride` 生效

### 前端（参照仓库已有 `*.test.tsx`）
- `StoryboardOptionGroups.test.tsx`：tag/dropdown/radio/toggle/contentTypes 五种控件渲染 + 选中态
- `StoryboardWorkbench.test.tsx`：项目持久化往返（新建 → 选选项 → 保存 → 刷新 → 数据恢复）
- `storyboardApi.test.ts`：mock fetch 验证三个端点调用

## 10. 不在本期范围

- 模块十「一键发布」（多平台上传、平台 API 对接）
- 数字人配音、视频合成、字幕烧录（模块九仅做提示词 + 可选调 videoApi 生成单段）
- 「再来一版 / 换个钩子 / 更口语化」等一键改写预设（架构上就是再调一次 `generate`，可后续加快捷按钮）
- 对标账号 AI 推荐（需要外部数据源）

## 11. 文件清单

**新增**：
- `python/services/storyboard.py`
- `python/api/routes_storyboard.py`
- `python/tests/services/test_storyboard.py`
- `src/components/storyboard/`（8 个文件）
- `src/services/storyboardApi.ts`
- `src/components/storyboard/storyboardTypes.ts`

**修改**：
- `python/core/paths.py`（+4 属性）
- `python/core/feature_access.py`（`FEATURE_PATH_RULES` 新增 `("/api/storyboard/generate", "matrix.devices")`）
- `python/core/loom_model_client.py`（`build_chat_payload` 识别 `systemOverride`）
- `python/bridge.py`（`_build_fastapi_context` + `_get_storyboard_svc`）
- `python/api/fastapi_routes.py`（注册新路由）
- `src/components/creative/CreativeMediaPage.tsx`（+第三个 tab）
- `src/components/settings/SettingsPage.tsx`（+导入 JSON 行）
