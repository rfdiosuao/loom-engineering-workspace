package com.apk.claw.android.utils

import android.content.Context
import com.tencent.mmkv.MMKV
import java.util.UUID

/**
 * MMKV 键值存储工具类
 *
 * 使用方式：
 *   // 在 Application.onCreate 中初始化
 *   KVUtils.init(context)
 *
 *   // 存取数据
 *   KVUtils.putString("key", "value")
 *   val value = KVUtils.getString("key", "default")
 */
object KVUtils {


    // 钉钉配置
    const val KEY_DINGTALK_APP_KEY = "DEFAULT_DINGTALK_APP_KEY"
    const val KEY_DINGTALK_APP_SECRET = "DEFAULT_DINGTALK_APP_SECRET"
    // 飞书配置
    const val KEY_FEISHU_APP_ID = "DEFAULT_FEISHU_APP_ID"
    const val KEY_FEISHU_APP_SECRET = "DEFAULT_FEISHU_APP_SECRET"
    // QQ 机器人配置
    const val KEY_QQ_APP_ID = "DEFAULT_QQ_APP_ID"
    const val KEY_QQ_APP_SECRET = "DEFAULT_QQ_APP_SECRET"
    // Discord 机器人配置
    const val KEY_DISCORD_BOT_TOKEN = "DEFAULT_DISCORD_BOT_TOKEN"
    // Telegram 机器人配置
    const val KEY_TELEGRAM_BOT_TOKEN = "DEFAULT_TELEGRAM_BOT_TOKEN"
    // 微信 iLink Bot 配置
    const val KEY_WECHAT_BOT_TOKEN = "DEFAULT_WECHAT_BOT_TOKEN"
    const val KEY_WECHAT_API_BASE_URL = "DEFAULT_WECHAT_API_BASE_URL"
    const val KEY_WECHAT_UPDATES_CURSOR = "DEFAULT_WECHAT_UPDATES_CURSOR"

    private lateinit var mmkv: MMKV

    private const val DEFAULT_INT = 0
    private const val DEFAULT_LONG = 0L
    private const val DEFAULT_BOOL = false
    private const val DEFAULT_FLOAT = 0f
    private const val DEFAULT_DOUBLE = 0.0

    /**
     * 在 Application.onCreate 中调用初始化
     */
    fun init(context: Context) {
        MMKV.initialize(context)
        mmkv = MMKV.defaultMMKV()
    }

    // ==================== String ====================
    fun putString(key: String, value: String?): Boolean {
        return mmkv.encode(key, value)
    }

    fun getString(key: String, defaultValue: String = ""): String {
        return mmkv.decodeString(key, defaultValue) ?: defaultValue
    }

    // ==================== Int ====================
    fun putInt(key: String, value: Int): Boolean {
        return mmkv.encode(key, value)
    }

    fun getInt(key: String, defaultValue: Int = DEFAULT_INT): Int {
        return mmkv.decodeInt(key, defaultValue)
    }

    // ==================== Long ====================
    fun putLong(key: String, value: Long): Boolean {
        return mmkv.encode(key, value)
    }

    fun getLong(key: String, defaultValue: Long = DEFAULT_LONG): Long {
        return mmkv.decodeLong(key, defaultValue)
    }

    // ==================== Boolean ====================
    fun putBoolean(key: String, value: Boolean): Boolean {
        return mmkv.encode(key, value)
    }

    fun getBoolean(key: String, defaultValue: Boolean = DEFAULT_BOOL): Boolean {
        return mmkv.decodeBool(key, defaultValue)
    }

    // ==================== Float ====================
    fun putFloat(key: String, value: Float): Boolean {
        return mmkv.encode(key, value)
    }

    fun getFloat(key: String, defaultValue: Float = DEFAULT_FLOAT): Float {
        return mmkv.decodeFloat(key, defaultValue)
    }

    // ==================== Double ====================
    fun putDouble(key: String, value: Double): Boolean {
        return mmkv.encode(key, value)
    }

    fun getDouble(key: String, defaultValue: Double = DEFAULT_DOUBLE): Double {
        return mmkv.decodeDouble(key, defaultValue)
    }

    // ==================== Bytes ====================
    fun putBytes(key: String, value: ByteArray?): Boolean {
        return mmkv.encode(key, value)
    }

