# 全案九步创作工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "全案九步" (nine-step) video creation workbench to the 创作栏 that turns a target object + module selections into script → storyboard → asset prompts → video prompt, reusing the existing LoomModelClient for text and imageApi/videoApi for media.

**Architecture:** New `storyboard` domain: a Python `StoryboardService` (context assembly + LLM call + asset-prompt extraction) exposed via `/api/storyboard/*` routes; a React `StoryboardWorkbench` mounted as a third tab in `CreativeMediaPage`; project state persisted to `data/.openclaw/storyboard/projects/*.json` via the existing `configApi`. Param-config JSON imported from the Settings page, with `null` values backfilled by an in-repo `DEFAULT_OPTION_HINTS` map.

**Tech Stack:** Python (FastAPI, urllib, stdlib only), React 18 + TypeScript + Vite, Tauri IPC. Tests: Python `unittest` + `fastapi.testclient.TestClient` (backend); Python source-contract tests asserting on `.tsx` strings (frontend, following `test_creative_media_contract.py`); `tsc --noEmit` for type-checking.

**Spec:** `docs/superpowers/specs/2026-07-20-storyboard-nine-step-workbench-design.md`

**Working directory:** `openclaw_new_launcher/` (all relative paths below are from here unless noted).

**Conventions confirmed from the codebase:**
- Backend tests live in `python/tests/test_*.py`, use `unittest`, build a `SimpleNamespace` ctx + `FastAPI()` + `TestClient`. See `python/tests/test_routes_wire.py:126` for the `_app()` helper pattern.
- Frontend "contract tests" are Python tests in `python/tests/test_*_contract.py` that read `.tsx`/`.ts` source as text and assert on markers (e.g. `test_creative_media_contract.py`).
- Run backend test: `python python/tests/test_xxx.py` (or `python -m pytest python/tests/test_xxx.py -v`).
- Run frontend type-check: `npm run build` (does `tsc && vite build`) or faster `npx tsc --noEmit`.
- Run frontend contract tests: `python python/tests/test_xxx_contract.py`.
- Commits: conventional-commit style (`feat:`, `test:`, `chore:`, `docs:`). Commit per task.

---

## File Structure

**New backend files:**
- `python/services/storyboard.py` — `StoryboardService` + `DEFAULT_OPTION_HINTS` + `build_context` + `extract_asset_prompts` + 3 system-prompt templates. Pure functions where possible.
- `python/api/routes_storyboard.py` — `/api/storyboard/param-config`, `/import-param-config`, `/generate`.
- `python/tests/test_storyboard_service.py` — unit tests for context/hint/extraction pure functions.
- `python/tests/test_routes_storyboard.py` — route tests with TestClient.

**New frontend files:**
- `src/services/storyboardApi.ts` — typed wrappers around `/api/storyboard/*`.
- `src/components/storyboard/storyboardTypes.ts` — `StoryboardProject`, `StoryboardSelections`, `StoryboardShot`, `StoryboardParamConfig` types.
- `src/components/storyboard/storyboardSteps.ts` — nine-step metadata (single source of truth, mirrors the HTML prototype `steps[]`).
- `src/components/storyboard/StoryboardOptionGroups.tsx` — renders a list of option-groups (tag/dropdown/radio/toggle/contentTypes controls) from param-config.
- `src/components/storyboard/StoryboardProjectsSidebar.tsx` — project list (new/switch/rename/delete) backed by configApi.
- `src/components/storyboard/StoryboardScriptPanel.tsx` — module 4 (generate + editable textarea + save).
- `src/components/storyboard/StoryboardShotsPanel.tsx` — module 5 (shots table + auto-extracted asset prompt cards).
- `src/components/storyboard/StoryboardAssetPanel.tsx` — modules 6/7/8 shared (style options + reference image + imageApi submit + result grid).
- `src/components/storyboard/StoryboardVideoPanel.tsx` — module 9 (config + generate prompt + optional videoApi submit).
- `src/components/storyboard/StoryboardWorkbench.tsx` — top-level: sidebar + target input + step bar + active step panel.
- `python/tests/test_storyboard_workbench_contract.py` — frontend source-contract test.

**Modified backend files:**
- `python/core/paths.py` — +`storyboard_dir`, `storyboard_param_config`, `storyboard_projects_dir`, `storyboard_projects_index`.
- `python/core/feature_access.py` — add `("/api/storyboard/generate", "matrix.devices")` to `FEATURE_PATH_RULES`.
- `python/core/loom_model_client.py` — `build_chat_payload` honors `request.get("systemOverride")`.
- `python/bridge.py` — `_build_fastapi_context` adds `get_storyboard_svc`; new `_get_storyboard_svc()` singleton.
- `python/api/fastapi_routes.py` — register `register_storyboard_routes`.

**Modified frontend files:**
- `src/components/creative/CreativeMediaPage.tsx` — add third tab "全案九步".
- `src/components/settings/SettingsPage.tsx` — add "全案九步参数配置" import row in `data` tab.

---

## Task 1: Add storyboard paths to AppPaths

**Files:**
- Modify: `openclaw_new_launcher/python/core/paths.py` (after the `storyboard_dir`/`storyboard_project` block, around line 281-289)

- [ ] **Step 1: Read the current paths block to anchor the edit**

Run: `sed -n '278,295p' python/core/paths.py`
Expected: see existing `storyboard_dir`, `storyboard_project`, `storyboard_assets` properties (these are unrelated legacy ad-storyboard paths — we add new `nine_step_*` names to avoid collision).

- [ ] **Step 2: Add four new path properties**

Insert immediately after the `storyboard_assets` property (keep the legacy `storyboard_*` names intact; our new feature uses distinct `nine_step_*` names):

```python
    @property
    def nine_step_dir(self) -> str:
        return os.path.join(self.state_dir, "nine-step")

    @property
    def nine_step_param_config(self) -> str:
        return os.path.join(self.nine_step_dir, "param-config.json")

    @property
    def nine_step_projects_dir(self) -> str:
        return os.path.join(self.nine_step_dir, "projects")

    @property
    def nine_step_projects_index(self) -> str:
        return os.path.join(self.nine_step_projects_dir, "index.json")
```

- [ ] **Step 3: Verify import works**

Run: `python -c "import sys; sys.path.insert(0,'python'); from core.paths import AppPaths; p=AppPaths('.'); print(p.nine_step_dir, p.nine_step_param_config)"`
Expected: prints `./data/.openclaw/nine-step` and `./data/.openclaw/nine-step/param-config.json` with no error.

- [ ] **Step 4: Commit**

```bash
git add python/core/paths.py
git commit -m "feat(storyboard): add nine-step path properties to AppPaths"
```

---

## Task 2: Extend build_chat_payload to honor systemOverride

**Files:**
- Modify: `openclaw_new_launcher/python/core/loom_model_client.py` — function `build_chat_payload` (around line 497, the `messages` list construction)
- Test: `openclaw_new_launcher/python/tests/test_loom_model_client.py`

- [ ] **Step 1: Write the failing test**

Append to `python/tests/test_loom_model_client.py` (inside the existing test class that has access to `build_chat_payload` and `managed_session()` — check the file for the `LoomModelClientPayloadTests`-style class; if none, add a new `unittest.TestCase`):

```python
    def test_chat_payload_honors_system_override_when_provided(self) -> None:
        profile = profile_from_session(managed_session())
        payload = build_chat_payload(profile, {
            "prompt": "写文案",
            "systemOverride": "你是九步文案专家，只输出JSON。",
        })
        messages = payload["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("九步文案专家", messages[0]["content"])
        self.assertNotIn("麓鸣原生中枢智能体", messages[0]["content"])
```

If the test file doesn't already import `profile_from_session`/`build_chat_payload`/`managed_session` at module scope, add the imports matching the existing style (look for `from core.loom_model_client import ...`).

- [ ] **Step 2: Run test to verify it fails**

Run: `python python/tests/test_loom_model_client.py::LoomModelClientPayloadTests.test_chat_payload_honors_system_override_when_provided -v` (adjust class name to match) or `python -m pytest python/tests/test_loom_model_client.py -k system_override -v`
Expected: FAIL — the system message still contains the default agent prompt.

- [ ] **Step 3: Implement the override**

In `build_chat_payload` (loom_model_client.py ~line 497), replace the first `messages` line:

```python
    messages: list[dict[str, Any]] = [{"role": "system", "content": build_agent_system_prompt(capabilities)}]
```

with:

```python
    system_override = request.get("systemOverride")
    system_content = (
        system_override if isinstance(system_override, str) and system_override.strip()
        else build_agent_system_prompt(capabilities)
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
```

- [ ] **Step 4: Run the new test and the full model-client suite**

Run: `python -m pytest python/tests/test_loom_model_client.py -v`
Expected: all tests PASS, including the new one.

- [ ] **Step 5: Commit**

```bash
git add python/core/loom_model_client.py python/tests/test_loom_model_client.py
git commit -m "feat(model-client): honor systemOverride in build_chat_payload"
```

---

## Task 3: Register /api/storyboard/generate as a protected path

**Files:**
- Modify: `openclaw_new_launcher/python/core/feature_access.py` — `FEATURE_PATH_RULES` tuple (around line 26-38)

- [ ] **Step 1: Write the failing test**

Create `python/tests/test_storyboard_feature_gate.py`:

```python
from __future__ import annotations

import os
import sys
import unittest

PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from core.feature_access import feature_for_path


class StoryboardFeatureGateTests(unittest.TestCase):
    def test_storyboard_generate_requires_matrix_devices_feature(self) -> None:
        self.assertEqual(feature_for_path("/api/storyboard/generate"), "matrix.devices")

    def test_storyboard_get_param_config_is_unprotected(self) -> None:
        # GET-only read endpoints should not require a paid feature
        self.assertIsNone(feature_for_path("/api/storyboard/param-config"))

    def test_storyboard_import_is_unprotected(self) -> None:
        self.assertIsNone(feature_for_path("/api/storyboard/import-param-config"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python python/tests/test_storyboard_feature_gate.py`
Expected: FAIL — `feature_for_path("/api/storyboard/generate")` returns `None`, not `"matrix.devices"`.

- [ ] **Step 3: Add the rule**

In `feature_access.py`, add this line to `FEATURE_PATH_RULES` (insert before the `("/api/image/generate", "image"),` line so longer prefixes are checked first — though `_matches` uses exact-or-prefix so order matters only for overlapping prefixes; place it near the other `/api/...` entries):

```python
    ("/api/storyboard/generate", "matrix.devices"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python python/tests/test_storyboard_feature_gate.py`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add python/core/feature_access.py python/tests/test_storyboard_feature_gate.py
git commit -m "feat(storyboard): gate /api/storyboard/generate behind matrix.devices"
```

---

## Task 4: Create StoryboardService — DEFAULT_OPTION_HINTS + resolve_hint + build_context

This is the core of the feature. Split across Tasks 4-6 for testability.

**Files:**
- Create: `openclaw_new_launcher/python/services/storyboard.py`
- Test: `openclaw_new_launcher/python/tests/test_storyboard_service.py`

- [ ] **Step 1: Write the failing tests for hint resolution and context assembly**

Create `python/tests/test_storyboard_service.py`:

```python
from __future__ import annotations

import os
import sys
import unittest

PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from services.storyboard import (
    DEFAULT_OPTION_HINTS,
    build_context,
    resolve_hint,
    GENERIC_HINT_TEMPLATE,
)


def _param_config() -> dict:
    return {
        "模块一": {
            "产品/服务类型": {"实物商品": "你是实物商品定位专家，强调产品实体、品质、供应链。", "虚拟服务": None},
        },
        "模块二": {"内容大类": {"种草测评类": None}},
        "模块三": {},
        "模块四": {"视频类型": {"种草测评": "用种草测评视角组织文案。"}},
        "模块五": {},
    }


def _project(stage: str) -> dict:
    base = {
        "target": {"category": "食品饮料", "object": "3秒冷萃咖啡液"},
        "selections": {
            "模块一": {"产品/服务类型": ["实物商品"]},
            "模块二": {"内容大类": ["种草测评类"]},
            "模块三": {},
            "模块四": {"视频类型": ["种草测评"]},
            "模块五": {},
        },
        "script": {"content": "定稿文案示例"},
        "storyboard": {"shots": [{"num": 1, "scene": "x", "voice": "y", "assetType": "产品图"}]},
    }
    return base


class ResolveHintTests(unittest.TestCase):
    def test_returns_explicit_string_when_present(self) -> None:
        cfg = _param_config()
        self.assertEqual(
            resolve_hint(cfg, "模块一", "产品/服务类型", "实物商品"),
            "你是实物商品定位专家，强调产品实体、品质、供应链。",
        )

    def test_backfills_null_from_default_hints(self) -> None:
        cfg = _param_config()
        # "种草测评类" is null in cfg; default hint must exist
        hint = resolve_hint(cfg, "模块二", "内容大类", "种草测评类")
        self.assertIsInstance(hint, str)
        self.assertTrue(hint.strip())
        self.assertIn(hint, DEFAULT_OPTION_HINTS.values())

    def test_falls_back_to_generic_template_when_unknown(self) -> None:
        cfg = _param_config()
        hint = resolve_hint(cfg, "模块一", "产品/服务类型", "完全不存在的选项")
        self.assertIn("完全不存在的选项", hint)
        self.assertEqual(hint, GENERIC_HINT_TEMPLATE.format(option="完全不存在的选项"))


