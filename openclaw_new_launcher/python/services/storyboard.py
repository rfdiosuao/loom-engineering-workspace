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
    section_lines: list[str] = []
    for category, options in selections.items():
        if not isinstance(options, list):
            continue
        for option in options:
            if isinstance(option, bool):
                # toggle controls: only mention when on
                if option:
                    section_lines.append(f"【{module} · {category}】已开启")
                continue
            option_text = str(option)
            hint = resolve_hint(param_config, module, category, option_text)
            section_lines.append(f"【{module} · {category} · {option_text}】\n{hint}")
    # Always emit a section header for the module, even when it has no selections,
    # so downstream prompts can see which modules were considered.
    if section_lines:
        parts.append(f"【{module}】\n" + "\n\n".join(section_lines))
    else:
        parts.append(f"【{module}】（暂无具体选项）")


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