    fun getBytes(key: String): ByteArray? {
        return mmkv.decodeBytes(key)
    }

    // ==================== 常用操作 ====================
    fun contains(key: String): Boolean {
        return mmkv.containsKey(key)
    }

    fun remove(key: String) {
        mmkv.removeValueForKey(key)
    }

    fun remove(vararg keys: String) {
        mmkv.removeValuesForKeys(keys)
    }

    fun clear() {
        mmkv.clearAll()
    }

    fun getAllKeys(): Array<String> {
        return mmkv.allKeys() ?: emptyArray()
    }

    /**
     * 同步写入磁盘（默认是异步的）
     */
    fun sync() {
        mmkv.sync()
    }


    // ==================== 引导页 ====================
    private const val KEY_GUIDE_SHOWN = "KEY_GUIDE_SHOWN"

    fun isGuideShown(): Boolean = getBoolean(KEY_GUIDE_SHOWN, false)

    fun setGuideShown(shown: Boolean) = putBoolean(KEY_GUIDE_SHOWN, shown)

    // ==================== 钉钉配置 ====================
    fun getDingtalkAppKey(): String = getString(KEY_DINGTALK_APP_KEY, "")
    fun setDingtalkAppKey(value: String) = putString(KEY_DINGTALK_APP_KEY, value)
    fun getDingtalkAppSecret(): String = getString(KEY_DINGTALK_APP_SECRET, "")
    fun setDingtalkAppSecret(value: String) = putString(KEY_DINGTALK_APP_SECRET, value)

    // ==================== 飞书配置 ====================
    fun getFeishuAppId(): String = getString(KEY_FEISHU_APP_ID, "")
    fun setFeishuAppId(value: String) = putString(KEY_FEISHU_APP_ID, value)
    fun getFeishuAppSecret(): String = getString(KEY_FEISHU_APP_SECRET, "")
    fun setFeishuAppSecret(value: String) = putString(KEY_FEISHU_APP_SECRET, value)

    // ==================== QQ 机器人配置 ====================
    fun getQqAppId(): String = getString(KEY_QQ_APP_ID, "")
    fun setQqAppId(value: String) = putString(KEY_QQ_APP_ID, value)
    fun getQqAppSecret(): String = getString(KEY_QQ_APP_SECRET, "")
    fun setQqAppSecret(value: String) = putString(KEY_QQ_APP_SECRET, value)

    // ==================== Discord 机器人配置 ====================
    fun getDiscordBotToken(): String = getString(KEY_DISCORD_BOT_TOKEN, "")
    fun setDiscordBotToken(value: String) = putString(KEY_DISCORD_BOT_TOKEN, value)

    // ==================== Telegram 机器人配置 ====================
    fun getTelegramBotToken(): String = getString(KEY_TELEGRAM_BOT_TOKEN, "")
    fun setTelegramBotToken(value: String) = putString(KEY_TELEGRAM_BOT_TOKEN, value)

    // ==================== 微信 iLink Bot 配置 ====================
    fun getWechatBotToken(): String = getString(KEY_WECHAT_BOT_TOKEN, "")
    fun setWechatBotToken(value: String) = putString(KEY_WECHAT_BOT_TOKEN, value)
    fun getWechatApiBaseUrl(): String = getString(KEY_WECHAT_API_BASE_URL, "")
    fun setWechatApiBaseUrl(value: String) = putString(KEY_WECHAT_API_BASE_URL, value)
    fun getWechatUpdatesCursor(): String = getString(KEY_WECHAT_UPDATES_CURSOR, "")
    fun setWechatUpdatesCursor(value: String) = putString(KEY_WECHAT_UPDATES_CURSOR, value)

    // ==================== 局域网配置服务 ====================
    private const val KEY_CONFIG_SERVER_ENABLED = "KEY_CONFIG_SERVER_ENABLED"
    fun isConfigServerEnabled(): Boolean = getBoolean(KEY_CONFIG_SERVER_ENABLED, false)
    fun setConfigServerEnabled(enabled: Boolean) = putBoolean(KEY_CONFIG_SERVER_ENABLED, enabled)