class BuildContextTests(unittest.TestCase):
    def test_script_stage_includes_target_and_modules_one_two_three(self) -> None:
        system, user = build_context("script", _project("script"), _param_config())
        self.assertIn("3秒冷萃咖啡液", user)
        self.assertIn("食品饮料", user)
        self.assertIn("模块一", user)
        self.assertIn("模块二", user)
        self.assertIn("模块三", user)
        # module 4 selections also included for script stage
        self.assertIn("模块四", user)
        # module 5 not relevant for script
        self.assertIsInstance(system, str)
        self.assertTrue(system.strip())

    def test_storyboard_stage_includes_script_content(self) -> None:
        _, user = build_context("storyboard", _project("storyboard"), _param_config())
        self.assertIn("定稿文案示例", user)

    def test_video_prompt_stage_includes_script_and_shots(self) -> None:
        _, user = build_context("videoPrompt", _project("videoPrompt"), _param_config())
        self.assertIn("定稿文案示例", user)
        self.assertIn('"assetType": "产品图"', user)

    def test_unknown_stage_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_context("nope", _project("script"), _param_config())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python python/tests/test_storyboard_service.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.storyboard'`.

- [ ] **Step 3: Create the service module with hints + resolve_hint + build_context**

Create `python/services/storyboard.py`:

```python
"""Storyboard (全案九步) service: context assembly and LLM orchestration."""

from __future__ import annotations

import json
from typing import Any

from core.storage import read_json, write_json


GENERIC_HINT_TEMPLATE = "当选择「{option}」时，请在文案中体现该方向的核心特征与对目标用户的吸引力。"

# Built-in default system-prompt fragments per option. Keys use a NUL-separated
# "模块\0类目\0选项" form so we can collide-proof against user strings.
DEFAULT_OPTION_HINTS: dict[str, str] = {
    # --- 模块一 ---
    "\0".join(["模块一", "产品/服务类型", "实物商品"]): "围绕看得见摸得着的实体商品展开，强调产品本体、用料、工艺与供应链。",
    "\0".join(["模块一", "产品/服务类型", "虚拟服务"]): "围绕无形服务展开，强调服务流程、交付方式与结果保障。",
    "\0".join(["模块一", "产品/服务类型", "知识课程"]): "围绕知识/课程展开，强调内容价值、体系化与学习收益。",
    "\0".join(["模块一", "产品/服务类型", "门店服务"]): "围绕到店服务展开，强调门店体验、地理位置与现场感受。",
    "\0".join(["模块一", "产品/服务类型", "加盟项目"]): "围绕加盟招商展开，强调模式成熟度、扶持政策与回报。",
    "\0".join(["模块一", "产品/服务类型", "本地生活服务"]): "围绕本地生活展开，强调就近便利、即时满足与口碑。",
    "\0".join(["模块一", "产品/服务类型", "咨询顾问"]): "围绕专业咨询展开，强调专家背书、定制方案与解决问题的能力。",
    "\0".join(["模块一", "所属品类", "食品饮料"]): "食品饮料类目，强调口感、配料、健康与食用场景。",
    "\0".join(["模块一", "所属品类", "美妆护肤"]): "美妆护肤类目，强调肤感、功效、成分与适用肤质。",
    "\0".join(["模块一", "所属品类", "服饰"]): "服饰类目，强调版型、面料、穿搭场景与风格。",
    "\0".join(["模块一", "所属品类", "母婴"]): "母婴类目，强调安全、温和、适龄与育儿场景。",
    "\0".join(["模块一", "所属品类", "家居"]): "家居类目，强调实用、颜值、生活品质提升。",
    "\0".join(["模块一", "所属品类", "教育"]): "教育类目，强调效果、师资、体系与成长。",
    "\0".join(["模块一", "所属品类", "美业"]): "美业类目，强调服务体验、效果与专业度。",
    "\0".join(["模块一", "客单价区间", "＜50 元"]): "低客单，强调性价比、低门槛尝试、囤货。",
    "\0".join(["模块一", "客单价区间", "50–200 元"]): "中低客单，强调品质与价格的平衡。",
    "\0".join(["模块一", "客单价区间", "200–1000 元"]): "中高客单，强调价值感与决策信心。",
    "\0".join(["模块一", "客单价区间", "1000–1 万"]): "高客单，强调信任、保障与长期价值。",
    "\0".join(["模块一", "客单价区间", "＞1 万"]): "超高客单，强调稀缺、身份与定制。",
    "\0".join(["模块一", "购买/使用场景", "日常刚需"]): "日常刚需场景，强调高频、必备、便利。",
    "\0".join(["模块一", "购买/使用场景", "送礼"]): "送礼场景，强调包装、面子、情感表达。",
    "\0".join(["模块一", "购买/使用场景", "应急"]): "应急场景，强调即时可用、解决问题。",
    "\0".join(["模块一", "购买/使用场景", "提升型消费"]): "提升型消费，强调生活品质升级。",
    "\0".join(["模块一", "购买/使用场景", "决策周期长的大件"]): "长决策大件，强调对比优势与售后保障。",
    "\0".join(["模块一", "核心卖点（多选）", "价格优势"]): "价格卖点：突出性价比、活动价、对比省钱。",
    "\0".join(["模块一", "核心卖点（多选）", "品质用料"]): "品质卖点：突出用料、工艺、细节。",
    "\0".join(["模块一", "核心卖点（多选）", "效果功效"]): "功效卖点：突出可感知的效果与变化。",
    "\0".join(["模块一", "核心卖点（多选）", "服务体验"]): "服务卖点：突出流程、态度、保障。",
    "\0".join(["模块一", "核心卖点（多选）", "稀缺独家"]): "稀缺卖点：突出独家、限量、难复制。",
    "\0".join(["模块一", "核心卖点（多选）", "资质背书"]): "资质卖点：突出认证、奖项、权威认可。",
    "\0".join(["模块一", "核心卖点（多选）", "技术专利"]): "技术卖点：突出专利、研发、创新。",
    "\0".join(["模块一", "核心卖点（多选）", "情感与价值观"]): "情感卖点：突出共鸣、价值观、归属感。",
    "\0".join(["模块一", "核心卖点（多选）", "售后保障"]): "售后卖点：突出保修、退换、兜底。",
    # (remaining 模块一 categories 竞争力来源/信任状/目标客户画像/客户核心痛点/购买抗拒点/用户身份角色/出镜意愿
    #  use the generic template fallback — they are numerous and the generic template is meaningful.)
    # --- 模块二 ---
    "\0".join(["模块二", "内容大类", "知识博主类"]): "知识博主风格：树立专业权威，干货输出为主。",
    "\0".join(["模块二", "内容大类", "种草测评类"]): "种草测评风格：好物推荐、真实体验、促转化。",
    "\0".join(["模块二", "内容大类", "品牌宣传类"]): "品牌宣传风格：讲品牌故事与理念，建信任。",
    "\0".join(["模块二", "内容大类", "剧情故事类"]): "剧情故事风格：用短剧/反转段子吸引传播。",
    "\0".join(["模块二", "内容大类", "生活 vlog 类"]): "生活 vlog 风格：日常记录，拉近距离。",
    "\0".join(["模块二", "内容大类", "促销带货类"]): "促销带货风格：限时优惠、福利、冲量。",
    "\0".join(["模块二", "人设语气", "专业权威"]): "语气：专业权威，可信、有据。",
    "\0".join(["模块二", "人设语气", "亲切邻家"]): "语气：亲切邻家，像朋友聊天。",
    "\0".join(["模块二", "人设语气", "幽默调侃"]): "语气：幽默调侃，轻松有趣。",
    "\0".join(["模块二", "人设语气", "犀利吐槽"]): "语气：犀利吐槽，观点鲜明。",
    "\0".join(["模块二", "人设语气", "温柔治愈"]): "语气：温柔治愈，情绪安抚。",
    "\0".join(["模块二", "人设语气", "励志正能量"]): "语气：励志正能量，鼓舞行动。",
    # 模块二 视觉调性 / 风格组合 use generic fallback.
    # --- 模块三 / 四 / 五 / 六 / 七 / 八 / 九 --- covered by generic fallback unless a high-value
    #     option needs a specific hint; add more here as needed.
}


def resolve_hint(param_config: dict, module: str, category: str, option: str) -> str:
    """Return the system-prompt fragment for an option, backfilling null/missing."""
    try:
        value = (param_config.get(module, {}).get(category, {}) or {}).get(option)
    except AttributeError:
        value = None
    if isinstance(value, str) and value.strip():
        return value
    key = "\0".join([module, category, option])
    default = DEFAULT_OPTION_HINTS.get(key)
    if isinstance(default, str) and default.strip():
        return default
    return GENERIC_HINT_TEMPLATE.format(option=option)


SCRIPT_SYSTEM_TEMPLATE = (
    "你是资深短视频文案专家。基于给定的目标对象与定位/风格/全案上下文，产出一段「可直接开口念」的"
    "完整口播/剧情文案。要求：开头3秒强钩子；卖点表达具体、口语化；结尾给出明确转化引导（CTA）；"
    "字数与目标时长匹配（每秒约4-5字）。只输出文案正文，不要解释。"
)

STORYBOARD_SYSTEM_TEMPLATE = (
    "你是资深短视频分镜师。基于定稿文案与上下文，把文案逐镜拆解为分镜脚本。"
    "严格输出一个 JSON 数组，每个元素包含字段：num(镜号整数)、time(时长如\"0-3s\")、"
    "scene(画面内容)、voice(口播/台词)、subtitle(屏幕字幕)、effect(特效/贴纸)、"
    "shotType(景别)、camera(运镜)、transition(转场)、bgm(BGM/音效)、"
    "assetType(人物图/产品图/场景图/无之一)、shootTip(拍摄提示)。只输出 JSON，不要解释。"
)

VIDEO_PROMPT_SYSTEM_TEMPLATE = (
    "你是 AI 视频提示词工程师。基于文案、分镜与成片配置，产出一段可直接用于视频生成模型的"
    "中文提示词，涵盖主体、动作、镜头运动、光线、色调、节奏与风格。只输出提示词正文，不要解释。"
)


def _append_selections(parts: list[str], project: dict, param_config: dict, module: str) -> None:
    selections = (project.get("selections") or {}).get(module, {}) or {}
    for category, options in selections.items():
        if not isinstance(options, list):
            continue
        for option in options:
            if isinstance(option, bool):
                # toggle controls: only mention when on
                if option:
                    parts.append(f"【{module} · {category}】已开启")
                continue
            option_text = str(option)
            hint = resolve_hint(param_config, module, category, option_text)
            parts.append(f"【{module} · {category} · {option_text}】\n{hint}")


def build_context(stage: str, project: dict, param_config: dict) -> tuple[str, str]:
    """Assemble (system_prompt, user_prompt) for a given generation stage."""
    if stage == "script":
        system = SCRIPT_SYSTEM_TEMPLATE
        context_modules = ["模块一", "模块二", "模块三", "模块四"]
    elif stage == "storyboard":
        system = STORYBOARD_SYSTEM_TEMPLATE
        context_modules = ["模块一", "模块二", "模块三", "模块四", "模块五"]
    elif stage == "videoPrompt":
        system = VIDEO_PROMPT_SYSTEM_TEMPLATE
        context_modules = ["模块一", "模块二", "模块三", "模块四", "模块五", "模块九"]
    else:
        raise ValueError(f"unknown storyboard stage: {stage}")

    parts: list[str] = []
    target = project.get("target") or {}
    parts.append(
        f"【目标对象】\n品类：{target.get('category', '')}\n对象：{target.get('object', '')}"
    )
    for module in context_modules:
        _append_selections(parts, project, param_config, module)

    user_parts = list(parts)
    if stage == "storyboard":
        script = (project.get("script") or {}).get("content") or ""
        user_parts.append(f"【定稿文案】\n{script}")
        user_parts.append("请把上文文案逐镜拆解为分镜脚本，严格输出 JSON 数组。")
    elif stage == "videoPrompt":
        script = (project.get("script") or {}).get("content") or ""
        shots = (project.get("storyboard") or {}).get("shots") or []
        user_parts.append(f"【文案】\n{script}")
        user_parts.append("【分镜】\n" + json.dumps(shots, ensure_ascii=False))
        user_parts.append("请基于以上信息产出可直接用于视频生成模型的提示词。")
    else:
        user_parts.append("请基于以上设定产出完整口播/剧情文案。")

    return system, "\n\n".join(user_parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python python/tests/test_storyboard_service.py`
