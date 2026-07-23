"""Deterministic two-stage capability routing for the central agent."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from core.agent_capabilities import CAPABILITY_OPERATION_KEYS
from core.agent_language import has_positive_term as _has_positive_term


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
_RESPONSE_ONLY_PHRASES = frozenset({
    "你好", "您好", "嗨", "哈喽", "hello", "hi", "在吗", "谢谢", "感谢", "好的", "好", "嗯", "知道了",
    "你是谁", "介绍一下你自己", "介绍你自己", "自我介绍",
})

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "media": (
        "生图", "图片", "海报", "封面", "素材", "相册", "生视频", "视频", "媒体", "image", "video", "media",
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
        "同时下发", "任务模板", "运行经验", "经验报告", "复盘经验", "matrix", "fleet", "campaign",
    ),
    "acquisition": (
        "获客", "拓客", "线索", "招聘", "简历", "boss直聘", "客户", "lead", "acquisition", "recruit",
    ),
    "integration": (
        "飞书集成", "飞书线索表", "飞书同步", "绑定飞书", "创建飞书", "安装飞书", "登录飞书",
        "测试写入飞书", "feishu integration",
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
        "诊断", "日志", "报错", "错误", "健康", "修复", "运行环境", "diagnostic", "log", "error",
    ),
    "jobs": (
        "任务列表", "作业列表", "后台任务", "最近任务", "任务详情", "作业详情",
        "job list", "jobs list", "job detail", "job status", "job id",
    ),
    "system": (
        "麓鸣状态", "工作台状态", "系统状态", "整体状态", "运行状态", "健康状态", "loom status",
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
    "矩阵状态", "任务状态", "执行状态", "运行情况",
)
_MATRIX_WATCH_TERMS = ("矩阵进度", "任务进度", "执行进度", "查看进度", "持续监控", "持续跟踪", "跟踪矩阵")
_MATRIX_EXPERIENCE_TERMS = ("运行经验", "经验报告", "复盘经验")
_MATRIX_TEMPLATE_TERMS = ("任务模板", "执行模板", "模板任务")
_PHONE_DIRECT_CONTROL_TERMS = (
    "打开", "启动", "点击", "输入", "返回", "主页", "解锁", "亮屏", "切换到", "控制", "操作",
    "执行手机任务", "手机快速任务", "执行手机模板任务", "手机模板任务",
)
_PHONE_TEMPLATE_TERMS = (
    "执行手机模板任务", "手机模板任务", "模板任务", "返回键", "主页键", "回到主页", "返回上一页",
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
_PHONE_SETTINGS_ACTION_TERMS = ("打开", "进入", "点击", "查看", "返回", "切换到", "启动")
_LOOM_SETTINGS_TERMS = (
    "麓鸣设置", "工作台设置", "界面设置", "主题", "深色", "浅色", "更新麓鸣", "版本更新",
)
_ACQUISITION_SUBJECT_TERMS = ("招聘", "招工", "简历", "候选人", "人才")
_ACQUISITION_OPERATION_TERMS = (
    "筛选", "搜索", "查找", "收集", "获取", "导入", "跟进", "联系", "打招呼", "沟通",
    "投递", "职位", "线索", "获客", "客户", "招聘任务", "自动招聘", "boss直聘",
)

_SETTINGS_THEME_SET_TERMS = (
    "设置界面主题", "设置深色主题", "设置浅色主题", "设置为", "设置成", "设为", "改成", "改为", "切换到",
    "应用主题", "修改主题", "更换主题",
)
_MODEL_LIST_TERMS = (
    "查看模型配置", "列出当前模型", "查看当前模型", "当前模型", "模型列表", "有哪些模型", "可用模型", "model list",
)
_MODEL_SELECT_TERMS = (
    "选择默认模型", "设置默认模型", "修改默认模型", "切换默认模型", "默认模型改成", "默认模型改为",
)
_AGENT_MODEL_STATUS_TERMS = ("查看智能体模型状态", "智能体模型状态", "agent model status")
_AGENT_MODEL_APPLY_TERMS = ("应用智能体模型配置", "设置智能体模型", "配置智能体模型", "应用 agent 模型")
_AGENT_MODEL_ROLLBACK_TERMS = ("回滚智能体模型配置", "恢复智能体模型配置", "回退智能体模型")
_WIRE_CURRENT_TERMS = ("查看模型接线配置", "模型接线配置", "当前接线配置")
_WIRE_CUSTOM_TERMS = ("配置自定义模型接口", "自定义模型接口", "修改模型接口", "设置模型接口")
_WIRE_SYNC_TERMS = ("同步模型接线配置", "同步模型配置")
_WIRE_VERIFY_TERMS = ("验证模型接口", "测试模型接口", "检查模型接口")
_WIRE_ROLLBACK_TERMS = ("回滚模型接线配置", "恢复模型接线配置", "回退模型接线")
_ACCOUNT_CURRENT_TERMS = ("查看当前账户", "查看当前账号", "当前账户", "当前账号", "账户状态", "账号状态")
_ACCOUNT_SUBSCRIPTION_TERMS = ("查看账户订阅", "查看账号订阅", "账户订阅", "账号订阅", "订阅状态", "订阅", "额度")
_ACCOUNT_SEND_CODE_TERMS = ("发送登录验证码", "发送验证码", "获取登录验证码", "获取验证码")
_ACCOUNT_LOGIN_CODE_TERMS = ("使用验证码登录", "验证码登录")
_ACCOUNT_LOGIN_PASSWORD_TERMS = ("使用密码登录", "密码登录")
_ACCOUNT_LOGIN_GENERIC_TERMS = ("登录账户", "登录账号", "账户登录", "账号登录")
_ACCOUNT_LOGOUT_TERMS = ("退出当前账户", "退出当前账号", "退出登录", "注销登录")
_ACCOUNT_SYNC_TERMS = ("同步账户与模型", "同步账号与模型", "同步账户", "同步账号")
_ACQUISITION_RUN_TERMS = (
    "启动获客智能体任务", "启动获客任务", "开始获客任务", "运行获客任务", "执行获客任务", "招聘获客任务", "自动招聘",
    "筛选招聘简历", "筛选简历", "自动筛选简历", "筛选候选人", "整理候选人", "招聘自动化",
    "自动拓客", "拓客", "帮我找客户", "找客户", "寻找客户",
)
_ACQUISITION_RESULT_TERMS = ("记录获客智能体结果", "记录获客结果", "保存获客结果", "回写获客结果")
_LEAD_LIST_TERMS = ("查看合规线索", "查看线索", "线索列表", "查询线索", "有哪些线索")
_LEAD_RECORD_TERMS = ("记录合规线索", "记录一条合规线索", "记录线索", "新增线索", "保存线索", "录入线索")
_FEISHU_INTEGRATION_TERMS = (
    "飞书集成", "飞书线索表", "飞书同步", "绑定飞书", "创建飞书", "安装飞书", "登录飞书", "测试写入飞书",
)
_FEISHU_STATUS_TERMS = ("查看飞书集成状态", "飞书集成状态")
_FEISHU_DOCTOR_TERMS = ("检查飞书集成环境", "诊断飞书集成", "修复飞书集成环境")
_FEISHU_INSTALL_TERMS = ("安装飞书集成",)
_FEISHU_LOGIN_TERMS = ("登录飞书集成",)
_FEISHU_BIND_TERMS = ("绑定飞书线索表",)
_FEISHU_CREATE_TERMS = ("创建飞书线索表",)
_FEISHU_TEST_WRITE_TERMS = ("测试写入飞书",)
_FEISHU_RETRY_TERMS = ("重试飞书同步",)
_FEISHU_RECONCILE_TERMS = ("核对飞书同步状态", "核对飞书同步")
_AGENT_DETECT_TERMS = ("检测智能体安装", "检查智能体安装", "检测 codex", "检测 claude code", "检测 openclaw")
_AGENT_INSTALL_TERMS = ("安装智能体", "安装 codex", "安装 claude code", "安装 openclaw", "安装 opencode", "安装 hermes")
_AGENT_LIST_TERMS = ("查看智能体安装状态", "智能体安装状态", "列出已安装智能体", "有哪些智能体")
_AGENT_ROLLBACK_TERMS = ("回滚智能体安装", "恢复智能体安装", "回退智能体安装")
_AGENT_START_TERMS = ("启动智能体", "启动 codex", "启动 claude code", "启动 openclaw", "启动 opencode", "启动 hermes")
_AGENT_UNINSTALL_TERMS = ("卸载智能体", "卸载 codex", "卸载 claude code", "卸载 openclaw", "卸载 opencode", "卸载 hermes")

_JOB_LIST_TERMS = (
    "查看任务列表", "任务列表", "作业列表", "后台任务", "最近任务", "有哪些任务", "所有任务", "全部任务",
    "job list", "jobs list",
)
_JOB_GET_TERMS = (
    "查看任务详情", "任务详情", "作业详情", "查询任务", "查询作业", "查看作业",
    "job detail", "job status", "job id",
)
_SYSTEM_STATUS_TERMS = (
    "查看麓鸣状态", "麓鸣状态", "工作台状态", "系统状态", "整体状态", "运行状态", "健康状态", "loom status",
)
_SCHEDULE_LIST_TERMS = ("查看定时任务", "列出定时任务", "定时任务列表", "计划任务列表")
_SCHEDULE_ADD_TERMS = ("添加定时任务", "新增定时任务", "创建定时任务", "安排定时任务")
_SCHEDULE_RUN_TERMS = ("立即执行定时任务", "立即运行定时任务", "马上执行定时任务", "马上运行定时任务")
_SCHEDULE_CANCEL_TERMS = ("取消定时任务", "删除定时任务", "停用定时任务", "关闭定时任务")
_DOCTOR_TERMS = ("检查麓鸣运行环境", "麓鸣运行环境", "检查运行环境", "运行环境")
_DIAGNOSTICS_RUN_TERMS = ("运行系统诊断", "执行系统诊断", "重新诊断", "开始诊断")
_DIAGNOSTICS_REPAIR_TERMS = ("执行诊断修复", "诊断修复", "修复诊断问题", "一键修复")
_DIAGNOSTICS_EXPORT_TERMS = ("导出诊断包", "诊断包", "导出诊断")
_LOGS_TERMS = ("查看运行日志", "运行日志", "查看日志", "读取日志", "最近日志")
_LICENSE_CURRENT_TERMS = ("查看授权状态", "当前授权状态", "授权状态", "查看许可证", "当前许可证")
_LICENSE_AUTHORIZED_TERMS = ("检查授权有效性", "授权有效性", "授权是否有效", "是否已授权")
_LICENSE_ACTIVATE_TERMS = ("激活授权码", "激活许可证", "使用授权码激活", "输入授权码")
_JOB_ID_PATTERN = re.compile(r"(?<![a-z0-9])job[_-][a-z0-9_-]+", re.IGNORECASE)
_ACTIVE_JOB_STATUSES = frozenset({"queued", "running", "pending", "in_progress", "waiting"})
_TERMINAL_JOB_STATUSES = frozenset({"succeeded", "success", "completed", "failed", "cancelled", "canceled"})

_CORE_NAME_PATTERNS: tuple[str, ...] = ()

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
        and _has_positive_term(folded, _BROAD_INTENT_PATTERNS)
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

    if explicit_mode != "full" and not hinted and _is_response_only_phrase(folded):
        return [], _routing_metadata(
            "response_only",
            set(),
            len(available),
            0,
            "no_tool_intent",
            hinted,
            toolChoice="none",
        )

    fallback_reason = ""
    if explicit_mode == "full":
        fallback_reason = "requested_full_catalog"
    elif int(checkpoint.get("toolSelectionRepairAttempts", 0) or 0) > 0:
        fallback_reason = "selection_repair"
    elif _has_positive_term(folded, _BROAD_INTENT_PATTERNS):
        fallback_reason = "broad_capability_intent"

    domains = _intent_domains(folded, request)
    has_active_job = _checkpoint_has_active_job_reference(checkpoint)
    if has_active_job:
        domains.add("jobs")
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

    selected = _prune_capabilities_for_intent(
        folded,
        selected,
        set(hinted),
        domains,
        has_active_job=has_active_job,
    )

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


def _checkpoint_has_active_job_reference(checkpoint: Mapping[str, Any]) -> bool:
    tool_results = checkpoint.get("toolResults")
    if not isinstance(tool_results, list):
        return False
    return any(
        isinstance(item, Mapping)
        and _value_has_active_job_reference(item.get("result"))
        for item in tool_results
    )


def _value_has_active_job_reference(value: Any, *, parent_key: str = "") -> bool:
    if isinstance(value, Mapping):
        status = str(value.get("status") or "").strip().casefold()
        job_id = str(value.get("jobId") or value.get("job_id") or "").strip()
        if not job_id and parent_key in {"job", "backgroundjob", "background_job"}:
            job_id = str(value.get("id") or "").strip()
        if job_id and (not status or status in _ACTIVE_JOB_STATUSES):
            return True
        if job_id and status in _TERMINAL_JOB_STATUSES:
            return False
        return any(
            _value_has_active_job_reference(nested, parent_key=str(key).casefold())
            for key, nested in value.items()
        )
    if isinstance(value, list):
        return any(_value_has_active_job_reference(item, parent_key=parent_key) for item in value)
    return False


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
        if _has_positive_term(text, keywords)
    }
    if any(pattern.search(text) for pattern in _SCHEDULE_INTENT_PATTERNS):
        domains.add("schedule")
    if not domains and _has_positive_term(text, ("失败", "状态", "异常", "更新")):
        domains.add("diagnostics")
    if _MULTI_DEVICE_TARGET_PATTERN.search(text) or _NAMED_DEVICE_GROUP_TARGET_PATTERN.search(text):
        domains.add("matrix")
    if (
        _has_positive_term(text, _PHONE_REPAIR_TERMS)
        and _has_positive_term(text, ("手机", "设备", "phone", "adb", "无障碍"))
        and not _has_positive_term(text, ("系统诊断", "环境诊断", "导出诊断", "诊断包", "运行日志"))
    ):
        domains.add("phone")
        domains.discard("diagnostics")
    if _is_phone_settings_navigation(text):
        domains.discard("settings")
    if _is_feishu_integration_intent(text):
        domains.add("integration")
        domains.discard("phone")
    if _is_business_agent_context(text):
        domains.discard("agent")
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
    *,
    has_active_job: bool = False,
) -> list[Json]:
    reuse_media = (
        "media" in {_domain for item in capabilities for _domain in _capability_domains(item)}
        and _has_positive_term(text, _MEDIA_REUSE_TERMS)
    )
    regenerate_media = _has_positive_term(text, _MEDIA_REGENERATE_TERMS)
    media_config = _has_positive_term(text, _MEDIA_CONFIG_TERMS)
    media_execution = _has_positive_term(text, _MEDIA_EXECUTION_TERMS)
    image_generation = _has_positive_term(text, _IMAGE_GENERATION_ACTION_TERMS)
    video_generation = _has_positive_term(text, _VIDEO_GENERATION_ACTION_TERMS)
    image_media = _has_positive_term(text, _IMAGE_MEDIA_TERMS)
    video_media = _has_positive_term(text, _VIDEO_MEDIA_TERMS)
    album_transfer = _has_positive_term(text, _ALBUM_TRANSFER_TERMS)
    media_transfer = album_transfer or _has_positive_term(text, _MEDIA_TRANSFER_ACTION_TERMS)
    outbound_publish = _has_positive_term(text, _OUTBOUND_PUBLISH_ACTION_TERMS)
    if album_transfer and not _has_positive_term(text, _OUTBOUND_PUBLISH_DESTINATION_TERMS):
        outbound_publish = False
    phone_repair = _has_positive_term(text, _PHONE_REPAIR_TERMS)
    phone_events = _has_positive_term(text, _PHONE_EVENT_TERMS)
    matrix_intent = "matrix" in domains
    scoped_phone_continuation = domains == {"phone"} and _has_positive_term(
        text,
        ("继续", "接着", "下一步"),
    )
    media_flow = reuse_media or media_execution or media_transfer
    matrix_cancel = _has_positive_term(text, _MATRIX_CANCEL_TERMS)
    matrix_retry = _has_positive_term(text, _MATRIX_RETRY_TERMS)
    matrix_screen = _has_positive_term(text, _MATRIX_SCREEN_TERMS)
    matrix_status = _has_positive_term(text, _MATRIX_STATUS_TERMS)
    matrix_watch = _has_positive_term(text, _MATRIX_WATCH_TERMS)
    matrix_experience = _has_positive_term(text, _MATRIX_EXPERIENCE_TERMS)
    matrix_template = _has_positive_term(text, _MATRIX_TEMPLATE_TERMS)
    matrix_dispatch = (
        matrix_intent
        and _has_positive_term(text, _MATRIX_DISPATCH_ACTION_TERMS)
        and not media_flow
        and not matrix_cancel
        and not matrix_retry
        and not matrix_screen
        and not matrix_status
        and not matrix_watch
        and not matrix_experience
        and not matrix_template
    )
    phone_direct = _has_positive_term(text, _PHONE_DIRECT_CONTROL_TERMS)
    phone_template = _has_positive_term(text, _PHONE_TEMPLATE_TERMS)
    phone_read = _has_positive_term(text, _PHONE_READ_TERMS)
    phone_status = _has_positive_term(text, _PHONE_STATUS_TERMS)
    phone_event_start = _has_positive_term(text, _PHONE_EVENT_START_TERMS)
    phone_event_stop = _has_positive_term(text, _PHONE_EVENT_STOP_TERMS)
    phone_event_status = _has_positive_term(text, _PHONE_EVENT_STATUS_TERMS)
    if phone_events:
        phone_status = False
    settings_theme = _has_positive_term(text, _SETTINGS_THEME_TERMS)
    settings_theme_list = _has_positive_term(text, _SETTINGS_THEME_LIST_TERMS)
    settings_theme_set = settings_theme and _has_positive_term(text, _SETTINGS_THEME_SET_TERMS)
    settings_update = _has_positive_term(text, _SETTINGS_UPDATE_TERMS)
    settings_update_install = _has_positive_term(text, _SETTINGS_UPDATE_INSTALL_TERMS) or (
        settings_update and _has_positive_term(text, ("安装",))
    )
    media_config_save = _has_positive_term(text, _MEDIA_CONFIG_SAVE_TERMS)
    media_config_test = _has_positive_term(text, _MEDIA_CONFIG_TEST_TERMS)
    job_list = _has_positive_term(text, _JOB_LIST_TERMS)
    job_get = has_active_job or _has_positive_term(text, _JOB_GET_TERMS) or bool(_JOB_ID_PATTERN.search(text))
    system_status = _has_positive_term(text, _SYSTEM_STATUS_TERMS)
    model_list = _has_positive_term(text, _MODEL_LIST_TERMS)
    model_select = _has_positive_term(text, _MODEL_SELECT_TERMS)
    agent_model_status = _has_positive_term(text, _AGENT_MODEL_STATUS_TERMS)
    agent_model_apply = _has_positive_term(text, _AGENT_MODEL_APPLY_TERMS)
    agent_model_rollback = _has_positive_term(text, _AGENT_MODEL_ROLLBACK_TERMS)
    wire_current = _has_positive_term(text, _WIRE_CURRENT_TERMS)
    wire_custom = _has_positive_term(text, _WIRE_CUSTOM_TERMS)
    wire_sync = _has_positive_term(text, _WIRE_SYNC_TERMS)
    wire_verify = _has_positive_term(text, _WIRE_VERIFY_TERMS)
    wire_rollback = _has_positive_term(text, _WIRE_ROLLBACK_TERMS)
    account_current = _has_positive_term(text, _ACCOUNT_CURRENT_TERMS)
    account_subscription = _has_positive_term(text, _ACCOUNT_SUBSCRIPTION_TERMS)
    account_send_code = _has_positive_term(text, _ACCOUNT_SEND_CODE_TERMS)
    account_login_generic = (
        _has_positive_term(text, _ACCOUNT_LOGIN_GENERIC_TERMS)
        and not _has_positive_term(text, ("验证码", "密码"))
    )
    account_login_code = account_login_generic or _has_positive_term(text, _ACCOUNT_LOGIN_CODE_TERMS)
    account_login_password = account_login_generic or _has_positive_term(text, _ACCOUNT_LOGIN_PASSWORD_TERMS)
    account_logout = _has_positive_term(text, _ACCOUNT_LOGOUT_TERMS)
    if account_logout:
        account_current = False
    account_sync = _has_positive_term(text, _ACCOUNT_SYNC_TERMS)
    acquisition_run = _has_positive_term(text, _ACQUISITION_RUN_TERMS)
    acquisition_result = _has_positive_term(text, _ACQUISITION_RESULT_TERMS)
    lead_list = _has_positive_term(text, _LEAD_LIST_TERMS)
    lead_record = _has_positive_term(text, _LEAD_RECORD_TERMS)
    feishu_status = _has_positive_term(text, _FEISHU_STATUS_TERMS)
    feishu_doctor = _has_positive_term(text, _FEISHU_DOCTOR_TERMS)
    feishu_install = _has_positive_term(text, _FEISHU_INSTALL_TERMS)
    feishu_login = _has_positive_term(text, _FEISHU_LOGIN_TERMS)
    feishu_bind = _has_positive_term(text, _FEISHU_BIND_TERMS)
    feishu_create = _has_positive_term(text, _FEISHU_CREATE_TERMS)
    feishu_test_write = _has_positive_term(text, _FEISHU_TEST_WRITE_TERMS)
    feishu_retry = _has_positive_term(text, _FEISHU_RETRY_TERMS)
    feishu_reconcile = _has_positive_term(text, _FEISHU_RECONCILE_TERMS)
    agent_detect = _has_positive_term(text, _AGENT_DETECT_TERMS)
    agent_install = _has_positive_term(text, _AGENT_INSTALL_TERMS)
    agent_list = _has_positive_term(text, _AGENT_LIST_TERMS)
    agent_rollback = _has_positive_term(text, _AGENT_ROLLBACK_TERMS)
    agent_start = _has_positive_term(text, _AGENT_START_TERMS)
    agent_uninstall = _has_positive_term(text, _AGENT_UNINSTALL_TERMS)
    schedule_list = _has_positive_term(text, _SCHEDULE_LIST_TERMS)
    schedule_run = _has_positive_term(text, _SCHEDULE_RUN_TERMS)
    schedule_cancel = _has_positive_term(text, _SCHEDULE_CANCEL_TERMS)
    schedule_add = _has_positive_term(text, _SCHEDULE_ADD_TERMS) or (
        "schedule" in domains and not schedule_list and not schedule_run and not schedule_cancel
    )
    diagnostic_doctor = _has_positive_term(text, _DOCTOR_TERMS)
    diagnostic_repair = _has_positive_term(text, _DIAGNOSTICS_REPAIR_TERMS)
    diagnostic_export = _has_positive_term(text, _DIAGNOSTICS_EXPORT_TERMS)
    diagnostic_logs = _has_positive_term(text, _LOGS_TERMS)
    diagnostic_run = _has_positive_term(text, _DIAGNOSTICS_RUN_TERMS) or (
        "diagnostics" in domains
        and not diagnostic_doctor
        and not diagnostic_repair
        and not diagnostic_export
        and not diagnostic_logs
    )
    license_current = _has_positive_term(text, _LICENSE_CURRENT_TERMS)
    license_authorized = _has_positive_term(text, _LICENSE_AUTHORIZED_TERMS)
    license_activate = _has_positive_term(text, _LICENSE_ACTIVATE_TERMS)

    selected: list[Json] = []
    for capability in capabilities:
        name = str(capability.get("name") or "").strip()
        operation = CAPABILITY_OPERATION_KEYS.get(name, name)
        if not name or name in hinted or _is_core_capability(capability):
            selected.append(capability)
            continue
        if name == _CAPABILITY_CATALOG_NAME or name.endswith(_LEGACY_CAPABILITY_CATALOG_SUFFIX):
            continue
        if operation == "loom.cli.jobs.list" and not job_list:
            continue
        if operation == "loom.cli.jobs.get" and not job_get:
            continue
        if operation == "loom.cli.status" and not system_status:
            continue
        if (".loom_schedule_list" in name or name.endswith(".schedule.list")) and not schedule_list:
            continue
        if (".loom_schedule_add" in name or name.endswith(".schedule.add")) and not schedule_add:
            continue
        if (".loom_schedule_run" in name or name.endswith(".schedule.run")) and not schedule_run:
            continue
        if (".loom_schedule_cancel" in name or name.endswith(".schedule.cancel")) and not schedule_cancel:
            continue
        if name.endswith(".loom_doctor") and not diagnostic_doctor:
            continue
        if (".loom_diagnostics_run" in name or name.endswith(".diagnostics.run")) and not diagnostic_run:
            continue
        if ".loom_diagnostics_repair" in name and not diagnostic_repair:
            continue
        if ".loom_diagnostics_export" in name and not diagnostic_export:
            continue
        if operation == "loom.logs.tail" and not diagnostic_logs:
            continue
        if (".loom_license_current" in name or name.endswith(".license.current")) and not license_current:
            continue
        if (".loom_license_authorized" in name or name.endswith(".license.authorized")) and not license_authorized:
            continue
        if (".loom_license_activate" in name or name.endswith(".license.activate")) and not license_activate:
            continue
        if operation == "loom.cli.models" and not model_list:
            continue
        if ".loom_account_current" in name or name == "loom.cli.account.current":
            if not account_current:
                continue
        if ".loom_account_subscription" in name and not account_subscription:
            continue
        if ".loom_account_send_code" in name and not account_send_code:
            continue
        if ".loom_account_login_code" in name and not account_login_code:
            continue
        if ".loom_account_login_password" in name and not account_login_password:
            continue
        if ".loom_account_logout" in name and not account_logout:
            continue
        if ".loom_account_sync" in name and not account_sync:
            continue
        if ".loom_account_select_models" in name and not model_select:
            continue
        if ".loom_agent_model_status" in name and not agent_model_status:
            continue
        if ".loom_agent_model_apply" in name and not agent_model_apply:
            continue
        if ".loom_agent_model_rollback" in name and not agent_model_rollback:
            continue
        if ".loom_wire_current" in name and not wire_current:
            continue
        if ".loom_wire_custom" in name and not wire_custom:
            continue
        if ".loom_wire_sync" in name and not wire_sync:
            continue
        if ".loom_wire_verify" in name and not wire_verify:
            continue
        if ".loom_wire_rollback" in name and not wire_rollback:
            continue
        if operation == "loom.acquisition.run" or ".loom_acquisition_agent_run" in name:
            if not acquisition_run:
                continue
        if ".loom_acquisition_agent_result" in name and not acquisition_result:
            continue
        if ".loom_lead_list" in name and not lead_list:
            continue
        if ".loom_lead_record" in name and not lead_record:
            continue
        if ".loom_feishu_status" in name and not feishu_status:
            continue
        if ".loom_feishu_doctor" in name and not feishu_doctor:
            continue
        if ".loom_feishu_install" in name and not feishu_install:
            continue
        if ".loom_feishu_login" in name and not feishu_login:
            continue
        if ".loom_feishu_bind_table" in name and not feishu_bind:
            continue
        if ".loom_feishu_create_table" in name and not feishu_create:
            continue
        if ".loom_feishu_test_write" in name and not feishu_test_write:
            continue
        if ".loom_feishu_retry_sync" in name and not feishu_retry:
            continue
        if ".loom_feishu_reconcile" in name and not feishu_reconcile:
            continue
        if ".loom_agent_detect" in name and not agent_detect:
            continue
        if ".loom_agent_install" in name and not agent_install:
            continue
        if ".loom_agent_list" in name and not agent_list:
            continue
        if ".loom_agent_rollback" in name and not agent_rollback:
            continue
        if ".loom_agent_start" in name and not agent_start:
            continue
        if ".loom_agent_uninstall" in name and not agent_uninstall:
            continue
        if reuse_media and not regenerate_media and operation == "loom.media.image.generate" and not image_generation:
            continue
        if reuse_media and not regenerate_media and operation == "loom.media.video.generate" and not video_generation:
            continue
        if image_media and not video_media and operation == "loom.media.video.generate":
            continue
        if video_media and not image_media and operation == "loom.media.image.generate":
            continue
        if media_transfer and not media_execution and operation in {
            "loom.media.image.generate",
            "loom.media.video.generate",
        }:
            continue
        if operation == "loom.media.asset.transfer" and not media_transfer:
            continue
        if media_execution and not reuse_media and not media_transfer and operation == "loom.media.assets.list":
            continue
        if media_config and not media_execution and operation in _MEDIA_EXECUTION_CAPABILITIES:
            continue
        if not media_config and any(marker in name for marker in _MEDIA_CONFIG_CAPABILITY_MARKERS):
            continue
        if name.endswith(".loom_media_config") and (
            media_config_save or _has_positive_term(text, ("测试", "验证"))
        ):
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
        if operation == "loom.matrix.status" and not matrix_status:
            continue
        if operation == "loom.cli.matrix.watch" and not matrix_watch:
            continue
        if operation == "loom.cli.experience.report" and not matrix_experience:
            continue
        if operation == "loom.cli.template.run" and not matrix_template:
            continue
        if operation == "loom.cli.phone.quick-task":
            if phone_template or phone_events or matrix_dispatch or (media_flow and not phone_direct) or not phone_direct:
                continue
        if operation == "loom.mcp.loom.loom_phone_template_task":
            if not phone_template:
                continue
        if operation == "loom.cli.phone.read" and (matrix_intent or not phone_read):
            continue
        if operation == "loom.cli.phone.status" and (matrix_intent or not (phone_status or phone_repair)):
            continue
        if name == "loom.phone.publish" and not outbound_publish and not scoped_phone_continuation:
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
        if (
            (".loom_settings_theme" in name and not name.endswith("_list"))
            or name == "loom.settings.theme.set"
        ) and not settings_theme_set:
            continue
        if (
            ".loom_settings_update_check" in name or name == "loom.settings.update.check"
        ) and not settings_update:
            continue
        if (
            ".loom_settings_update_install" in name or name == "loom.settings.update.install"
        ) and not settings_update_install:
            continue
        selected.append(capability)
    return selected


def _is_phone_settings_navigation(text: str) -> bool:
    return (
        _has_positive_term(text, ("设置",))
        and _has_positive_term(text, ("手机", "phone", "device", "设备"))
        and _has_positive_term(text, _PHONE_SETTINGS_ACTION_TERMS)
        and not _has_positive_term(text, _LOOM_SETTINGS_TERMS)
    )


def _is_response_only_phrase(text: str) -> bool:
    normalized = re.sub(r"[\s，,。.!！?？;；:：~～]+", "", text.casefold())
    return normalized in _RESPONSE_ONLY_PHRASES


def _is_feishu_integration_intent(text: str) -> bool:
    return _has_positive_term(text, _FEISHU_INTEGRATION_TERMS)


def _is_business_agent_context(text: str) -> bool:
    return _has_positive_term(text, ("获客智能体", "招聘智能体")) and not _has_positive_term(
        text,
        (
            *_AGENT_DETECT_TERMS,
            *_AGENT_INSTALL_TERMS,
            *_AGENT_LIST_TERMS,
            *_AGENT_ROLLBACK_TERMS,
            *_AGENT_START_TERMS,
            *_AGENT_UNINSTALL_TERMS,
            *_AGENT_MODEL_STATUS_TERMS,
            *_AGENT_MODEL_APPLY_TERMS,
            *_AGENT_MODEL_ROLLBACK_TERMS,
        ),
    )


def _is_recruitment_media_subject(text: str) -> bool:
    return (
        _has_positive_term(text, _ACQUISITION_SUBJECT_TERMS)
        and _has_positive_term(text, _MEDIA_CONTENT_TERMS)
        and not _has_positive_term(text, _ACQUISITION_OPERATION_TERMS)
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
        "feishu": "integration",
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