    // ==================== 悬浮球显示 ====================
    private const val KEY_FLOATING_CIRCLE_SIZE = "KEY_FLOATING_CIRCLE_SIZE"
    fun getFloatingCircleSize(): String = getString(KEY_FLOATING_CIRCLE_SIZE, "large")
    fun setFloatingCircleSize(value: String) = putString(KEY_FLOATING_CIRCLE_SIZE, value)

    private const val KEY_FLOATING_CLICK_ENABLED = "KEY_FLOATING_CLICK_ENABLED"
    fun isFloatingClickEnabled(): Boolean = getBoolean(KEY_FLOATING_CLICK_ENABLED, false)
    fun setFloatingClickEnabled(enabled: Boolean) = putBoolean(KEY_FLOATING_CLICK_ENABLED, enabled)

    // ==================== LLM 配置 ====================
    private const val KEY_LLM_API_KEY = "KEY_LLM_API_KEY"
    private const val KEY_LLM_BASE_URL = "KEY_LLM_BASE_URL"
    private const val KEY_LLM_MODEL_NAME = "KEY_LLM_MODEL_NAME"

    // 默认使用阿里云通义千问 API
    private const val DEFAULT_LLM_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"
    private const val DEFAULT_LLM_MODEL_NAME = "qwen3.5-plus"

    fun getLlmApiKey(): String = getString(KEY_LLM_API_KEY, "")
    fun setLlmApiKey(value: String) = putString(KEY_LLM_API_KEY, value)
    fun getLlmBaseUrl(): String = getString(KEY_LLM_BASE_URL, DEFAULT_LLM_BASE_URL)
    fun setLlmBaseUrl(value: String) = putString(KEY_LLM_BASE_URL, value)
    fun getLlmModelName(): String = getString(KEY_LLM_MODEL_NAME, DEFAULT_LLM_MODEL_NAME)
    fun setLlmModelName(value: String) = putString(KEY_LLM_MODEL_NAME, value)

    /** 是否已配置 LLM（API Key 非空即视为已配置） */
    fun hasLlmConfig(): Boolean = getLlmApiKey().isNotEmpty()

    // ==================== 记忆系统 ====================
    private const val KEY_MEMORY_USER_PROFILE = "KEY_MEMORY_USER_PROFILE"
    private const val KEY_MEMORY_LONG_TERM = "KEY_MEMORY_LONG_TERM"
    private const val KEY_MEMORY_SESSION = "KEY_MEMORY_SESSION"

    fun getMemoryUserProfile(): String = getString(KEY_MEMORY_USER_PROFILE, "")
    fun setMemoryUserProfile(value: String) = putString(KEY_MEMORY_USER_PROFILE, value)
    fun getMemoryLongTerm(): String = getString(KEY_MEMORY_LONG_TERM, "")
    fun setMemoryLongTerm(value: String) = putString(KEY_MEMORY_LONG_TERM, value)
    fun getMemorySession(): String = getString(KEY_MEMORY_SESSION, "[]")
    fun setMemorySession(value: String) = putString(KEY_MEMORY_SESSION, value)

    // ==================== 定时任务 ====================
    private const val KEY_SCHEDULED_TASKS = "KEY_SCHEDULED_TASKS"
    fun getScheduledTasks(): String = getString(KEY_SCHEDULED_TASKS, "[]")
    fun setScheduledTasks(value: String) = putString(KEY_SCHEDULED_TASKS, value)

    // ==================== 行为分析 ====================
    private const val KEY_BEHAVIOR_EVENTS = "KEY_BEHAVIOR_EVENTS"
    fun getBehaviorEvents(): String = getString(KEY_BEHAVIOR_EVENTS, "[]")
    fun setBehaviorEvents(value: String) = putString(KEY_BEHAVIOR_EVENTS, value)

    // ==================== 主动建议 ====================
    private const val KEY_PROACTIVE_SUGGESTIONS = "KEY_PROACTIVE_SUGGESTIONS"
    fun getProactiveSuggestions(): String = getString(KEY_PROACTIVE_SUGGESTIONS, "[]")
    fun setProactiveSuggestions(value: String) = putString(KEY_PROACTIVE_SUGGESTIONS, value)