Expected: PASS (7 tests: 3 resolve_hint + 4 build_context).

- [ ] **Step 5: Commit**

```bash
git add python/services/storyboard.py python/tests/test_storyboard_service.py
git commit -m "feat(storyboard): add service with hint resolution and context assembly"
```

---

## Task 5: Add extract_asset_prompts to StoryboardService

**Files:**
- Modify: `openclaw_new_launcher/python/services/storyboard.py` (append function)
- Modify: `openclaw_new_launcher/python/tests/test_storyboard_service.py` (append test class)

- [ ] **Step 1: Write the failing test**

Append to `python/tests/test_storyboard_service.py`:

```python
from services.storyboard import extract_asset_prompts


class ExtractAssetPromptsTests(unittest.TestCase):
    def test_classifies_shots_by_asset_type_and_appends_style(self) -> None:
        project = {
            "selections": {
                "模块六": {"气质风格": ["亲和邻家"], "画幅": ["9:16"]},
                "模块七": {"视觉风格": ["电商精致"], "画幅比例": ["9:16"]},
                "模块八": {"场景类型": ["厨房"], "画幅": ["9:16"]},
            },
            "storyboard": {
                "shots": [
                    {"num": 1, "scene": "女性手持咖啡杯", "assetType": "人物图"},
                    {"num": 2, "scene": "咖啡液产品特写", "assetType": "产品图"},
                    {"num": 3, "scene": "明亮厨房环境", "assetType": "场景图"},
                    {"num": 4, "scene": "纯口播无素材", "assetType": "无"},
                ]
            },
        }
        result = extract_asset_prompts(project, {})
        self.assertEqual(set(result.keys()), {"人物图", "产品图", "场景图"})
        self.assertEqual(len(result["人物图"]), 1)
        self.assertIn("女性手持咖啡杯", result["人物图"][0])
        self.assertIn("亲和邻家", result["人物图"][0])
        self.assertIn("9:16", result["人物图"][0])
        self.assertIn("电商精致", result["产品图"][0])
        self.assertIn("厨房", result["场景图"][0])
        # "无" assetType shots are dropped
        self.assertEqual(sum(len(v) for v in result.values()), 3)

    def test_handles_missing_asset_type(self) -> None:
        project = {"storyboard": {"shots": [{"num": 1, "scene": "x"}]}}
        result = extract_asset_prompts(project, {})
        self.assertEqual(result, {"人物图": [], "产品图": [], "场景图": []})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python python/tests/test_storyboard_service.py`
Expected: FAIL — `ImportError: cannot import name 'extract_asset_prompts'`.

- [ ] **Step 3: Implement extract_asset_prompts**

Append to `python/services/storyboard.py`:

```python
ASSET_STYLE_MODULES = {
    "人物图": ("模块六", ["性别", "年龄段", "气质风格", "职业着装", "表情神态", "画面风格", "画幅", "背景"]),
    "产品图": ("模块七", ["出图类型", "产品呈现", "视觉风格", "背景/道具", "画幅比例"]),
    "场景图": ("模块八", ["场景类型", "光线氛围", "画面色调", "视觉风格", "画幅", "用途"]),
}


def _style_suffix(project: dict, module: str, categories: list[str]) -> str:
    parts: list[str] = []
    selections = (project.get("selections") or {}).get(module, {}) or {}
    for category in categories:
        options = selections.get(category)
        if isinstance(options, list) and options:
            values = [str(o) for o in options if not isinstance(o, bool)]
            if values:
                parts.append(f"{category}：{','.join(values)}")
    return "；".join(parts)


def extract_asset_prompts(project: dict, param_config: dict) -> dict:
    """Group storyboard shots by assetType into 人物图/产品图/场景图 prompts.

    Each prompt combines the shot's scene with the matching module's selected
    style parameters. Shots whose assetType is missing or '无' are dropped.
    """
    result: dict[str, list[str]] = {"人物图": [], "产品图": [], "场景图": []}
    shots = (project.get("storyboard") or {}).get("shots") or []
    for shot in shots:
        asset_type = str(shot.get("assetType") or "").strip()
        if asset_type not in result:
            continue
        module, categories = ASSET_STYLE_MODULES[asset_type]
        scene = str(shot.get("scene") or "").strip()
        style = _style_suffix(project, module, categories)
        prompt = f"镜头{shot.get('num', '?')}：{scene}"
        if style:
            prompt = f"{prompt}；{style}"
        result[asset_type].append(prompt)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python python/tests/test_storyboard_service.py`
Expected: PASS (all 9 tests).

- [ ] **Step 5: Commit**

```bash
git add python/services/storyboard.py python/tests/test_storyboard_service.py
git commit -m "feat(storyboard): extract asset prompts from shots by type"
```

---

## Task 6: Add StoryboardService class (param-config CRUD + generate)

**Files:**
- Modify: `openclaw_new_launcher/python/services/storyboard.py` (append class)
- Modify: `openclaw_new_launcher/python/tests/test_storyboard_service.py` (append test class)

- [ ] **Step 1: Write the failing test**

Append to `python/tests/test_storyboard_service.py`:

```python
import tempfile
from types import SimpleNamespace

from services.storyboard import StoryboardService


def _fake_model_client(text: str) -> SimpleNamespace:
    """A fake LoomModelClient whose complete() returns the given text."""
    def complete(request, emit, cancel, *, timeout_sec=None):
        return {"text": text, "toolCalls": [], "usage": {}, "model": "test"}
    return SimpleNamespace(complete=complete)


class StoryboardServiceParamConfigTests(unittest.TestCase):
    def test_get_param_config_backfills_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = StoryboardService(_Paths(tmp))
            imported = svc.import_param_config({
                "模块一": {"产品/服务类型": {"实物商品": None}},
                "模块二": {},
                "模块三": {},
            })
            self.assertTrue(imported["ok"])
            self.assertEqual(imported["optionCount"], 1)
            cfg = svc.get_param_config()
            hint = cfg["模块一"]["产品/服务类型"]["实物商品"]
            self.assertIsInstance(hint, str)
            self.assertTrue(hint.strip())

    def test_import_detects_missing_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = StoryboardService(_Paths(tmp))
            result = svc.import_param_config({"模块一": {}})
            self.assertTrue(result["ok"])
            self.assertIn("模块二", result["warnings"]["missing"])

    def test_generate_script_returns_model_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = StoryboardService(_Paths(tmp))
            project = _project("script")
            result = svc.generate("script", project, _fake_model_client("生成的文案"))
            self.assertEqual(result["stage"], "script")
            self.assertEqual(result["result"], "生成的文案")


class _Paths:
    def __init__(self, base):
        self.nine_step_param_config = os.path.join(base, "param-config.json")
        self.nine_step_dir = base
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python python/tests/test_storyboard_service.py`
Expected: FAIL — `ImportError: cannot import name 'StoryboardService'`.

- [ ] **Step 3: Implement StoryboardService**

Append to `python/services/storyboard.py`:

```python
import threading

REQUIRED_MODULES = ["模块一", "模块二", "模块三", "模块四", "模块五", "模块六", "模块七", "模块八", "模块九"]


def _backfill(param_config: dict) -> dict:
    """Return a copy where every null/missing option value is replaced by a hint string."""
    filled: dict[str, dict[str, dict[str, str]]] = {}
    for module, categories in (param_config or {}).items():
        if not isinstance(categories, dict):
            continue
        filled_module: dict[str, dict[str, str]] = {}
        for category, options in categories.items():
            if not isinstance(options, dict):
                continue
            filled_category: dict[str, str] = {}
            for option, value in options.items():
                if isinstance(value, str) and value.strip():
                    filled_category[option] = value
                else:
                    filled_category[option] = resolve_hint(param_config, module, category, option)
            filled_module[category] = filled_category
        filled[module] = filled_module
    return filled


class StoryboardService:
    def __init__(self, paths) -> None:
        self.paths = paths

    def get_param_config(self) -> dict:
        raw = read_json(self.paths.nine_step_param_config, {})
        return _backfill(raw if isinstance(raw, dict) else {})

    def import_param_config(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        present = [m for m in REQUIRED_MODULES if isinstance(payload.get(m), dict)]
        missing = [m for m in REQUIRED_MODULES if m not in present]
        write_json(self.paths.nine_step_param_config, payload)
        option_count = sum(
            len(options) if isinstance(options, dict) else 0
            for module in present
            for options in (payload[module].values())
        )
        return {
            "ok": True,
            "optionCount": option_count,
            "warnings": {"missing": missing},
            "backfilled": _backfill(payload),
        }

    def generate(self, stage: str, project: dict, model_client) -> dict:
        param_config = self.get_param_config()
        system, user = build_context(stage, project or {}, param_config)
        request = {
            "prompt": user,
            "history": [],
            "capabilities": [],
            "systemOverride": system,
        }
        cancel = threading.Event()
        result = model_client.complete(request, emit=lambda _event: None, cancel=cancel)
        text = str(result.get("text") or "").strip()
        return {"stage": stage, "result": text, "rawText": text}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python python/tests/test_storyboard_service.py`
Expected: PASS (all 12 tests).

- [ ] **Step 5: Commit**

```bash
git add python/services/storyboard.py python/tests/test_storyboard_service.py
git commit -m "feat(storyboard): add StoryboardService for param-config and generation"
```

---

## Task 7: Add /api/storyboard/* routes

**Files:**
- Create: `openclaw_new_launcher/python/api/routes_storyboard.py`
- Create: `openclaw_new_launcher/python/tests/test_routes_storyboard.py`

- [ ] **Step 1: Write the failing route tests**

Create `python/tests/test_routes_storyboard.py`:

```python
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api.routes_storyboard import register_storyboard_routes
from core.paths import AppPaths


def _fake_model_client(text: str) -> SimpleNamespace:
    def complete(request, emit, cancel, *, timeout_sec=None):
        return {"text": text, "toolCalls": [], "usage": {}, "model": "test"}
    return SimpleNamespace(complete=complete)


def _app(base_path: str, *, model_text: str = "ok", protected: bool = False) -> FastAPI:
    app = FastAPI()
    paths = AppPaths(base_path)

    async def body(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def fastapi_json(data: dict, status_code: int = 200):
        payload = dict(data)
        payload["_meta"] = {"ok": 200 <= status_code < 400 and "error" not in payload, "status": status_code}
        return JSONResponse(status_code=status_code, content=payload)

    svc = SimpleNamespace(
        get_param_config=lambda: {"模块一": {"产品/服务类型": {"实物商品": "hint"}}},
        import_param_config=lambda payload: {"ok": True, "optionCount": 1, "warnings": {"missing": []}, "backfilled": {}},
        generate=lambda stage, project, mc: {"stage": stage, "result": model_text, "rawText": model_text},
    )

    ctx = SimpleNamespace(
        auth_error=lambda _request: None,
        body=body,
        fastapi_json=fastapi_json,
        protected_error=lambda _path: fastapi_json({"error": "未授权"}, 403) if protected else None,
        get_storyboard_svc=lambda: svc,
        get_agent_service=lambda: SimpleNamespace(model_client=_fake_model_client(model_text)),
        paths=paths,
    )
    register_storyboard_routes(app, ctx)
    return app


class StoryboardRouteTests(unittest.TestCase):
    def test_get_param_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(_app(tmp))
            resp = client.get("/api/storyboard/param-config")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("模块一", data["config"])

    def test_import_param_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(_app(tmp))
            resp = client.post("/api/storyboard/import-param-config", json={"config": {"模块一": {}}})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["ok"])

    def test_generate_requires_feature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(_app(tmp, protected=True))
            resp = client.post("/api/storyboard/generate", json={"stage": "script", "project": {}})
            self.assertEqual(resp.status_code, 403)

    def test_generate_returns_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(_app(tmp, model_text="你好文案"))
            resp = client.post("/api/storyboard/generate", json={
                "stage": "script",
                "project": {"target": {"object": "咖啡"}},
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["result"], "你好文案")
            self.assertEqual(data["stage"], "script")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python python/tests/test_routes_storyboard.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.routes_storyboard'`.

- [ ] **Step 3: Create the routes module**

Create `python/api/routes_storyboard.py`:

```python
"""Storyboard (全案九步) FastAPI routes."""

from __future__ import annotations

from fastapi import Request


def register_storyboard_routes(app, ctx) -> None:

    @app.get("/api/storyboard/param-config")
    async def get_param_config(request: Request):
        if error := ctx.auth_error(request):
            return error
        svc = ctx.get_storyboard_svc()
        return ctx.fastapi_json({"config": svc.get_param_config()})

    @app.post("/api/storyboard/import-param-config")
    async def import_param_config(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        payload = body.get("config", body)
        if not isinstance(payload, dict):
            return ctx.fastapi_json({"error": "config 必须是对象"}, 400)
        svc = ctx.get_storyboard_svc()
        result = svc.import_param_config(payload)
        return ctx.fastapi_json(result)

    @app.post("/api/storyboard/generate")
    async def generate(request: Request):
        if error := ctx.protected_error(request.url.path):
            return error
        body = await ctx.body(request)
        stage = str(body.get("stage") or "").strip()
        if stage not in ("script", "storyboard", "videoPrompt"):
            return ctx.fastapi_json({"error": "stage 必须是 script/storyboard/videoPrompt"}, 400)
        project = body.get("project")
        if not isinstance(project, dict):
            return ctx.fastapi_json({"error": "project 必须是对象"}, 400)
        svc = ctx.get_storyboard_svc()
        model_client = ctx.get_agent_service().model_client
        result = svc.generate(stage, project, model_client)
        return ctx.fastapi_json(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python python/tests/test_routes_storyboard.py`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add python/api/routes_storyboard.py python/tests/test_routes_storyboard.py
