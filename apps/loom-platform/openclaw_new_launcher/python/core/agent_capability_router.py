"""Deterministic two-stage capability routing for the central agent."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from core.agent_capabilities import CAPABILITY_OPERATION_KEYS


Json = dict[str, Any]


_BROAD_INTENT_PATTERNS = (
    "全部能力",
    "所有能力",
    "完整能力",
    "能力目录",
    "能力列表",
    "已开放能力",
    "已连接能力",
    "连接的能力",
    "可以掌握什么",
    "你会什么",
    "你能做什么",
    "what can you do",
    "what capabilities",
    "connected capabilities",
    "all capabilities",
    "capability catalog",
)

_CAPABILITY_CATALOG_NAME = "loom.capabilities.list"
_LEGACY_CAPABILITY_CATALOG_SUFFIX = ".loom_cli_commands"

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "media": (
        "生图", "图片", "海报", "封面", "素材", "相册", "生视频", "视频", "image", "video", "media",
    ),
    "phone": (
        "手机", "设备", "截图", "读屏", "亮屏", "解锁", "点击", "输入", "返回键", "主页键", "发布",
        "抖音", "小红书", "快手", "微博", "微信", "qq", "闲鱼", "咸鱼", "淘宝", "京东", "拼多多",
        "美团", "知乎", "boss直聘", "飞书", "钉钉", "浏览器", "相机", "相册",
        "phone", "device", "screenshot", "publish",
    ),
    "matrix": (
        "矩阵", "多台", "批量", "设备组", "群控", "急停", "下发任务", "全部设备", "所有设备",
        "全部手机", "所有手机", "每台手机", "每一台手机", "全部在线", "所有在线", "在线设备",
        "同时下发", "matrix", "fleet", "campaign",
    ),
    "acquisition": (
        "获客", "线索", "招聘", "简历", "boss直聘", "飞书", "客户", "lead", "acquisition", "feishu", "recruit",
    ),
    "schedule": ("定时", "计划任务", "日程", "调度", "schedule", "cron"),
    "models": ("模型", "供应商", "api key", "apikey", "provider", "model"),
    "account": ("账号", "登录", "订阅", "额度", "账户", "account", "login", "quota"),
    "license": ("授权", "授权码", "许可证", "激活码", "商业授权", "license", "activation"),
    "agent": (
        "智能体", "agent", "runtime", "运行时", "技能", "skill", "mcp", "cli",
        "codex", "claude code", "claudecode", "openclaw", "opencode", "hermes",
    ),
    "settings": ("设置", "主题", "深色", "浅色", "更新", "版本", "settings", "theme", "update", "version"),
    "diagnostics": (
        "诊断", "日志", "报错", "错误", "健康", "修复", "diagnostic", "log", "error",
    ),
}

_TIME_NUMBER = r"(?:[0-2]?\d|[零一二两三四五六七八九十]{1,3})"
_SCHEDULE_INTENT_PATTERNS = (
    re.compile(
        rf"(?:今天|明天|后天|今晚|每天|每周|每月).{{0,12}}"
        rf"(?:{_TIME_NUMBER}\s*(?:点|时)|执行|运行|发布|开始)"
    ),
    re.compile(
        rf"{_TIME_NUMBER}\s*(?:点|时)(?:\s*{_TIME_NUMBER}\s*分)?"
        rf".{{0,8}}(?:执行|运行|发布|开始)"
    ),
    re.compile(
        rf"(?:稍后|过\s*{_TIME_NUMBER}\s*(?:分钟|小时)|"
        rf"{_TIME_NUMBER}\s*(?:分钟|小时)后).{{0,8}}(?:执行|运行|发布|开始|任务)"
    ),
)

_MULTI_DEVICE_TARGET_PATTERN = re.compile(
    r"(?:[2-9]\d*|[二两三四五六七八九十百]+)\s*(?:台|部)\s*(?:手机|设备)"
)
_NAMED_DEVICE_GROUP_TARGET_PATTERN = re.compile(
    r"(?:传到|传给|发到|发给|下发到|下发给|同步到|导入到).{1,24}(?:设备组|分组|组)"
)

_MEDIA_REUSE_TERMS = (
    "刚才", "之前", "已有", "现有", "已经生成", "上次", "那张", "这张", "那个视频",
    "这个视频", "本地素材", "本地图片", "本地视频",
)
_MEDIA_REGENERATE_TERMS = (
    "重新生成", "再生成", "重新做", "再做一张", "另生成", "新生成", "生成新版", "重绘",
    "编辑", "修改", "换背景", "改颜色", "调整风格",
)
_MEDIA_CONTENT_TERMS = ("海报", "图片", "视频", "封面", "素材", "壁纸", "文案")
_MEDIA_CONFIG_TERMS = (
    "生成配置", "生图配置", "视频配置", "模型配置", "api", "接口", "密钥", "key",
)
_MEDIA_EXECUTION_TERMS = (
    "生成一张", "生成一个", "生成一段", "生成图片", "生成视频", "生成海报", "开始生图", "帮我生图",
    "生一张", "制作", "创建", "画一张", "重绘", "编辑", "修改", "换背景", "改颜色", "调整风格",
)
_IMAGE_GENERATION_ACTION_TERMS = (
    "生成一张", "生成图片", "生成海报", "生成封面", "画一张", "重绘", "编辑", "修改", "换背景",
    "改颜色", "调整风格",
)
_VIDEO_GENERATION_ACTION_TERMS = (
    "生成视频", "生成一段", "做成视频", "转成视频", "图生视频", "开始生视频",
)
_IMAGE_MEDIA_TERMS = ("图片", "海报", "封面", "壁纸", "插画", "头像", "照片", "图像", "生图")
_VIDEO_MEDIA_TERMS = ("视频", "短片", "动画", "片段", "生视频")
_MEDIA_CONFIG_CAPABILITY_MARKERS = (
    ".loom_media_config",
    ".loom_media_save_",
    ".loom_media_test_",
)
_MEDIA_EXECUTION_CAPABILITIES = frozenset(
    {
        "loom.media.asset.transfer",
        "loom.media.assets.list",
        "loom.media.image.generate",
        "loom.media.video.generate",
    }
)
_ALBUM_TRANSFER_TERMS = (
    "手机相册", "传到相册", "传入相册", "保存到手机", "导入手机", "同步到手机",
    "传到手机", "传给手机",
)
_OUTBOUND_PUBLISH_ACTION_TERMS = (
    "发布", "发帖", "草稿", "发到", "发去", "上传到", "投放到", "推文",
)
_OUTBOUND_PUBLISH_DESTINATION_TERMS = (
    "抖音", "小红书", "快手", "微博", "朋友圈", "视频号", "公众号", "douyin", "xiaohongshu",
)
_MEDIA_TRANSFER_ACTION_TERMS = (
    "传到", "传给", "传输", "同步到", "导入到", "保存到手机", "发到手机", "发给手机",
)
_MATRIX_DISPATCH_ACTION_TERMS = (
    "下发", "执行", "运行", "打开", "启动", "点击", "输入", "控制", "操作", "发布", "发给", "发到",
)
_MATRIX_CANCEL_TERMS = ("取消", "终止", "停止任务", "急停")
_MATRIX_RETRY_TERMS = ("重试", "再试", "重新执行")
_MATRIX_SCREEN_TERMS = ("截图", "屏幕", "画面")
_MATRIX_STATUS_TERMS = (
    "矩阵状态", "矩阵进度", "任务状态", "执行状态", "任务进度", "执行进度", "运行情况", "查看进度",
)
_MATRIX_EXPERIENCE_TERMS = ("运行经验", "经验报告", "复盘经验")
_MATRIX_TEMPLATE_TERMS = ("任务模板", "执行模板", "模板任务")
_PHONE_DIRECT_CONTROL_TERMS = (
    "打开", "启动", "点击", "输入", "返回", "主页", "解锁", "亮屏", "切换到", "控制", "操作",
    "执行手机任务", "手机快速任务", "执行手机模板任务", "手机模板任务",
)
_PHONE_READ_TERMS = (
    "截图", "读屏", "读取屏幕", "读取手机屏幕", "查看屏幕", "查看手机屏幕", "当前画面", "屏幕内容",
)
_PHONE_STATUS_TERMS = (
    "手机状态", "设备状态", "检测手机", "检查手机", "查看手机", "哪些手机", "是否在线", "连接情况",
)
_PHONE_EVENT_START_TERMS = ("启动", "开始", "开启")
_PHONE_EVENT_STOP_TERMS = ("停止", "关闭", "终止")
_PHONE_EVENT_STATUS_TERMS = ("状态", "查看", "检查", "是否运行")
_SETTINGS_THEME_TERMS = ("主题", "深色", "浅色", "界面风格")
_SETTINGS_THEME_LIST_TERMS = ("主题列表", "查看界面主题", "有哪些主题", "可用主题")
_SETTINGS_UPDATE_TERMS = ("更新", "新版本", "升级")
_SETTINGS_UPDATE_INSTALL_TERMS = ("安装更新", "安装麓鸣更新", "立即更新", "马上更新", "开始更新", "升级到")
_MEDIA_CONFIG_SAVE_TERMS = (
    "保存配置",
    "保存图片生成配置",
    "保存视频生成配置",
    "设置接口",
    "配置接口",
    "修改配置",
    "更新配置",
    "接入",
)
_MEDIA_CONFIG_TEST_TERMS = ("测试", "验证", "检查")
_PHONE_REPAIR_TERMS = (
    "连接失败", "连接异常", "离线", "不可达", "授权失效", "修复", "诊断", "adb", "无障碍",
)
_PHONE_EVENT_TERMS = (
    "事件同步", "事件流", "手机事件", "监听事件", "实时事件", "events", "event stream",
)
_PHONE_NON_PUBLISH_ACTION_TERMS = (
    "打开", "启动", "点击", "输入", "截图", "查看", "读取", "读屏", "状态", "检测", "连接",
    "设置", "返回", "主页", "解锁", "亮屏", "修复", "诊断", "相册", "传到手机", "同步到手机",
)
_PHONE_SETTINGS_ACTION_TERMS = ("打开", "进入", "点击", "查看", "返回", "切换到", "启动")
_LOOM_SETTINGS_TERMS = (
    "麓鸣设置", "工作台设置", "界面设置", "主题", "深色", "浅色", "更新麓鸣", "版本更新",
)
_ACQUISITION_SUBJECT_TERMS = ("招聘", "招工", "简历", "候选人", "人才")
_ACQUISITION_OPERATION_TERMS = (
    "筛选", "搜索", "查找", "收集", "获取", "导入", "跟进", "联系", "打招呼", "沟通",
    "投递", "职位", "线索", "获客", "客户", "招聘任务", "自动招聘", "boss直聘",
)

_CORE_NAME_PATTERNS = (
    ".capabilities.",
    ".capability.",
    ".jobs.get",
    ".jobs.list",
    ".logs.tail",
    "loom.status",
    "loom_status",
)


def route_capabilities(
    request: Mapping[str, Any],
    capabilities: Sequence[Mapping[str, Any]],
    checkpoint: Mapping[str, Any] | None = None,
) -> tuple[list[Json], Json]:
    """Return a focused catalog, with an automatic full-catalog safety fallback."""

    available = [dict(item) for item in capabilities if isinstance(item, Mapping)]
    checkpoint = checkpoint or {}
    text = _request_text(request)
    folded = text.casefold()
    explicit_mode = str(request.get("capabilityRoutingMode") or "").strip().lower()
    hinted = _available_capability_hints(request, available)

    catalog_capability = _capability_catalog(available)
    if (
        explicit_mode != "full"
        and any(pattern in folded for pattern in _BROAD_INTENT_PATTERNS)
        and catalog_capability is not None
    ):
        catalog_name = str(catalog_capability.get("name") or "").strip()
        if _has_capability_result(checkpoint, catalog_name):
            return [catalog_capability], _routing_metadata(
                "response_only",
                set(),
                len(available),
                1,
                "capability_catalog_available",
                hinted,
                toolChoice="none",
            )
        return [catalog_capability], _routing_metadata(
            "forced",
            set(),
            len(available),
            1,
            "capability_catalog_required",
            hinted,
            forcedCapability=catalog_name,
        )

    fallback_reason = ""
    if explicit_mode == "full":
        fallback_reason = "requested_full_catalog"
    elif int(checkpoint.get("toolSelectionRepairAttempts", 0) or 0) > 0:
        fallback_reason = "selection_repair"
    elif any(pattern in folded for pattern in _BROAD_INTENT_PATTERNS):
        fallback_reason = "broad_capability_intent"

    domains = _intent_domains(folded, request)
    if not fallback_reason and not domains and not hinted:
        fallback_reason = "ambiguous_intent"

    if fallback_reason:
        return available, _routing_metadata(
            "full", domains, len(available), len(available), fallback_reason, hinted
        )

    selected: list[Json] = []
    for capability in available:
        capability_domains = _capability_domains(capability)
        if (
            str(capability.get("name") or "") in hinted
            or capability_domains.intersection(domains)
            or _is_core_capability(capability)
        ):
            selected.append(capability)

    selected = _prune_capabilities_for_intent(folded, selected, set(hinted), domains)

    if not selected:
        return available, _routing_metadata(
            "full", domains, len(available), len(available), "empty_route", hinted
        )
    if len(selected) >= len(available):
        return available, _routing_metadata(
            "full", domains, len(available), len(available), "all_domains_selected", hinted
        )
    reason = "intent_match" if domains else "explicit_hint"
    return selected, _routing_metadata(
        "focused", domains, len(available), len(selected), reason, hinted
    )


def _available_capability_hints(
    request: Mapping[str, Any],
    capabilities: Sequence[Mapping[str, Any]],
) -> list[str]:
    raw_hints = request.get("capabilityHints")
    if not isinstance(raw_hints, list):
        return []
    available_names = {
        str(capability.get("name") or "").strip()
        for capability in capabilities
        if str(capability.get("name") or "").strip()
    }
    return sorted(
        {
            hint.strip()
            for hint in raw_hints
            if isinstance(hint, str) and hint.strip() in available_names
        }
    )


def _capability_catalog(capabilities: Sequence[Mapping[str, Any]]) -> Json | None:
    preferred: Json | None = None
    for capability in capabilities:
        name = str(capability.get("name") or "").strip()
        display_name = str(capability.get("displayName") or "").strip()
        if name == _CAPABILITY_CATALOG_NAME:
            return dict(capability)
        if display_name == "查看能力目录" or name.endswith(_LEGACY_CAPABILITY_CATALOG_SUFFIX):
            preferred = dict(capability)
    return preferred


def _has_capability_result(checkpoint: Mapping[str, Any], capability_name: str) -> bool:
    tool_results = checkpoint.get("toolResults")
    if not isinstance(tool_results, list):
        return False
    return any(
        isinstance(item, Mapping)
        and str(item.get("capability") or "").strip() == capability_name
        for item in tool_results
    )


def _request_text(request: Mapping[str, Any]) -> str:
    chunks: list[str] = []
    for key in ("prompt", "input", "text", "task", "message", "userMessage"):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            chunks.append(value.strip())
    messages = request.get("messages")
    if isinstance(messages, list):
        for item in messages[-4:]:
            if not isinstance(item, Mapping) or str(item.get("role") or "user") != "user":
                continue
            content = item.get("content")
            if isinstance(content, str):
                chunks.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, Mapping) and isinstance(block.get("text"), str):
                        chunks.append(str(block["text"]))
    return "\n".join(chunks)[:12000]


def _intent_domains(text: str, request: Mapping[str, Any]) -> set[str]:
    domains = {
        domain
        for domain, keywords in _DOMAIN_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    }
    if any(pattern.search(text) for pattern in _SCHEDULE_INTENT_PATTERNS):
        domains.add("schedule")
    if not domains and any(term in text for term in ("失败", "状态", "异常", "更新")):
        domains.add("diagnostics")
    if _MULTI_DEVICE_TARGET_PATTERN.search(text) or _NAMED_DEVICE_GROUP_TARGET_PATTERN.search(text):
        domains.add("matrix")
    if (
        any(term in text for term in _PHONE_REPAIR_TERMS)
        and any(term in text for term in ("手机", "设备", "phone", "adb", "无障碍"))
        and not any(term in text for term in ("系统诊断", "环境诊断", "导出诊断", "诊断包", "运行日志"))
    ):
        domains.discard("diagnostics")
    if _is_phone_settings_navigation(text):
        domains.discard("settings")
    if _is_recruitment_media_subject(text):
        domains.discard("acquisition")
    scope = request.get("requestScope")
    if isinstance(scope, Mapping):
        _add_target_domains(domains, scope)
        for key in ("target", "targets"):
            target = scope.get(key)
            if isinstance(target, Mapping):
                _add_target_domains(domains, target)
    for key in ("target", "targets"):
        target = request.get(key)
        if isinstance(target, Mapping):
            _add_target_domains(domains, target)
    return domains


def _prune_capabilities_for_intent(
    text: str,
    capabilities: Sequence[Json],
    hinted: set[str],
    domains: set[str],
) -> list[Json]:
    reuse_media = "media" in {_domain for item in capabilities for _domain in _capability_domains(item)} and any(
        term in text for term in _MEDIA_REUSE_TERMS
    )
    regenerate_media = any(term in text for term in _MEDIA_REGENERATE_TERMS)
    media_config = any(term in text for term in _MEDIA_CONFIG_TERMS)
    media_execution = any(term in text for term in _MEDIA_EXECUTION_TERMS)
    image_generation = any(term in text for term in _IMAGE_GENERATION_ACTION_TERMS)
    video_generation = any(term in text for term in _VIDEO_GENERATION_ACTION_TERMS)
    image_media = any(term in text for term in _IMAGE_MEDIA_TERMS)
    video_media = any(term in text for term in _VIDEO_MEDIA_TERMS)
    album_transfer = any(term in text for term in _ALBUM_TRANSFER_TERMS)
    media_transfer = album_transfer or any(term in text for term in _MEDIA_TRANSFER_ACTION_TERMS)
    outbound_publish = any(term in text for term in _OUTBOUND_PUBLISH_ACTION_TERMS)
    if album_transfer and not any(term in text for term in _OUTBOUND_PUBLISH_DESTINATION_TERMS):
        outbound_publish = False
    phone_repair = any(term in text for term in _PHONE_REPAIR_TERMS)
    phone_events = any(term in text for term in _PHONE_EVENT_TERMS)
    non_publish_phone_action = any(term in text for term in _PHONE_NON_PUBLISH_ACTION_TERMS)
    matrix_intent = "matrix" in domains
    media_flow = reuse_media or media_execution or media_transfer
    matrix_cancel = any(term in text for term in _MATRIX_CANCEL_TERMS)
    matrix_retry = any(term in text for term in _MATRIX_RETRY_TERMS)
    matrix_screen = any(term in text for term in _MATRIX_SCREEN_TERMS)
    matrix_status = any(term in text for term in _MATRIX_STATUS_TERMS)
    matrix_experience = any(term in text for term in _MATRIX_EXPERIENCE_TERMS)
    matrix_template = any(term in text for term in _MATRIX_TEMPLATE_TERMS)
    matrix_dispatch = (
        matrix_intent
        and any(term in text for term in _MATRIX_DISPATCH_ACTION_TERMS)
        and not media_flow
        and not matrix_cancel
        and not matrix_retry
    )
    phone_direct = any(term in text for term in _PHONE_DIRECT_CONTROL_TERMS)
    phone_read = any(term in text for term in _PHONE_READ_TERMS)
    phone_status = any(term in text for term in _PHONE_STATUS_TERMS)
    phone_event_start = any(term in text for term in _PHONE_EVENT_START_TERMS)
    phone_event_stop = any(term in text for term in _PHONE_EVENT_STOP_TERMS)
    phone_event_status = any(term in text for term in _PHONE_EVENT_STATUS_TERMS)
    settings_theme = any(term in text for term in _SETTINGS_THEME_TERMS)
    settings_theme_list = any(term in text for term in _SETTINGS_THEME_LIST_TERMS)
    settings_update = any(term in text for term in _SETTINGS_UPDATE_TERMS)
    settings_update_install = any(term in text for term in _SETTINGS_UPDATE_INSTALL_TERMS)
    media_config_save = any(term in text for term in _MEDIA_CONFIG_SAVE_TERMS)
    media_config_test = any(term in text for term in _MEDIA_CONFIG_TEST_TERMS)

    selected: list[Json] = []
    for capability in capabilities:
        name = str(capability.get("name") or "").strip()
        operation = CAPABILITY_OPERATION_KEYS.get(name, name)
        if not name or name in hinted or _is_core_capability(capability):
            selected.append(capability)
            continue
        if reuse_media and not regenerate_media and operation == "loom.media.image.generate" and not image_generation:
            continue
        if reuse_media and not regenerate_media and operation == "loom.media.video.generate" and not video_generation:
            continue
        if image_media and not video_media and operation == "loom.media.video.generate":
            continue
        if video_media and not image_media and operation == "loom.media.image.generate":
            continue
        if operation == "loom.media.asset.transfer" and not media_transfer:
            continue
        if media_execution and not reuse_media and not media_transfer and operation == "loom.media.assets.list":
            continue
        if media_config and not media_execution and operation in _MEDIA_EXECUTION_CAPABILITIES:
            continue
        if not media_config and any(marker in name for marker in _MEDIA_CONFIG_CAPABILITY_MARKERS):
            continue
        if ".loom_media_save_image_config" in name and not (media_config_save and image_media):
            continue
        if ".loom_media_save_video_config" in name and not (media_config_save and video_media):
            continue
        if ".loom_media_test_image" in name and not (image_media and media_config_test):
            continue
        if ".loom_media_test_video" in name and not (video_media and media_config_test):
            continue
        if operation == "loom.matrix.dispatch" and not matrix_dispatch:
            continue
        if operation == "loom.matrix.cancel" and not matrix_cancel:
            continue
        if operation == "loom.matrix.retry" and not matrix_retry:
            continue
        if operation == "loom.matrix.screenshot" and not matrix_screen:
            continue
        if operation in {"loom.matrix.status", "loom.cli.matrix.watch"} and not (
            matrix_dispatch or matrix_cancel or matrix_retry or matrix_screen or matrix_status
        ):
            continue
        if operation == "loom.cli.experience.report" and not matrix_experience:
            continue
        if operation == "loom.cli.template.run" and not matrix_template:
            continue
        if operation in {"loom.cli.phone.quick-task", "loom.mcp.loom.loom_phone_template_task"}:
            if phone_events or matrix_dispatch or (media_flow and not phone_direct) or not phone_direct:
                continue
        if operation == "loom.cli.phone.read" and (matrix_intent or not phone_read):
            continue
        if operation == "loom.cli.phone.status" and (matrix_intent or not (phone_status or phone_repair)):
            continue
        if name == "loom.phone.publish" and not outbound_publish and (
            non_publish_phone_action or matrix_intent or phone_events or phone_repair or phone_status
        ):
            continue
        if ".loom_phone_adb_doctor" in name and not phone_repair:
            continue
        if ".loom_phone_events_" in name:
            if not phone_events:
                continue
            if name.endswith("_start") and not phone_event_start:
                continue
            if name.endswith("_stop") and not phone_event_stop:
                continue
            if name.endswith("_status") and not (
                phone_event_status or (not phone_event_start and not phone_event_stop)
            ):
                continue
        if ".loom_settings_theme_list" in name and not settings_theme_list:
            continue
        if ".loom_settings_theme" in name and not name.endswith("_list") and not settings_theme:
            continue
        if ".loom_settings_update_check" in name and not settings_update:
            continue
        if ".loom_settings_update_install" in name and not settings_update_install:
            continue
        selected.append(capability)
    return selected


def _is_phone_settings_navigation(text: str) -> bool:
    return (
        "设置" in text
        and any(term in text for term in ("手机", "phone", "device", "设备"))
        and any(term in text for term in _PHONE_SETTINGS_ACTION_TERMS)
        and not any(term in text for term in _LOOM_SETTINGS_TERMS)
    )


def _is_recruitment_media_subject(text: str) -> bool:
    return (
        any(term in text for term in _ACQUISITION_SUBJECT_TERMS)
        and any(term in text for term in _MEDIA_CONTENT_TERMS)
        and not any(term in text for term in _ACQUISITION_OPERATION_TERMS)
    )


def _add_target_domains(domains: set[str], target: Mapping[str, Any]) -> None:
    raw_device_ids = target.get("deviceIds") or target.get("devices")
    device_ids = raw_device_ids if isinstance(raw_device_ids, list) else []
    has_single_device = bool(target.get("deviceId")) or len(device_ids) == 1
    has_multiple_devices = len(device_ids) > 1
    has_matrix_target = bool(
        target.get("groupIds")
        or target.get("groups")
        or target.get("groupId")
        or target.get("group")
        or target.get("allOnline") is True
    )
    if has_single_device and not has_matrix_target:
        domains.add("phone")
    if has_multiple_devices or has_matrix_target:
        domains.add("matrix")


def _capability_domains(capability: Mapping[str, Any]) -> set[str]:
    haystack = " ".join(
        str(capability.get(key) or "")
        for key in ("name", "domain", "displayName", "description", "source")
    ).casefold()
    tokens = set(filter(None, re.split(r"[^a-z0-9]+", haystack)))
    domains: set[str] = set()
    aliases = {
        "image": "media",
        "video": "media",
        "media": "media",
        "asset": "media",
        "phone": "phone",
        "device": "phone",
        "publish": "phone",
        "matrix": "matrix",
        "fleet": "matrix",
        "campaign": "matrix",
        "acquisition": "acquisition",
        "lead": "acquisition",
        "feishu": "acquisition",
        "schedule": "schedule",
        "cron": "schedule",
        "model": "models",
        "models": "models",
        "provider": "models",
        "account": "account",
        "auth": "account",
        "agent": "agent",
        "runtime": "agent",
        "skill": "agent",
        "diagnostics": "diagnostics",
        "diagnostic": "diagnostics",
        "logs": "diagnostics",
    }
    for token in tokens:
        mapped = aliases.get(token)
        if mapped:
            domains.add(mapped)
    metadata_domain = str(capability.get("domain") or "").strip().casefold()
    if metadata_domain:
        domains.add(aliases.get(metadata_domain, metadata_domain))
    return domains


def _is_core_capability(capability: Mapping[str, Any]) -> bool:
    name = str(capability.get("name") or "").casefold()
    normalized = f".{name}."
    return any(pattern in normalized for pattern in _CORE_NAME_PATTERNS)


def _routing_metadata(
    mode: str,
    domains: set[str],
    total: int,
    selected: int,
    reason: str,
    hinted: Sequence[str] = (),
    **extras: Any,
) -> Json:
    return {
        "schema": "loom.agent.capability-routing.v1",
        "mode": mode,
        "domains": sorted(domains),
        "total": total,
        "selected": selected,
        "reason": reason,
        "hinted": list(hinted),
        **extras,
    }


__all__ = ["route_capabilities"]