    // ==================== API Token ====================
    private const val KEY_API_TOKEN = "KEY_API_TOKEN"
    fun getApiToken(): String = getString(KEY_API_TOKEN, "")
    fun setApiToken(value: String) = putString(KEY_API_TOKEN, value)

    // ==================== Publish Relay ====================
    private const val KEY_PUBLISH_RELAY_BASE_URL = "KEY_PUBLISH_RELAY_BASE_URL"
    private const val KEY_PUBLISH_RELAY_CHANNEL_ID = "KEY_PUBLISH_RELAY_CHANNEL_ID"
    private const val KEY_PUBLISH_RELAY_TOKEN = "KEY_PUBLISH_RELAY_TOKEN"
    private const val KEY_PUBLISH_RELAY_ENABLED = "KEY_PUBLISH_RELAY_ENABLED"
    private const val KEY_PUBLISH_RELAY_CLIENT_ID = "KEY_PUBLISH_RELAY_CLIENT_ID"

    fun getPublishRelayBaseUrl(): String = getString(KEY_PUBLISH_RELAY_BASE_URL, "")
    fun setPublishRelayBaseUrl(value: String) = putString(KEY_PUBLISH_RELAY_BASE_URL, value)
    fun getPublishRelayChannelId(): String = getString(KEY_PUBLISH_RELAY_CHANNEL_ID, "")
    fun setPublishRelayChannelId(value: String) = putString(KEY_PUBLISH_RELAY_CHANNEL_ID, value)
    fun getPublishRelayToken(): String = getString(KEY_PUBLISH_RELAY_TOKEN, "")
    fun setPublishRelayToken(value: String) = putString(KEY_PUBLISH_RELAY_TOKEN, value)
    fun isPublishRelayEnabled(): Boolean = getBoolean(KEY_PUBLISH_RELAY_ENABLED, false)
    fun setPublishRelayEnabled(enabled: Boolean) = putBoolean(KEY_PUBLISH_RELAY_ENABLED, enabled)
    fun getPublishRelayClientId(): String = getString(KEY_PUBLISH_RELAY_CLIENT_ID, "")
    fun setPublishRelayClientId(value: String) = putString(KEY_PUBLISH_RELAY_CLIENT_ID, value)
    fun ensurePublishRelayClientId(): String {
        val current = getPublishRelayClientId()
        if (current.isNotBlank()) return current
        val generated = "relay-${UUID.randomUUID().toString().replace("-", "").take(12)}"
        setPublishRelayClientId(generated)
        return generated
    }

    // ==================== Lumi launcher secure channel ====================
    private const val KEY_LUMI_LAUNCHER_ID = "KEY_LUMI_LAUNCHER_ID"
    private const val KEY_LUMI_LAUNCHER_NAME = "KEY_LUMI_LAUNCHER_NAME"
    private const val KEY_LUMI_LAUNCHER_SECRET = "KEY_LUMI_LAUNCHER_SECRET"
    private const val KEY_LUMI_LAUNCHER_PAIRED_AT = "KEY_LUMI_LAUNCHER_PAIRED_AT"

    fun getLumiLauncherId(): String = getString(KEY_LUMI_LAUNCHER_ID, "")
    fun setLumiLauncherId(value: String) = putString(KEY_LUMI_LAUNCHER_ID, value)
    fun getLumiLauncherName(): String = getString(KEY_LUMI_LAUNCHER_NAME, "")
    fun setLumiLauncherName(value: String) = putString(KEY_LUMI_LAUNCHER_NAME, value)
    fun getLumiLauncherSecret(): String = getString(KEY_LUMI_LAUNCHER_SECRET, "")
    fun setLumiLauncherSecret(value: String) = putString(KEY_LUMI_LAUNCHER_SECRET, value)
    fun getLumiLauncherPairedAt(): Long = getLong(KEY_LUMI_LAUNCHER_PAIRED_AT, 0L)
    fun setLumiLauncherPairedAt(value: Long) = putLong(KEY_LUMI_LAUNCHER_PAIRED_AT, value)
    fun clearLumiLauncherPairing() = remove(
        KEY_LUMI_LAUNCHER_ID,
        KEY_LUMI_LAUNCHER_NAME,
        KEY_LUMI_LAUNCHER_SECRET,
        KEY_LUMI_LAUNCHER_PAIRED_AT
    )
}