git commit -m "feat(storyboard): add /api/storyboard/* routes"
```

---

## Task 8: Wire StoryboardService into Bridge + register routes

**Files:**
- Modify: `openclaw_new_launcher/python/bridge.py` — `_get_storyboard_svc()` + ctx field + register call
- Modify: `openclaw_new_launcher/python/api/fastapi_routes.py` — import + register
- Test: `python/tests/test_packaged_bridge_runtime_contract.py` may assert on ctx shape; run it after.

- [ ] **Step 1: Add the singleton getter in bridge.py**

In `python/bridge.py`, the existing `_get_image_client` / `_get_video_client` use a module-level global singleton pattern (around line 134-144):

```python
_image_client: ImageApiClient | None = None

def _get_image_client() -> ImageApiClient:
    global _image_client
    if _image_client is None:
        _image_client = ImageApiClient()
    return _image_client
```

Match this pattern exactly. First add a module-level global near the other `_xxx_client` declarations:

```python
_storyboard_svc = None
```

Then add the getter near `_get_video_client`:

```python
def _get_storyboard_svc():
    global _storyboard_svc
    if _storyboard_svc is None:
        from services.storyboard import StoryboardService
        _storyboard_svc = StoryboardService(paths)
    return _storyboard_svc
```

- [ ] **Step 2: Add the ctx field in `_build_fastapi_context`**

In `_build_fastapi_context` (around line 833-870), add to the `SimpleNamespace(...)` kwargs, next to the other `get_*` entries:

```python
        get_storyboard_svc=_get_storyboard_svc,
```

- [ ] **Step 3: Register the routes**

In `python/api/fastapi_routes.py`:
- Add import near the other `from api.routes_*` imports: `from api.routes_storyboard import register_storyboard_routes`
- Add call inside `register_fastapi_routes`, near `register_config_routes(app, ctx)`: `register_storyboard_routes(app, ctx)`

- [ ] **Step 4: Verify backend smoke**

Run:
```bash
cd openclaw_new_launcher
python -c "import sys; sys.path.insert(0,'python'); import bridge; print('bridge import ok')"
python python/tests/test_routes_storyboard.py
python python/tests/test_routes_wire.py
```
Expected: bridge imports cleanly; storyboard + wire route tests PASS.

- [ ] **Step 5: Commit**

```bash
git add python/bridge.py python/api/fastapi_routes.py
git commit -m "feat(storyboard): wire StoryboardService into bridge and routes"
```

---

## Task 9: Add storyboard TypeScript types and step metadata

**Files:**
- Create: `openclaw_new_launcher/src/components/storyboard/storyboardTypes.ts`
- Create: `openclaw_new_launcher/src/components/storyboard/storyboardSteps.ts`

This task has no test (pure data/types); type-checking happens via `tsc --noEmit` in later tasks.

- [ ] **Step 1: Create the types file**

Create `src/components/storyboard/storyboardTypes.ts`:

```typescript
export type ModuleKey =
  | '模块一' | '模块二' | '模块三' | '模块四' | '模块五'
  | '模块六' | '模块七' | '模块八' | '模块九';

/** option value: string for tag/radio/dropdown, boolean for toggle */
export type OptionValue = string | boolean;

/** module -> category -> selected option values */
export type StoryboardSelections = Partial<Record<ModuleKey, Record<string, OptionValue[]>>>;

export interface StoryboardTarget {
  category: string;
  object: string;
}

export interface StoryboardShot {
  num: number;
  time?: string;
  scene?: string;
  voice?: string;
  subtitle?: string;
  effect?: string;
  shotType?: string;
  camera?: string;
  transition?: string;
  bgm?: string;
  assetType?: '人物图' | '产品图' | '场景图' | '无' | string;
  shootTip?: string;
}

export interface StoryboardProject {
  projectId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  target: StoryboardTarget;
  selections: StoryboardSelections;
  script: { content: string; versions?: Array<{ content: string; savedAt: string }>; generatedAt?: string };
  storyboard: { shots: StoryboardShot[]; generatedAt?: string };
  assetPrompts?: { 人物图: string[]; 产品图: string[]; 场景图: string[] };
  generatedAssets?: Array<{ shotNum: number; kind: string; mediaId?: string; path?: string; createdAt?: string }>;
  videoPrompt?: { content: string; generatedAt?: string };
}

/** module -> category -> option -> prompt string (already backfilled, no nulls) */
export type StoryboardParamConfig = Partial<Record<ModuleKey, Record<string, Record<string, string>>>>;

export interface StoryboardProjectsIndexEntry {
  projectId: string;
  title: string;
  updatedAt: string;
}
```

- [ ] **Step 2: Create the step metadata file**

Create `src/components/storyboard/storyboardSteps.ts`. This mirrors the HTML prototype's `steps[]`. Keep it focused: only the fields the UI renders (label/icon/goal/sections with their option-group definitions). For brevity in the plan, here is the structure with module 1 and 4 fully shown; modules 2/3/5/6/7/8/9 follow the same `OptionGroup` shape using the categories/options from `全案九步_参数配置.json`:

```typescript
import type { ModuleKey } from './storyboardTypes';

export type ControlKind = 'tag' | 'dropdown' | 'radio' | 'toggle' | 'contentTypes';

export interface OptionGroup {
  category: string;       // matches a key in param-config[module], e.g. "产品/服务类型"
  label: string;           // display label
  hint?: string;
  control: ControlKind;
  multi?: boolean;         // for tag/contentTypes
  module: ModuleKey;
  /** For contentTypes only */
  items?: Array<{ name: string; forms?: string; goal?: string }>;
}

export interface StoryboardStep {
  id: number;
  key: string;
  module: ModuleKey;
  label: string;
  icon: string;
  goal: string;
  hasGenerate?: boolean;   // true for modules 4/5/9
  generateStage?: 'script' | 'storyboard' | 'videoPrompt';
  optionGroups: OptionGroup[];
}

export const STORYBOARD_STEPS: StoryboardStep[] = [
  {
    id: 0,
    key: 'target',
    module: '模块一',
    label: '目标对象',
    icon: '🎯',
    goal: '整个视频制作的中心点。对象可以是产品名称、场景描述或故事文章。',
    optionGroups: [],
  },
  {
    id: 1,
    key: 'm1',
    module: '模块一',
    label: '定位',
    icon: '🎯',
    goal: '产品·竞争力·痛点：从产品/服务出发，想清卖什么、凭什么强、卖给谁。',
    optionGroups: [
      { module: '模块一', category: '产品/服务类型', label: '产品/服务类型', control: 'tag', multi: false, hint: '选择主营业务类型' },
      { module: '模块一', category: '所属品类', label: '所属品类', control: 'dropdown', hint: '行业二级分类' },
      { module: '模块一', category: '客单价区间', label: '客单价区间', control: 'radio' },
      { module: '模块一', category: '购买/使用场景', label: '购买/使用场景', control: 'tag', multi: true },
      { module: '模块一', category: '核心卖点（多选）', label: '核心卖点', control: 'tag', multi: true },
      { module: '模块一', category: '竞争力来源', label: '竞争力来源', control: 'tag', multi: true },
      { module: '模块一', category: '信任状/背书', label: '信任状/背书', control: 'tag', multi: true },
      { module: '模块一', category: '目标客户画像', label: '目标客户画像', control: 'tag', multi: true },
      { module: '模块一', category: '客户核心痛点（多选）', label: '客户核心痛点', control: 'tag', multi: true },
      { module: '模块一', category: '购买抗拒点', label: '购买抗拒点', control: 'tag', multi: true },
      { module: '模块一', category: '用户身份角色', label: '用户身份角色', control: 'radio' },
      { module: '模块一', category: '出镜意愿', label: '出镜意愿', control: 'radio' },
    ],
  },
  {
    id: 2,
    key: 'm2',
    module: '模块二',
    label: '内容风格',
    icon: '🎨',
    goal: '内容形态与全局调性：选定主风格与辅助风格，决定后续文案语气、画面调性。',
    optionGroups: [
      { module: '模块二', category: '内容大类', label: '内容大类', control: 'tag', multi: false, hint: '主风格' },
      { module: '模块二', category: '人设语气', label: '人设语气', control: 'tag', multi: false },
      { module: '模块二', category: '视觉调性', label: '视觉调性', control: 'tag', multi: false },
      { module: '模块二', category: '风格组合', label: '风格组合', control: 'tag', multi: true, hint: '可选1主+1辅' },
    ],
  },
  {
    id: 3,
    key: 'm3',
    module: '模块三',
    label: '全案制作',
    icon: '📋',
    goal: '把定位+风格一键展开为可执行的运营全案。',
    optionGroups: [
      { module: '模块三', category: '可勾选生成的全案板块', label: '全案板块', control: 'tag', multi: true },
      { module: '模块三', category: '全案激进度', label: '全案激进度', control: 'radio' },
      { module: '模块三', category: '规划周期', label: '规划周期', control: 'radio' },
      { module: '模块三', category: '侧重方向', label: '侧重方向', control: 'radio' },
    ],
  },
  {
    id: 4,
    key: 'm4',
    module: '模块四',
    label: '文案撰写',
    icon: '✍️',
    goal: '产出可直接开口念的口播/剧情文案。',
    hasGenerate: true,
    generateStage: 'script',
    optionGroups: [
      { module: '模块四', category: '视频类型', label: '视频类型', control: 'tag', multi: false },
      { module: '模块四', category: '视频时长', label: '视频时长', control: 'radio' },
      { module: '模块四', category: '开头钩子', label: '开头钩子', control: 'tag', multi: false },
      { module: '模块四', category: '文案结构', label: '文案结构', control: 'tag', multi: false },
      { module: '模块四', category: '转化动作 CTA', label: '转化动作 CTA', control: 'tag', multi: true },
    ],
  },
  {
    id: 5,
    key: 'm5',
    module: '模块五',
    label: '分镜文案',
    icon: '🎬',
    goal: '文案转画面：逐镜拆解并标注每镜所需的素材类型。',
    hasGenerate: true,
    generateStage: 'storyboard',
    optionGroups: [
      { module: '模块五', category: '分镜颗粒度', label: '分镜颗粒度', control: 'radio' },
      { module: '模块五', category: '拍摄/成片方式', label: '拍摄/成片方式', control: 'tag', multi: false },
      { module: '模块五', category: '节奏卡点', label: '节奏卡点', control: 'radio' },
      { module: '模块五', category: '特效风格', label: '特效风格', control: 'tag', multi: false },
      { module: '模块五', category: '运镜偏好', label: '运镜偏好', control: 'tag', multi: false },
      { module: '模块五', category: '字幕与音效', label: '字幕与音效', control: 'tag', multi: true },
    ],
  },
  {
    id: 6,
    key: 'm6',
    module: '模块六',
    label: '人物图',
    icon: '🧑‍🎨',
    goal: '生成专属 IP 人物形象，保持跨内容一致。',
    optionGroups: [
      { module: '模块六', category: '性别', label: '性别', control: 'tag', multi: true },
      { module: '模块六', category: '年龄段', label: '年龄段', control: 'tag', multi: true },
      { module: '模块六', category: '气质风格', label: '气质风格', control: 'tag', multi: false },
      { module: '模块六', category: '职业着装', label: '职业着装', control: 'tag', multi: false },
      { module: '模块六', category: '表情神态', label: '表情神态', control: 'tag', multi: false },
      { module: '模块六', category: '画面风格', label: '画面风格', control: 'tag', multi: false },
      { module: '模块六', category: '画幅', label: '画幅', control: 'tag', multi: true },
      { module: '模块六', category: '背景', label: '背景', control: 'tag', multi: true },
    ],
  },
  {
    id: 7,
    key: 'm7',
    module: '模块七',
    label: '产品图',
    icon: '📦',
    goal: '生成电商级产品画面。',
    optionGroups: [
      { module: '模块七', category: '出图类型', label: '出图类型', control: 'tag', multi: true },
      { module: '模块七', category: '产品呈现', label: '产品呈现', control: 'tag', multi: true },
      { module: '模块七', category: '视觉风格', label: '视觉风格', control: 'tag', multi: false },
      { module: '模块七', category: '背景/道具', label: '背景/道具', control: 'tag', multi: true },
      { module: '模块七', category: '文字标注', label: '文字标注', control: 'tag', multi: true },
      { module: '模块七', category: '画幅比例', label: '画幅比例', control: 'radio' },
    ],
  },
  {
    id: 8,
    key: 'm8',
    module: '模块八',
    label: '场景图',
    icon: '🏙️',
    goal: '生成环境素材，可与人物/产品合成。',
    optionGroups: [
      { module: '模块八', category: '场景类型', label: '场景类型', control: 'tag', multi: true },
      { module: '模块八', category: '光线氛围', label: '光线氛围', control: 'tag', multi: false },
      { module: '模块八', category: '画面色调', label: '画面色调', control: 'tag', multi: false },
      { module: '模块八', category: '视觉风格', label: '视觉风格', control: 'tag', multi: false },
      { module: '模块八', category: '画幅', label: '画幅', control: 'tag', multi: true },
      { module: '模块八', category: '用途', label: '用途', control: 'tag', multi: true },
    ],
  },
  {
    id: 9,
    key: 'm9',
    module: '模块九',
    label: '视频提示词',
    icon: '🎞️',
    goal: '整合文案与分镜，组装可直接用于视频生成的提示词。',
    hasGenerate: true,
    generateStage: 'videoPrompt',
    optionGroups: [
      { module: '模块九', category: '成片方式', label: '成片方式', control: 'tag', multi: false },
      { module: '模块九', category: '配音音色', label: '配音音色', control: 'tag', multi: false },
      { module: '模块九', category: '语速', label: '语速', control: 'radio' },
      { module: '模块九', category: '字幕样式', label: '字幕样式', control: 'tag', multi: false },
      { module: '模块九', category: '背景音乐', label: '背景音乐', control: 'tag', multi: false },
      { module: '模块九', category: '转场特效', label: '转场特效', control: 'radio' },
      { module: '模块九', category: '画幅', label: '画幅', control: 'radio' },
      { module: '模块九', category: '片头尾', label: '片头尾', control: 'tag', multi: true },
    ],
  },
];
```

- [ ] **Step 3: Verify types compile**

Run: `cd openclaw_new_launcher && npx tsc --noEmit`
Expected: no errors related to the new files.

- [ ] **Step 4: Commit**

```bash
git add src/components/storyboard/storyboardTypes.ts src/components/storyboard/storyboardSteps.ts
git commit -m "feat(storyboard): add TypeScript types and step metadata"
```

---

## Task 10: Add storyboardApi service wrapper

**Files:**
- Create: `openclaw_new_launcher/src/services/storyboardApi.ts`

- [ ] **Step 1: Create the API wrapper**

Create `src/services/storyboardApi.ts`:

```typescript
import { api } from './api';
import type {
  StoryboardParamConfig,
  StoryboardProject,
} from '../components/storyboard/storyboardTypes';

export interface StoryboardParamConfigResponse {
  config: StoryboardParamConfig;
}

export interface StoryboardImportResult {
  ok: boolean;
  optionCount: number;
  warnings: { missing: string[] };
  backfilled: StoryboardParamConfig;
}

export interface StoryboardGenerateResult {
  stage: 'script' | 'storyboard' | 'videoPrompt';
  result: string;
  rawText: string;
}

export const storyboardApi = {
  getParamConfig: (): Promise<StoryboardParamConfigResponse> =>
    api('/api/storyboard/param-config'),
  importParamConfig: (config: unknown): Promise<StoryboardImportResult> =>
    api('/api/storyboard/import-param-config', 'POST', { config }),
  generate: (params: {
    stage: 'script' | 'storyboard' | 'videoPrompt';
    project: StoryboardProject;
  }): Promise<StoryboardGenerateResult> =>
    api('/api/storyboard/generate', 'POST', params),
};
```

- [ ] **Step 2: Verify it compiles**

Run: `cd openclaw_new_launcher && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/services/storyboardApi.ts
git commit -m "feat(storyboard): add storyboardApi frontend wrapper"
```

---

## Task 11: Build StoryboardOptionGroups component

**Files:**
- Create: `openclaw_new_launcher/src/components/storyboard/StoryboardOptionGroups.tsx`

This renders the option groups for a step and reports selection changes upward.

- [ ] **Step 1: Create the component**

Create `src/components/storyboard/StoryboardOptionGroups.tsx`:

```typescript
import React from 'react';
import { FieldLabel } from '../common';
import type { OptionGroup, StoryboardStep } from './storyboardSteps';
import type { StoryboardParamConfig, StoryboardSelections } from './storyboardTypes';

interface Props {
  step: StoryboardStep;
  paramConfig: StoryboardParamConfig;
  selections: StoryboardSelections;
  onSelectionChange: (module: StoryboardStep['module'], category: string, values: Array<string | boolean>) => void;
}

function optionsFor(group: OptionGroup, paramConfig: StoryboardParamConfig): string[] {
  const moduleConfig = paramConfig[group.module];
  const categoryConfig = moduleConfig?.[group.category];
  if (categoryConfig && typeof categoryConfig === 'object') {
    return Object.keys(categoryConfig);
  }
  return [];
}

function selectedValues(
  selections: StoryboardSelections,
  module: OptionGroup['module'],
  category: string,
): Array<string | boolean> {
  return selections[module]?.[category] ?? [];
}

function toggleArrayValue(current: Array<string | boolean>, value: string | boolean, multi: boolean): Array<string | boolean> {
  if (!multi) {
    return current.includes(value) ? [] : [value];
  }
  return current.includes(value)
    ? current.filter((v) => v !== value)
    : [...current, value];
}

export const StoryboardOptionGroups: React.FC<Props> = ({ step, paramConfig, selections, onSelectionChange }) => {
  if (!step.optionGroups.length) {
    return null;
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {step.optionGroups.map((group) => {
        const options = optionsFor(group, paramConfig);
        const selected = selectedValues(selections, group.module, group.category);
        if (group.control === 'dropdown') {
          return (
            <label key={group.category} className="block">
              <FieldLabel text={group.label} />
              <select
                className="w-full rounded-xl border border-border bg-input px-3 py-2 text-sm text-text"
                value={(selected[0] as string) || ''}
                onChange={(event) => onSelectionChange(group.module, group.category, event.target.value ? [event.target.value] : [])}
              >
                <option value="">请选择...</option>
                {options.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
              {group.hint ? <div className="mt-1 text-xs text-text-muted">{group.hint}</div> : null}
            </label>
          );
        }
        if (group.control === 'toggle') {
          const on = selected.includes(true);
          return (
            <div key={group.category} className="flex items-center justify-between rounded-xl border border-border bg-surface-alt/40 px-4 py-3">
              <div>
                <div className="text-sm font-semibold text-text">{group.label}</div>
                {group.hint ? <div className="mt-0.5 text-xs text-text-muted">{group.hint}</div> : null}
              </div>
              <button
                type="button"
                aria-pressed={on}
                onClick={() => onSelectionChange(group.module, group.category, [!on])}
                className={`h-6 w-11 rounded-full transition ${on ? 'bg-accent' : 'bg-border'}`}
              >
                <span className={`block h-5 w-5 translate-x-0.5 rounded-full bg-white transition ${on ? 'translate-x-5' : ''}`} />
              </button>
            </div>
          );
        }
        if (group.control === 'radio') {
          return (
            <div key={group.category}>
              <FieldLabel text={group.label} />
              <div className="flex flex-wrap gap-2">
                {options.map((option) => {
                  const active = selected.includes(option);
                  return (
                    <button
                      key={option}
                      type="button"
                      onClick={() => onSelectionChange(group.module, group.category, toggleArrayValue(selected, option, false))}
                      className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${active ? 'border-accent bg-accent-soft text-accent' : 'border-border bg-surface text-text-muted'}`}
                    >{option}</button>
                  );
                })}
              </div>
            </div>
          );
        }
        // default: tag (multi or single)
        return (
          <div key={group.category}>
            <FieldLabel text={group.label} />
            <div className="flex flex-wrap gap-2">
              {options.map((option) => {
                const active = selected.includes(option);
                return (
                  <button
                    key={option}
                    type="button"
                    onClick={() => onSelectionChange(group.module, group.category, toggleArrayValue(selected, option, Boolean(group.multi)))}
                    className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${active ? 'border-accent bg-accent-soft text-accent' : 'border-border bg-surface text-text-muted'}`}
                  >{option}</button>
                );
              })}
            </div>
            {group.hint ? <div className="mt-1 text-xs text-text-muted">{group.hint}</div> : null}
          </div>
        );
      })}
    </div>
  );
};
```

- [ ] **Step 2: Verify it compiles**

Run: `cd openclaw_new_launcher && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/components/storyboard/StoryboardOptionGroups.tsx
git commit -m "feat(storyboard): add StoryboardOptionGroups renderer"
```

---

## Task 12: Build StoryboardProjectsSidebar + project persistence helpers

**Files:**
- Create: `openclaw_new_launcher/src/components/storyboard/projectStore.ts`
- Create: `openclaw_new_launcher/src/components/storyboard/StoryboardProjectsSidebar.tsx`

- [ ] **Step 1: Create the project store helper**

Create `src/components/storyboard/projectStore.ts`:

```typescript
import { configApi } from '../../services/api';
import type { StoryboardProject, StoryboardProjectsIndexEntry } from './storyboardTypes';

const PROJECTS_PATH = '.openclaw/nine-step/projects';
const INDEX_PATH = `${PROJECTS_PATH}/index.json`;
const BASE_PROJECTS_PATH = 'data/.openclaw/nine-step/projects';

function nowIso(): string {
  return new Date().toISOString();
}

export function newProjectId(): string {
  const rand = Math.random().toString(16).slice(2, 10);
  return `sb_${rand}`;
}

export function emptyProject(title = '未命名项目'): StoryboardProject {
  const now = nowIso();
  return {
    projectId: newProjectId(),
    title,
    createdAt: now,
    updatedAt: now,
    target: { category: '', object: '' },
    selections: {},
    script: { content: '' },
    storyboard: { shots: [] },
  };
}

export async function loadProjectsIndex(): Promise<StoryboardProjectsIndexEntry[]> {
  const { data } = await configApi.read(INDEX_PATH, []);
  return Array.isArray(data) ? (data as StoryboardProjectsIndexEntry[]) : [];
}

export async function saveProjectsIndex(entries: StoryboardProjectsIndexEntry[]): Promise<void> {
  await configApi.write(INDEX_PATH, entries);
}

export async function loadProject(projectId: string): Promise<StoryboardProject | null> {
  const { data } = await configApi.read(`${PROJECTS_PATH}/${projectId}.json`, null);
  return (data && typeof data === 'object') ? (data as StoryboardProject) : null;
}

export async function saveProject(project: StoryboardProject): Promise<void> {
  const updated = { ...project, updatedAt: nowIso() };
  await configApi.write(`${PROJECTS_PATH}/${updated.projectId}.json`, updated);
  const entries = await loadProjectsIndex();
  const without = entries.filter((entry) => entry.projectId !== updated.projectId);
  without.unshift({ projectId: updated.projectId, title: updated.title, updatedAt: updated.updatedAt });
  await saveProjectsIndex(without);
}

export async function deleteProject(projectId: string): Promise<void> {
  const entries = await loadProjectsIndex();
  await saveProjectsIndex(entries.filter((entry) => entry.projectId !== projectId));
  // Note: configApi has no delete; leave the JSON file in place, it is just unlisted.
}

// `BASE_PROJECTS_PATH` exported for contract tests; not used at runtime.
export { BASE_PROJECTS_PATH };
```

> Note: the `configApi` `path` is resolved by backend `_safe_config_path` relative to base_path, so `.openclaw/nine-step/projects/...` lands under `data/.openclaw/nine-step/projects/...`. Verify in Task 16 end-to-end.

- [ ] **Step 2: Create the sidebar component**

Create `src/components/storyboard/StoryboardProjectsSidebar.tsx`:

```typescript
import React from 'react';
import { Button, Input, showConfirm, showToast } from '../common';
import type { StoryboardProjectsIndexEntry } from './storyboardTypes';

interface Props {
  entries: StoryboardProjectsIndexEntry[];
  activeProjectId: string | null;
  loading: boolean;
  onRefresh: () => void;
  onSelect: (projectId: string) => void;
  onCreate: () => void;
  onRename: (projectId: string, title: string) => void;
  onDelete: (projectId: string) => void;
}

export const StoryboardProjectsSidebar: React.FC<Props> = ({
  entries, activeProjectId, loading, onRefresh, onSelect, onCreate, onRename, onDelete,
}) => {
  const [renamingId, setRenamingId] = React.useState<string | null>(null);
  const [renameValue, setRenameValue] = React.useState('');

  const startRename = (entry: StoryboardProjectsIndexEntry) => {
    setRenamingId(entry.projectId);
    setRenameValue(entry.title);
  };
  const commitRename = () => {
    if (renamingId) {
      onRename(renamingId, renameValue.trim() || '未命名项目');
      setRenamingId(null);
    }
  };
  const handleDelete = async (entry: StoryboardProjectsIndexEntry) => {
    const ok = await showConfirm({
      title: '删除项目',
      message: `确定删除「${entry.title}」吗？项目文件不会被物理删除，但会从列表移除。`,
      confirmText: '删除',
      tone: 'danger',
    });
    if (ok) onDelete(entry.projectId);
  };

  return (
    <aside data-storyboard-projects-sidebar className="flex w-60 shrink-0 flex-col gap-3 border-r border-border bg-surface-alt/30 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-black text-text">项目</span>
        <Button variant="quiet" onClick={onRefresh} disabled={loading}>刷新</Button>
      </div>
      <Button variant="primary" onClick={onCreate}>新建项目</Button>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading ? (
          <div className="px-2 py-4 text-xs text-text-muted">加载中...</div>
        ) : entries.length === 0 ? (
          <div className="px-2 py-4 text-xs text-text-muted">暂无项目，点「新建项目」开始。</div>
        ) : (
          <ul className="space-y-1">
            {entries.map((entry) => (
              <li key={entry.projectId}>
                {renamingId === entry.projectId ? (
                  <div className="flex gap-1">
                    <Input value={renameValue} onChange={(e) => setRenameValue(e.target.value)} className="text-xs" />
                    <Button variant="quiet" onClick={commitRename}>确定</Button>
                  </div>
                ) : (
                  <div
                    data-storyboard-project-item={entry.projectId}
                    className={`group flex cursor-pointer items-center justify-between rounded-lg px-2 py-1.5 text-xs ${entry.projectId === activeProjectId ? 'bg-accent-soft text-accent' : 'text-text-muted hover:bg-hover'}`}
                    onClick={() => onSelect(entry.projectId)}
                  >
                    <span className="truncate">{entry.title}</span>
                    <span className="hidden gap-1 group-hover:flex">
                      <button type="button" className="text-text-muted hover:text-text" onClick={(e) => { e.stopPropagation(); startRename(entry); }}>改名</button>
                      <button type="button" className="text-status-danger hover:opacity-80" onClick={(e) => { e.stopPropagation(); void handleDelete(entry); }}>删</button>
                    </span>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
};

// re-export for convenience
export { showToast };
```

- [ ] **Step 3: Verify it compiles**

Run: `cd openclaw_new_launcher && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/components/storyboard/projectStore.ts src/components/storyboard/StoryboardProjectsSidebar.tsx
git commit -m "feat(storyboard): add projects sidebar and persistence helpers"
```

---

## Task 13: Build step panels (script / shots / asset / video)

**Files:**
- Create: `openclaw_new_launcher/src/components/storyboard/StoryboardScriptPanel.tsx`
- Create: `openclaw_new_launcher/src/components/storyboard/StoryboardShotsPanel.tsx`
- Create: `openclaw_new_launcher/src/components/storyboard/StoryboardAssetPanel.tsx`
- Create: `openclaw_new_launcher/src/components/storyboard/StoryboardVideoPanel.tsx`

These are presentational + generation-trigger components; they receive the project and a `onGenerate` callback. Keep each small.

- [ ] **Step 1: Create StoryboardScriptPanel (module 4)**

Create `src/components/storyboard/StoryboardScriptPanel.tsx`:

```typescript
import React from 'react';
import { Button, FieldLabel, TextArea, showToast } from '../common';

interface Props {
  content: string;
  generating: boolean;
  onContentChange: (content: string) => void;
  onGenerate: () => Promise<string | null>;
  onSave: () => Promise<void>;
}

export const StoryboardScriptPanel: React.FC<Props> = ({ content, generating, onContentChange, onGenerate, onSave }) => {
  const [draft, setDraft] = React.useState(content);
  React.useEffect(() => setDraft(content), [content]);

  const handleGenerate = async () => {
    const text = await onGenerate();
    if (text) {
      setDraft(text);
      showToast('文案已生成，记得保存', 'success');
    }
  };
  const handleSave = async () => {
    onContentChange(draft);
    await onSave();
    showToast('文案已保存', 'success');
  };

  return (
    <div data-storyboard-script-panel className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-text-muted">点「生成文案」基于模块一/二/三的设定产出文案；可在下方直接修改后保存。</p>
        <div className="flex gap-2">
          <Button variant="primary" onClick={handleGenerate} disabled={generating}>{generating ? '生成中...' : '生成文案'}</Button>
          <Button variant="quiet" onClick={handleSave} disabled={generating || draft === content}>保存</Button>
        </div>
      </div>
      <label className="block">
        <FieldLabel text="短视频文案" required />
        <TextArea value={draft} onChange={(e) => setDraft(e.target.value)} rows={12} placeholder="生成或手写的口播/剧情文案..." />
      </label>
    </div>
  );
};
```

- [ ] **Step 2: Create StoryboardShotsPanel (module 5)**

Create `src/components/storyboard/StoryboardShotsPanel.tsx`:

```typescript
import React from 'react';
import { Button, showToast } from '../common';
import type { StoryboardShot } from './storyboardTypes';

interface Props {
  shots: StoryboardShot[];
  assetPrompts: { 人物图: string[]; 产品图: string[]; 场景图: string[] };
  generating: boolean;
  scriptContent: string;
  onGenerate: () => Promise<StoryboardShot[] | null>;
}

export const StoryboardShotsPanel: React.FC<Props> = ({ shots, assetPrompts, generating, scriptContent, onGenerate }) => {
  const handleGenerate = async () => {
    if (!scriptContent.trim()) {
      showToast('请先在模块四生成或保存文案', 'error');
      return;
    }
    const result = await onGenerate();
    if (result) showToast(`已生成 ${result.length} 个分镜`, 'success');
  };
  return (
    <div data-storyboard-shots-panel className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-text-muted">基于已保存文案自动同步并逐镜拆解，同时提取人物/产品/场景素材提示词。</p>
        <Button variant="primary" onClick={handleGenerate} disabled={generating || !scriptContent.trim()}>
          {generating ? '生成中...' : '生成分镜'}
        </Button>
      </div>
      {shots.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-6 text-sm text-text-muted">暂无分镜。</div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-surface-alt/60 text-text-muted">
              <tr>
                {['镜', '时长', '景别', '画面', '口播/字幕', '素材', '特效'].map((h) => (
                  <th key={h} className="px-2 py-2 text-left font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shots.map((shot) => (
                <tr key={shot.num} className="border-t border-border">
                  <td className="px-2 py-2 font-bold text-accent">{shot.num}</td>
                  <td className="px-2 py-2 text-text-muted">{shot.time || ''}</td>
                  <td className="px-2 py-2 text-text-muted">{shot.shotType || ''}</td>
                  <td className="px-2 py-2 text-text">{shot.scene || ''}</td>
                  <td className="px-2 py-2 text-text">{shot.voice || ''}</td>
                  <td className="px-2 py-2 text-text-muted">{shot.assetType || ''}</td>
                  <td className="px-2 py-2 text-text-muted">{shot.effect || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(assetPrompts.人物图.length > 0 || assetPrompts.产品图.length > 0 || assetPrompts.场景图.length > 0) && (
        <div className="grid gap-3 md:grid-cols-3">
          {(['人物图', '产品图', '场景图'] as const).map((kind) => (
            <div key={kind} className="rounded-xl border border-border bg-surface-alt/30 p-3">
              <div className="mb-2 text-xs font-black text-text">{kind}提示词</div>
              {assetPrompts[kind].length === 0 ? (
                <div className="text-xs text-text-muted">无</div>
              ) : (
                <ul className="space-y-2">
                  {assetPrompts[kind].map((p, i) => (
                    <li key={i} className="rounded-lg bg-surface px-2 py-1.5 text-xs text-text-muted">{p}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 3: Create StoryboardAssetPanel (modules 6/7/8)**

Create `src/components/storyboard/StoryboardAssetPanel.tsx`. It receives the asset kind, the prompts, and a `onGenerate` that wraps `imageApi.submit`. To keep this task focused, the actual `imageApi` wiring lives in the parent workbench (Task 14) and is passed in:

```typescript
import React from 'react';
import { Button, FieldLabel, showToast } from '../common';
import { ReferenceImagePicker } from '../creative/ReferenceImagePicker';
import type { ReferenceImage } from '../creative/mediaPresets';

interface Props {
  kind: '人物图' | '产品图' | '场景图';
  prompts: string[];
  imageConfigReady: boolean;
  onGenerate: (prompt: string, reference: ReferenceImage | null) => Promise<void>;
}

export const StoryboardAssetPanel: React.FC<Props> = ({ kind, prompts, imageConfigReady, onGenerate }) => {
  const [selectedPrompt, setSelectedPrompt] = React.useState(prompts[0] || '');
  const [reference, setReference] = React.useState<ReferenceImage | null>(null);
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => { if (!selectedPrompt && prompts.length) setSelectedPrompt(prompts[0]); }, [prompts, selectedPrompt]);

  const handleGenerate = async () => {
    if (!selectedPrompt) { showToast('没有可用的提示词，请先生成分镜', 'error'); return; }
    if (!imageConfigReady) { showToast('请先在「生图」tab 配置生图模型', 'error'); return; }
    setBusy(true);
    try {
      await onGenerate(selectedPrompt, reference);
      showToast(`${kind}已提交生成`, 'success');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-storyboard-asset-panel={kind} className="space-y-4">
      <div className="text-xs text-text-muted">从分镜自动提取的{kind}提示词，配合参考图（选填）生成。</div>
      <FieldLabel text="提示词" />
      <select
        className="w-full rounded-xl border border-border bg-input px-3 py-2 text-sm text-text"
        value={selectedPrompt}
        onChange={(e) => setSelectedPrompt(e.target.value)}
      >
        {prompts.length === 0 ? <option value="">暂无提示词</option> : prompts.map((p, i) => (
          <option key={i} value={p}>{p.slice(0, 40)}...</option>
        ))}
      </select>
      <ReferenceImagePicker value={reference} latest={null} onChange={setReference} />
      <Button variant="primary" onClick={handleGenerate} disabled={busy || !selectedPrompt}>
        {busy ? '提交中...' : `生成${kind}`}
      </Button>
    </div>
  );
};
```

- [ ] **Step 4: Create StoryboardVideoPanel (module 9)**

Create `src/components/storyboard/StoryboardVideoPanel.tsx`:

```typescript
import React from 'react';
import { Button, FieldLabel, TextArea, showToast } from '../common';

interface Props {
  prompt: string;
  generating: boolean;
  onPromptChange: (prompt: string) => void;
  onGeneratePrompt: () => Promise<string | null>;
}

export const StoryboardVideoPanel: React.FC<Props> = ({ prompt, generating, onPromptChange, onGeneratePrompt }) => {
  const [draft, setDraft] = React.useState(prompt);
  React.useEffect(() => setDraft(prompt), [prompt]);

  const handleGenerate = async () => {
    const text = await onGeneratePrompt();
    if (text) { setDraft(text); showToast('视频提示词已生成', 'success'); }
  };

  return (
    <div data-storyboard-video-panel className="space-y-4">
      <p className="text-xs text-text-muted">基于文案与分镜，组装可直接用于视频生成模型的提示词。生成后可复制到「生视频」tab 实际生成视频。</p>
      <div className="flex justify-end">
        <Button variant="primary" onClick={handleGenerate} disabled={generating}>{generating ? '生成中...' : '生成视频提示词'}</Button>
      </div>
      <label className="block">
        <FieldLabel text="视频提示词" />
        <TextArea value={draft} onChange={(e) => setDraft(e.target.value)} rows={8} />
      </label>
      <div className="flex justify-end gap-2">
        <Button variant="quiet" onClick={async () => { onPromptChange(draft); showToast('已保存', 'success'); }}>保存</Button>
      </div>
    </div>
  );
};
```

- [ ] **Step 5: Verify everything compiles**

Run: `cd openclaw_new_launcher && npx tsc --noEmit`
Expected: no errors (the new components reference only existing exports).

- [ ] **Step 6: Commit**

```bash
git add src/components/storyboard/StoryboardScriptPanel.tsx src/components/storyboard/StoryboardShotsPanel.tsx src/components/storyboard/StoryboardAssetPanel.tsx src/components/storyboard/StoryboardVideoPanel.tsx
git commit -m "feat(storyboard): add script/shots/asset/video panels"
```

---

## Task 14: Build StoryboardWorkbench (top-level orchestrator)

**Files:**
- Create: `openclaw_new_launcher/src/components/storyboard/StoryboardWorkbench.tsx`

This wires together: sidebar + target input + step bar + active panel + generate handlers + asset generation via `imageApi`.

- [ ] **Step 1: Create the workbench**

Create `src/components/storyboard/StoryboardWorkbench.tsx`:

```typescript
import React from 'react';
import { Button, FieldLabel, Input, Loading, showToast } from '../common';
import { imageApi, parseErrorText, mediaApi, waitForJob, type MediaConfigSnapshot, type BridgeJob } from '../../services/api';
import { storyboardApi } from '../../services/storyboardApi';
import { STORYBOARD_STEPS } from './storyboardSteps';
import type { StoryboardOptionGroups } from './StoryboardOptionGroups';
import type { StoryboardProject, StoryboardSelections, StoryboardShot, StoryboardParamConfig } from './storyboardTypes';
import {
  emptyProject, loadProjectsIndex, loadProject, saveProject, deleteProject as deleteProjectEntry,
} from './projectStore';
import { StoryboardProjectsSidebar } from './StoryboardProjectsSidebar';
import { StoryboardScriptPanel } from './StoryboardScriptPanel';
import { StoryboardShotsPanel } from './StoryboardShotsPanel';
import { StoryboardAssetPanel } from './StoryboardAssetPanel';
import { StoryboardVideoPanel } from './StoryboardVideoPanel';

const OptionGroups = React.lazy(() => import('./StoryboardOptionGroups').then((m) => ({ default: m.StoryboardOptionGroups })));

function parseShotsJson(text: string): StoryboardShot[] {
  const start = text.indexOf('[');
  const end = text.lastIndexOf(']');
  if (start < 0 || end < 0) return [];
  try {
    const parsed = JSON.parse(text.slice(start, end + 1));
    return Array.isArray(parsed) ? (parsed as StoryboardShot[]) : [];
  } catch {
    return [];
  }
}

function extractAssetPromptsFrontend(shots: StoryboardShot[], project: StoryboardProject) {
  const result = { 人物图: [] as string[], 产品图: [] as string[], 场景图: [] as string[] };
  const moduleMap = { 人物图: '模块六', 产品图: '模块七', 场景图: '模块八' } as const;
  for (const shot of shots) {
    const kind = shot.assetType as keyof typeof result;
    if (!(kind in result)) continue;
    const sel = (project.selections[moduleMap[kind]] || {}) as Record<string, Array<string | boolean>>;
    const styleParts: string[] = [];
    for (const [cat, vals] of Object.entries(sel)) {
      const strings = (vals || []).filter((v): v is string => typeof v === 'string');
      if (strings.length) styleParts.push(`${cat}:${strings.join(',')}`);
    }
    result[kind].push(`镜头${shot.num}：${shot.scene || ''}${styleParts.length ? '；' + styleParts.join('；') : ''}`);
  }
  return result;
}

export const StoryboardWorkbench: React.FC = () => {
  const [entries, setEntries] = React.useState<Array<{ projectId: string; title: string; updatedAt: string }>>([]);
  const [entriesLoading, setEntriesLoading] = React.useState(true);
  const [project, setProject] = React.useState<StoryboardProject | null>(null);
  const [activeStepId, setActiveStepId] = React.useState(0);
  const [paramConfig, setParamConfig] = React.useState<StoryboardParamConfig>({});
  const [paramLoading, setParamLoading] = React.useState(true);
  const [mediaConfig, setMediaConfig] = React.useState<MediaConfigSnapshot | null>(null);
  const [generatingStage, setGeneratingStage] = React.useState<'script' | 'storyboard' | 'videoPrompt' | null>(null);

  const refreshEntries = React.useCallback(async () => {
    setEntriesLoading(true);
    try {
      setEntries(await loadProjectsIndex());
    } catch (error) {
      showToast(parseErrorText(error) || '读取项目列表失败', 'error');
    } finally {
      setEntriesLoading(false);
    }
  }, []);

  const refreshParamConfig = React.useCallback(async () => {
    setParamLoading(true);
    try {
      const { config } = await storyboardApi.getParamConfig();
      setParamConfig(config);
    } catch (error) {
      showToast(parseErrorText(error) || '读取参数配置失败', 'error');
    } finally {
      setParamLoading(false);
    }
  }, []);

  const refreshMediaConfig = React.useCallback(async () => {
    try {
      const { config } = await mediaApi.config();
      setMediaConfig(config);
    } catch {
      setMediaConfig(null);
    }
  }, []);

  React.useEffect(() => {
    void refreshEntries();
    void refreshParamConfig();
    void refreshMediaConfig();
  }, [refreshEntries, refreshParamConfig, refreshMediaConfig]);

  const selectProject = React.useCallback(async (projectId: string) => {
    try {
      const loaded = await loadProject(projectId);
      if (loaded) setProject(loaded);
    } catch (error) {
      showToast(parseErrorText(error) || '读取项目失败', 'error');
    }
  }, []);

  const createProject = React.useCallback(async () => {
    const fresh = emptyProject();
    await saveProject(fresh);
    setProject(fresh);
    setActiveStepId(0);
    await refreshEntries();
  }, [refreshEntries]);

  const persist = React.useCallback(async (next: StoryboardProject) => {
    setProject(next);
    try {
      await saveProject(next);
      await refreshEntries();
    } catch (error) {
      showToast(parseErrorText(error) || '保存项目失败', 'error');
    }
  }, [refreshEntries]);

  const renameProject = React.useCallback(async (projectId: string, title: string) => {
    if (!project || project.projectId !== projectId) return;
    await persist({ ...project, title });
  }, [project, persist]);

  const removeProject = React.useCallback(async (projectId: string) => {
    await deleteProjectEntry(projectId);
    if (project?.projectId === projectId) setProject(null);
    await refreshEntries();
  }, [project, refreshEntries]);

  const setSelection = React.useCallback((module: string, category: string, values: Array<string | boolean>) => {
    if (!project) return;
    const moduleSel = { ...(project.selections[module as keyof StoryboardSelections] || {}) };
    moduleSel[category] = values;
    const next = { ...project, selections: { ...project.selections, [module]: moduleSel } };
    void persist(next);
  }, [project, persist]);

  const generate = React.useCallback(async (stage: 'script' | 'storyboard' | 'videoPrompt') => {
    if (!project) return null;
    setGeneratingStage(stage);
    try {
      const { result } = await storyboardApi.generate({ stage, project });
      if (stage === 'storyboard') {
        const shots = parseShotsJson(result);
        const assetPrompts = extractAssetPromptsFrontend(shots, project);
        await persist({ ...project, storyboard: { shots, generatedAt: new Date().toISOString() }, assetPrompts });
        return shots;
      }
      if (stage === 'script') {
        await persist({ ...project, script: { ...project.script, content: result, generatedAt: new Date().toISOString() } });
      }
      if (stage === 'videoPrompt') {
        await persist({ ...project, videoPrompt: { content: result, generatedAt: new Date().toISOString() } });
      }
      return result;
    } catch (error) {
      showToast(parseErrorText(error) || `${stage} 生成失败`, 'error');
      return null;
    } finally {
      setGeneratingStage(null);
    }
  }, [project, persist]);

  const submitAssetImage = React.useCallback(async (prompt: string, reference: { requestValue: string } | null) => {
    if (!mediaConfig?.image?.baseUrl || !mediaConfig?.image?.hasApiKey) {
      showToast('请先在「生图」tab 配置生图模型', 'error');
      return;
    }
    try {
      const { jobId } = await imageApi.submit({
        baseUrl: mediaConfig.image.baseUrl!,
        apiKey: '',
        prompt,
        size: '1024x1024',
        model: mediaConfig.image.model || undefined,
        editImagePath: reference?.requestValue,
        source: 'storyboard',
      });
      await waitForJob(jobId, { timeoutMs: 10 * 60 * 1000 });
      showToast('图片生成完成，结果已存入媒体库', 'success');
    } catch (error) {
      showToast(parseErrorText(error) || '图片生成失败', 'error');
    }
  }, [mediaConfig]);

  if (paramLoading) {
    return <div className="flex h-full items-center justify-center"><Loading /></div>;
  }

  const step = STORYBOARD_STEPS.find((s) => s.id === activeStepId) || STORYBOARD_STEPS[0];
  const imageReady = Boolean(mediaConfig?.image?.baseUrl && mediaConfig?.image?.hasApiKey);

  return (
    <div data-storyboard-workbench className="flex h-full overflow-hidden">
      <StoryboardProjectsSidebar
        entries={entries}
        activeProjectId={project?.projectId ?? null}
        loading={entriesLoading}
        onRefresh={refreshEntries}
        onSelect={(id) => void selectProject(id)}
        onCreate={() => void createProject()}
        onRename={(id, title) => void renameProject(id, title)}
        onDelete={(id) => void removeProject(id)}
      />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {!project ? (
          <div className="flex flex-1 items-center justify-center text-sm text-text-muted">
           请新建或选择一个项目开始。
          </div>
        ) : (
          <>
            <header className="shrink-0 border-b border-border px-6 py-4">
              <div className="text-xs font-bold tracking-widest text-accent">全案九步</div>
              <h1 className="mt-1 text-2xl font-black text-text">{project.title}</h1>
            </header>
            <nav data-storyboard-step-bar className="flex shrink-0 gap-1 overflow-x-auto border-b border-border px-6 py-2">
              {STORYBOARD_STEPS.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  data-storyboard-step={s.id}
                  onClick={() => setActiveStepId(s.id)}
                  className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold transition ${s.id === activeStepId ? 'bg-accent text-accent-ink' : 'text-text-muted hover:bg-hover'}`}
                >
                  {s.id}. {s.icon} {s.label}
                </button>
              ))}
            </nav>
            <main className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
              {step.id === 0 ? (
                <div className="max-w-2xl space-y-4">
                  <div className="text-sm text-text-muted">{step.goal}</div>
                  <label className="block">
                    <FieldLabel text="目标对象品类" />
                    <Input
                      value={project.target.category}
                      onChange={(e) => setProject({ ...project, target: { ...project.target, category: e.target.value } })}
                      placeholder="如：食品饮料 / 美妆护肤 / 故事文章"
                    />
                  </label>
                  <label className="block">
                    <FieldLabel text="目标对象名称" required />
                    <Input
                      value={project.target.object}
                      onChange={(e) => setProject({ ...project, target: { ...project.target, object: e.target.value } })}
                      placeholder="产品名称 / 场景描述 / 故事文章"
                    />
                  </label>
                  <Button variant="primary" onClick={() => void persist(project)}>保存</Button>
                </div>
              ) : null}

              {step.id >= 1 && step.id <= 3 ? (
                <div className="space-y-4">
                  <div className="text-sm text-text-muted">{step.goal}</div>
                  <React.Suspense fallback={<Loading />}>
                    <OptionGroups
                      step={step}
                      paramConfig={paramConfig}
                      selections={project.selections}
                      onSelectionChange={(module, category, values) => setSelection(module as string, category, values)}
                    />
                  </React.Suspense>
                </div>
              ) : null}

              {step.generateStage === 'script' ? (
                <StoryboardScriptPanel
                  content={project.script.content}
                  generating={generatingStage === 'script'}
                  onContentChange={(content) => { setProject({ ...project, script: { ...project.script, content } }); }}
                  onGenerate={() => generate('script')}
                  onSave={async () => { await saveProject(project); }}
                />
              ) : null}

              {step.generateStage === 'storyboard' ? (
                <StoryboardShotsPanel
                  shots={project.storyboard.shots}
                  assetPrompts={project.assetPrompts || { 人物图: [], 产品图: [], 场景图: [] }}
                  generating={generatingStage === 'storyboard'}
                  scriptContent={project.script.content}
                  onGenerate={() => generate('storyboard')}
                />
              ) : null}

              {(step.module === '模块六' || step.module === '模块七' || step.module === '模块八') && project.assetPrompts ? (
                <div className="space-y-4">
                  <div className="text-sm text-text-muted">{step.goal}</div>
                  <StoryboardAssetPanel
                    kind={step.module === '模块六' ? '人物图' : step.module === '模块七' ? '产品图' : '场景图'}
                    prompts={project.assetPrompts[step.module === '模块六' ? '人物图' : step.module === '模块七' ? '产品图' : '场景图']}
                    imageConfigReady={imageReady}
                    onGenerate={submitAssetImage}
                  />
                </div>
              ) : null}

              {step.generateStage === 'videoPrompt' ? (
                <StoryboardVideoPanel
                  prompt={project.videoPrompt?.content || ''}
                  generating={generatingStage === 'videoPrompt'}
                  onPromptChange={(content) => { setProject({ ...project, videoPrompt: { content } }); }}
                  onGeneratePrompt={() => generate('videoPrompt')}
                />
              ) : null}
            </main>
          </>
        )}
      </div>
    </div>
  );
};
```

- [ ] **Step 2: Verify it compiles**

Run: `cd openclaw_new_launcher && npx tsc --noEmit`
Expected: no errors. Fix any type mismatches that surface (common: `ReferenceImage` import path, `MediaConfigSnapshot` field optionality).

- [ ] **Step 3: Commit**

```bash
git add src/components/storyboard/StoryboardWorkbench.tsx
git commit -m "feat(storyboard): add top-level StoryboardWorkbench orchestrator"
```

---

## Task 15: Add the "全案九步" tab to CreativeMediaPage

**Files:**
- Modify: `openclaw_new_launcher/src/components/creative/CreativeMediaPage.tsx`

- [ ] **Step 1: Extend the tab type and add lazy import**

At the top of `CreativeMediaPage.tsx`, change the tab type:

```typescript
type CreativeTab = 'image' | 'video' | 'storyboard';
```

Add a lazy import near the other imports (top of file):

```typescript
const StoryboardWorkbench = React.lazy(() => import('../storyboard/StoryboardWorkbench').then((m) => ({ default: m.StoryboardWorkbench })));
```

- [ ] **Step 2: Add the third tab button**

Find the existing tab button group (the `<div className="flex rounded-[14px] border ...">` containing the 生图/生视频 buttons, around line 553-570). Add a third button after the 生视频 button:

```tsx
            <button
              data-creative-tab-storyboard
              type="button"
              onClick={() => setTab('storyboard')}
              className={`rounded-[10px] px-5 py-2 text-sm font-black transition ${tab === 'storyboard' ? 'bg-accent text-accent-ink shadow-[0_12px_28px_rgba(8,60,49,0.18)]' : 'text-text-muted hover:text-text'}`}
            >
              全案九步
            </button>
```

- [ ] **Step 3: Render the workbench when storyboard tab is active**

Find the `<main ...>` element. Wrap the existing image/video content so it only shows for those tabs, and add a storyboard branch. Concretely, change the opening of `<main>` content to:

```tsx
      <main className="min-h-0 flex-1 overflow-y-auto px-8 py-7">
        {tab === 'storyboard' ? (
          <React.Suspense fallback={<Loading />}>
            <StoryboardWorkbench />
          </React.Suspense>
        ) : (
          <>
            {/* existing image/video content (the grid + media library) stays here unchanged */}
```

And close the conditional with `</>` and `)}` right before `</main>`. Keep all existing image/video JSX inside the conditional.

- [ ] **Step 4: Verify it compiles and builds**

Run: `cd openclaw_new_launcher && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add src/components/creative/CreativeMediaPage.tsx
git commit -m "feat(storyboard): add 全案九步 tab to CreativeMediaPage"
```

---

## Task 16: Add param-config JSON import to SettingsPage

**Files:**
- Modify: `openclaw_new_launcher/src/components/settings/SettingsPage.tsx`

- [ ] **Step 1: Add state and handler**

Inside the `SettingsPage` component (near the other state like `updateStatus`), add:

```typescript
  const [paramImportBusy, setParamImportBusy] = React.useState(false);
  const [paramImportStatus, setParamImportStatus] = React.useState<{ tone: 'info' | 'success' | 'error'; message: string } | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  const handleImportParamConfig = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setParamImportBusy(true);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const result = await storyboardApi.importParamConfig(parsed);
      const missing = result.warnings?.missing ?? [];
      const message = missing.length
        ? `已导入 ${result.optionCount} 个选项；缺失模块：${missing.join('、')}`
        : `已导入 ${result.optionCount} 个选项`;
      setParamImportStatus({ tone: missing.length ? 'info' : 'success', message });
      showToast(message, missing.length ? 'info' : 'success');
    } catch (error) {
      const message = parseErrorText(error) || '导入失败，请检查 JSON 格式';
      setParamImportStatus({ tone: 'error', message });
      showToast(message, 'error');
    } finally {
      setParamImportBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };
```

Add the imports at the top:

```typescript
import { storyboardApi } from '../../services/storyboardApi';
import { parseErrorText } from '../../services/api';
```

(`showToast` is already imported.)

- [ ] **Step 2: Extend the copy with a storyboard row**

In the `SETTINGS_COPY` constant, for both `'zh-CN'` and `'en-US'`, add a `storyboard` block inside `data`. For `'zh-CN'`:

```typescript
      storyboard: {
        title: '全案九步参数配置',
        desc: '导入 全案九步_参数配置.json，每个选项对应一条系统提示词，用于组合九步生成的上下文。空值由内置默认提示词兜底。',
        importButton: '导入 JSON',
        importing: '导入中...',
      },
```

For `'en-US'`:

```typescript
      storyboard: {
        title: 'Nine-Step Param Config',
        desc: 'Import the nine-step param config JSON. Each option maps to a system prompt used to assemble generation context. Empty values fall back to built-in defaults.',
        importButton: 'Import JSON',
        importing: 'Importing...',
      },
```

Add the matching type to `SettingsCopy['data']`:

```typescript
  storyboard: { title: string; desc: string; importButton: string; importing: string };
```

- [ ] **Step 3: Render the row in the `data` tab**

In the `{activeTab === 'data' ? (...)` block, add a new `<SettingRow>` (e.g., after the developer row):

```tsx
              <SettingRow title={copy.data.storyboard.title} desc={copy.data.storyboard.desc}>
                <div className="space-y-3">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".json,application/json"
                    className="hidden"
                    onChange={(e) => void handleImportParamConfig(e)}
                  />
                  <div className="flex flex-wrap gap-3">
                    <Button variant="primary" disabled={paramImportBusy} onClick={() => fileInputRef.current?.click()}>
                      {paramImportBusy ? copy.data.storyboard.importing : copy.data.storyboard.importButton}
                    </Button>
                  </div>
                  {paramImportStatus ? (
                    <div className={`rounded-xl border px-4 py-3 text-xs font-semibold ${
                      paramImportStatus.tone === 'error'
                        ? 'border-status-danger/30 bg-status-danger/8 text-status-danger'
                        : paramImportStatus.tone === 'success'
                          ? 'border-status-success/25 bg-status-success/10 text-text'
                          : 'border-border bg-surface-alt/55 text-text'
                    }`}>{paramImportStatus.message}</div>
                  ) : null}
                </div>
              </SettingRow>
```

- [ ] **Step 4: Verify it compiles**

Run: `cd openclaw_new_launcher && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add src/components/settings/SettingsPage.tsx
git commit -m "feat(storyboard): add param-config JSON import in Settings"
```

---

## Task 17: Add frontend source-contract test

**Files:**
- Create: `openclaw_new_launcher/python/tests/test_storyboard_workbench_contract.py`

This follows the `test_creative_media_contract.py` pattern — a Python test asserting on `.tsx`/`.ts` source strings.

- [ ] **Step 1: Write the contract test**

Create `python/tests/test_storyboard_workbench_contract.py`:

```python
from __future__ import annotations

import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_ROOT = os.path.join(REPO_ROOT, "src")

CREATIVE_PAGE = os.path.join(SRC_ROOT, "components", "creative", "CreativeMediaPage.tsx")
SETTINGS_PAGE = os.path.join(SRC_ROOT, "components", "settings", "SettingsPage.tsx")
WORKBENCH = os.path.join(SRC_ROOT, "components", "storyboard", "StoryboardWorkbench.tsx")
STEPS = os.path.join(SRC_ROOT, "components", "storyboard", "storyboardSteps.ts")
API_FILE = os.path.join(SRC_ROOT, "services", "storyboardApi.ts")
ROUTES_FILE = os.path.join(REPO_ROOT, "python", "api", "routes_storyboard.py")
SERVICE_FILE = os.path.join(REPO_ROOT, "python", "services", "storyboard.py")


class StoryboardContractTests(unittest.TestCase):
    def setUp(self) -> None:
        with open(CREATIVE_PAGE, "r", encoding="utf-8") as handle:
            self.creative = handle.read()
        with open(SETTINGS_PAGE, "r", encoding="utf-8") as handle:
            self.settings = handle.read()
        with open(WORKBENCH, "r", encoding="utf-8") as handle:
            self.workbench = handle.read()
        with open(STEPS, "r", encoding="utf-8") as handle:
            self.steps = handle.read()
        with open(API_FILE, "r", encoding="utf-8") as handle:
            self.api = handle.read()
        with open(ROUTES_FILE, "r", encoding="utf-8") as handle:
            self.routes = handle.read()
        with open(SERVICE_FILE, "r", encoding="utf-8") as handle:
            self.service = handle.read()

    def test_creative_page_has_storyboard_tab(self) -> None:
        self.assertIn("data-creative-tab-storyboard", self.creative)
        self.assertIn("StoryboardWorkbench", self.creative)
        self.assertIn("'storyboard'", self.creative)

    def test_settings_page_has_import_row(self) -> None:
        self.assertIn("storyboardApi.importParamConfig", self.settings)
        self.assertIn("全案九步参数配置", self.settings)

    def test_workbench_has_step_bar_and_project_sidebar(self) -> None:
        self.assertIn("data-storyboard-workbench", self.workbench)
        self.assertIn("data-storyboard-step-bar", self.workbench)
        self.assertIn("data-storyboard-projects-sidebar", self.workbench)
        self.assertIn("storyboardApi.generate", self.workbench)

    def test_steps_define_all_nine_modules(self) -> None:
        for module in ("模块一", "模块二", "模块三", "模块四", "模块五", "模块六", "模块七", "模块八", "模块九"):
            self.assertIn(module, self.steps)
        self.assertIn("generateStage", self.steps)
        self.assertIn("'script'", self.steps)
        self.assertIn("'storyboard'", self.steps)
        self.assertIn("'videoPrompt'", self.steps)

    def test_api_wrappers_match_routes(self) -> None:
        self.assertIn("/api/storyboard/param-config", self.api)
        self.assertIn("/api/storyboard/import-param-config", self.api)
        self.assertIn("/api/storyboard/generate", self.api)
        self.assertIn("/api/storyboard/param-config", self.routes)
        self.assertIn("/api/storyboard/import-param-config", self.routes)
        self.assertIn("/api/storyboard/generate", self.routes)

    def test_service_has_backfill_and_three_system_templates(self) -> None:
        self.assertIn("DEFAULT_OPTION_HINTS", self.service)
        self.assertIn("GENERIC_HINT_TEMPLATE", self.service)
        self.assertIn("SCRIPT_SYSTEM_TEMPLATE", self.service)
        self.assertIn("STORYBOARD_SYSTEM_TEMPLATE", self.service)
        self.assertIn("VIDEO_PROMPT_SYSTEM_TEMPLATE", self.service)
        self.assertIn("build_context", self.service)
        self.assertIn("extract_asset_prompts", self.service)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the contract test**

Run: `python python/tests/test_storyboard_workbench_contract.py`
Expected: PASS (6 tests). If any assertion fails, the corresponding source file is missing a marker — fix the source, not the test.

- [ ] **Step 3: Commit**

```bash
git add python/tests/test_storyboard_workbench_contract.py
git commit -m "test(storyboard): add frontend source-contract test"
```

---

## Task 18: Final verification

- [ ] **Step 1: Run the full Python test suite (focused on touched areas)**

Run:
```bash
cd openclaw_new_launcher
python python/tests/test_storyboard_service.py
python python/tests/test_routes_storyboard.py
python python/tests/test_storyboard_feature_gate.py
python python/tests/test_storyboard_workbench_contract.py
python python/tests/test_loom_model_client.py
python python/tests/test_commercial_license_feature_gate.py
python python/tests/test_creative_media_contract.py
python python/tests/test_settings_page_contract.py
```
Expected: all PASS.

- [ ] **Step 2: Type-check + build the frontend**

Run:
```bash
cd openclaw_new_launcher
npx tsc --noEmit
npm run build
```
Expected: build succeeds with no errors.

- [ ] **Step 3: Smoke-test the dev app (manual)**

Run: `cd openclaw_new_launcher && npm run tauri dev`
Manually verify:
1. Settings → 数据 → 全案九步参数配置 → import the provided `全案九步_参数配置.json` → see "已导入 N 个选项".
2. 创作 → 全案九步 tab → 新建项目 → fill 目标对象 → save.
3. Select a few options in 模块一/二/三, then 模块四 → 生成文案 → see generated text appear in the textarea (requires model account login; if not logged in, see a friendly error).
4. 模块五 → 生成分镜 → see shots table populate + 人物/产品/场景 prompt cards.
5. 模块六/七/八 → see the extracted prompts selectable; generate (requires image config).

- [ ] **Step 4: Commit any final fixes**

If the smoke test surfaced fixes, commit them:
```bash
git add -A
git commit -m "fix(storyboard): address smoke-test findings"
```

- [ ] **Step 5: Final commit (if not already committed in step 4)**

The implementation is complete; no commit needed if step 4 was empty.

---

## Notes for the implementer

- **`imageApi.submit` with empty apiKey**: when `mediaConfig.image.hasApiKey` is true, the key is stored server-side; passing `apiKey: ''` is the existing pattern (see `CreativeMediaPage.tsx` `submitImage`). Keep it.
- **`configApi` path resolution**: paths like `.openclaw/nine-step/projects/index.json` resolve under `data/` via `_safe_config_path`. If a project file fails to load, the sidebar should degrade gracefully (the index still lists it).
- **Lazy loading**: `StoryboardWorkbench` and `StoryboardOptionGroups` are `React.lazy` to keep the initial creative page bundle small — match the existing lazy pattern in `features/pages.tsx`.
- **i18n**: the storyboard UI is Chinese-only for now (matches the docx/source). The settings row is bilingual to match the existing `SettingsPage` convention.
