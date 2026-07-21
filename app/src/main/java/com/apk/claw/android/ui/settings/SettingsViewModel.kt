package com.apk.claw.android.ui.settings

import android.content.Context
import android.widget.Toast
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.apk.claw.android.ClawApplication
import com.apk.claw.android.R
import com.apk.claw.android.channel.ChannelManager
import com.apk.claw.android.floating.FloatingCircleManager
import com.apk.claw.android.server.ConfigServerManager
import com.apk.claw.android.server.PcPairingReadinessPolicy
import com.apk.claw.android.server.TokenValidator
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.widget.QRCodeDialog
import com.apk.claw.android.utils.XLog
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive

/**
 * SettingsActivity 的 ViewModel
 */
class SettingsViewModel : ViewModel() {

    // 设置项数据 Flow（用于动态更新）
    private val _settingItems = MutableStateFlow<Map<String, SettingValue>>(emptyMap())
    val settingItems: StateFlow<Map<String, SettingValue>> = _settingItems

    // 菜单点击事件
    private val _menuClickEvent = MutableStateFlow<MenuAction?>(null)
    val menuClickEvent: StateFlow<MenuAction?> = _menuClickEvent

    init {
        refresh()
    }

    fun refresh() {
        val dingtalkAppKey = KVUtils.getDingtalkAppKey().isNotEmpty()
        val dingtalkAppSecret = KVUtils.getDingtalkAppSecret().isNotEmpty()
        val feishuAppId = KVUtils.getFeishuAppId().isNotEmpty()
        val feishuAppSecret = KVUtils.getFeishuAppSecret().isNotEmpty()
        val qqAppId = KVUtils.getQqAppId().isNotEmpty()
        val qqAppSecret = KVUtils.getQqAppSecret().isNotEmpty()
        val discordBotToken = KVUtils.getDiscordBotToken().isNotEmpty()
        val telegramBotToken = KVUtils.getTelegramBotToken().isNotEmpty()
        val wechatBotToken = KVUtils.getWechatBotToken().isNotEmpty()
        val apiTokenSet = TokenValidator.isTokenConfigured()
        val map = mapOf(
            MenuAction.LLM_CONFIG.name to SettingValue.Text(if (KVUtils.hasLlmConfig()) KVUtils.getLlmModelName() else ClawApplication.instance.getString(R.string.common_unconfigured)),
            MenuAction.DINGDING.name to SettingValue.Text(ClawApplication.instance.getString(if (dingtalkAppKey && dingtalkAppSecret) R.string.common_bound else R.string.common_unbound)),
            MenuAction.FEISHU.name to SettingValue.Text(ClawApplication.instance.getString(if (feishuAppId && feishuAppSecret) R.string.common_bound else R.string.common_unbound)),
            MenuAction.QQ.name to SettingValue.Text(ClawApplication.instance.getString(if (qqAppId && qqAppSecret) R.string.common_bound else R.string.common_unbound)),
            MenuAction.DISCORD.name to SettingValue.Text(ClawApplication.instance.getString(if (discordBotToken) R.string.common_bound else R.string.common_unbound)),
            MenuAction.TELEGRAM.name to SettingValue.Text(ClawApplication.instance.getString(if (telegramBotToken) R.string.common_bound else R.string.common_unbound)),
            MenuAction.WECHAT.name to SettingValue.Text(ClawApplication.instance.getString(if (wechatBotToken) R.string.common_bound else R.string.common_unbound)),
            MenuAction.API_TOKEN.name to SettingValue.Text(ClawApplication.instance.getString(if (apiTokenSet) R.string.api_token_status_set else R.string.api_token_status_unset)),
            MenuAction.LAN_CONFIG.name to SettingValue.Text(getLanConfigTrailingText()),
            MenuAction.PUBLISH_RELAY.name to SettingValue.Text(getPublishRelayTrailingText()),
            MenuAction.FLOATING_CLICK.name to SettingValue.Switch(FloatingCircleManager.isFloatingClickEnabled()),
            MenuAction.FLOATING_SIZE.name to SettingValue.Text(FloatingCircleManager.getFloatingSizeLabel(ClawApplication.instance))
        )
        _settingItems.value = map
    }

    /**
     * 更新设置项值
     */
    fun updateSettingValue(key: String, value: SettingValue) {
        _settingItems.value = _settingItems.value.toMutableMap().apply {
            put(key, value)
        }
    }

    /**
     * 更新尾部文字
     */
    fun updateTrailingText(key: String, text: String) {
        updateSettingValue(key, SettingValue.Text(text))
    }

    fun setFloatingClickEnabled(enabled: Boolean) {
        FloatingCircleManager.setFloatingClickEnabled(enabled)
        updateSettingValue(MenuAction.FLOATING_CLICK.name, SettingValue.Switch(enabled))
    }

    /**
     * 处理菜单项点击
     */
    fun onMenuItemClick(action: MenuAction) {
        _menuClickEvent.value = action
    }

    /**
     * 清空菜单点击事件
     */
    fun clearMenuClickEvent() {
        _menuClickEvent.value = null
    }

    /**
     * 微信 iLink 扫码登录流程
     */
    fun startWeChatQrLogin(context: Context) {
        viewModelScope.launch {
            val loadingDialog = com.apk.claw.android.widget.LoadingDialog.show(
                context = context,
                message = context.getString(R.string.channel_config_wechat_scanning)
            )
            try {
                val apiClient = com.apk.claw.android.channel.wechat.WeChatApiClient()
                val qrResult = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                    apiClient.getQrCode()
                }
                loadingDialog.dismiss()
                if (qrResult == null) {
                    Toast.makeText(context, R.string.wechat_qr_failed, Toast.LENGTH_SHORT).show()
                    return@launch
                }

                // 用 qrcode 值通过 ZXing 本地生成二维码 Bitmap
                val qrBitmap = generateQrBitmap(qrResult.qrcodeImgContent, 512)
                if (qrBitmap == null) {
                    Toast.makeText(context, R.string.wechat_qr_failed, Toast.LENGTH_SHORT).show()
                    return@launch
                }
                var pollingJob: Job? = null
                val dialog = QRCodeDialog.show(
                    context = context,
                    title = context.getString(R.string.channel_config_wechat_title),
                    subtitle = context.getString(R.string.channel_config_wechat_tip),
                    qrBitmap = qrBitmap,
                    onClose = { pollingJob?.cancel() }
                )
                pollingJob = startWeChatQrPolling(context, dialog, apiClient, qrResult.qrcode)
            } catch (e: Exception) {
                loadingDialog.dismiss()
                XLog.e("SettingsViewModel", "微信扫码登录失败", e)
                Toast.makeText(context, R.string.wechat_qr_failed, Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun startWeChatQrPolling(
        context: Context,
        dialog: QRCodeDialog,
        apiClient: com.apk.claw.android.channel.wechat.WeChatApiClient,
        qrcode: String
    ): Job {
        return viewModelScope.launch {
            while (isActive) {
                delay(2000)
                if (!dialog.isShowing) break
                try {
                    val authResult = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                        apiClient.pollQrCodeStatus(qrcode)
                    }
                    if (authResult != null) {
                        // 扫码确认成功，保存 token 和 baseurl
                        KVUtils.setWechatBotToken(authResult.botToken)
                        KVUtils.setWechatApiBaseUrl(authResult.baseUrl)
                        ChannelManager.reinitWeChatFromStorage()
                        dialog.showStatusOverlay(
                            ClawApplication.instance.getString(R.string.channel_config_wechat_confirmed)
                        )
                        refresh()
                        delay(1500)
                        dialog.dismiss()
                        break
                    }
                } catch (_: Exception) {
                    // 网络异常静默重试
                }
            }
        }
    }


    /**
     * 切换局域网配置服务开关
     */
    fun toggleConfigServer(context: Context): String {
        return if (ConfigServerManager.isRunning()) {
            ConfigServerManager.stop()
            KVUtils.setConfigServerEnabled(false)
            val text = getLanConfigTrailingText()
            updateTrailingText(MenuAction.LAN_CONFIG.name, text)
            text
        } else {
            val started = ConfigServerManager.start(context)
            if (started) {
                KVUtils.setConfigServerEnabled(true)
                val text = getLanConfigTrailingText()
                updateTrailingText(MenuAction.LAN_CONFIG.name, text)
                text
            } else {
                ClawApplication.instance.getString(R.string.lan_config_no_wifi)
            }
        }
    }

    private fun getLanConfigTrailingText(): String {
        return if (ConfigServerManager.isRunning()) {
            ConfigServerManager.getAddress() ?: ClawApplication.instance.getString(R.string.lan_config_stopped)
        } else {
            ClawApplication.instance.getString(R.string.lan_config_stopped)
        }
    }

    private fun getPublishRelayTrailingText(): String {
        val configured = KVUtils.getPublishRelayBaseUrl().isNotBlank() && KVUtils.getPublishRelayChannelId().isNotBlank()
        if (!configured) return ClawApplication.instance.getString(R.string.common_unconfigured)
        return ClawApplication.instance.getString(
            if (KVUtils.isPublishRelayEnabled()) {
                R.string.publish_relay_status_on
            } else {
                R.string.publish_relay_status_off
            }
        )
    }

    fun isDingtalkBound(): Boolean {
        return KVUtils.getDingtalkAppKey().isNotEmpty() && KVUtils.getDingtalkAppSecret().isNotEmpty()
    }

    fun isFeishuBound(): Boolean {
        return KVUtils.getFeishuAppId().isNotEmpty() && KVUtils.getFeishuAppSecret().isNotEmpty()
    }

    fun isQqBound(): Boolean {
        return KVUtils.getQqAppId().isNotEmpty() && KVUtils.getQqAppSecret().isNotEmpty()
    }

    fun isDiscordBound(): Boolean {
        return KVUtils.getDiscordBotToken().isNotEmpty()
    }

    fun isTelegramBound(): Boolean {
        return KVUtils.getTelegramBotToken().isNotEmpty()
    }

    fun isWechatBound(): Boolean {
        return KVUtils.getWechatBotToken().isNotEmpty()
    }

    fun unbindDingtalk() {
        KVUtils.setDingtalkAppKey("")
        KVUtils.setDingtalkAppSecret("")
        ChannelManager.reinitDingTalkFromStorage()
        refresh()
    }

    fun unbindFeishu() {
        KVUtils.setFeishuAppId("")
        KVUtils.setFeishuAppSecret("")
        ChannelManager.reinitFeiShuFromStorage()
        refresh()
    }

    fun unbindQq() {
        KVUtils.setQqAppId("")
        KVUtils.setQqAppSecret("")
        ChannelManager.reinitQQFromStorage()
        refresh()
    }

    fun unbindDiscord() {
        KVUtils.setDiscordBotToken("")
        ChannelManager.reinitDiscordFromStorage()
        refresh()
    }

    fun unbindTelegram() {
        KVUtils.setTelegramBotToken("")
        ChannelManager.reinitTelegramFromStorage()
        refresh()
    }

    fun unbindWeChat() {
        // 清除持久化的 contextToken（对应 2.0.1 clearContextTokensForAccount）
        val accountId = KVUtils.getWechatBotToken().substringBefore(":").ifEmpty { "default" }
        com.apk.claw.android.channel.wechat.WeChatInbound.clearContextTokensForAccount(accountId)
        KVUtils.setWechatBotToken("")
        KVUtils.setWechatApiBaseUrl("")
        KVUtils.setWechatUpdatesCursor("")
        ChannelManager.reinitWeChatFromStorage()
        refresh()
    }

    /**
     * 设置值密封类
     */
    sealed class SettingValue {
        data class Text(val text: String) : SettingValue()
        data class Switch(val isOn: Boolean) : SettingValue()
    }

    /**
     * 用 ZXing 将文本编码为二维码 Bitmap
     */
    private fun generateQrBitmap(content: String, size: Int): android.graphics.Bitmap? {
        return try {
            val hints = mapOf(
                com.google.zxing.EncodeHintType.MARGIN to 1,
                com.google.zxing.EncodeHintType.CHARACTER_SET to "UTF-8"
            )
            val matrix = com.google.zxing.qrcode.QRCodeWriter()
                .encode(content, com.google.zxing.BarcodeFormat.QR_CODE, size, size, hints)
            val bitmap = android.graphics.Bitmap.createBitmap(size, size, android.graphics.Bitmap.Config.RGB_565)
            for (x in 0 until size) {
                for (y in 0 until size) {
                    bitmap.setPixel(x, y, if (matrix.get(x, y)) android.graphics.Color.BLACK else android.graphics.Color.WHITE)
                }
            }
            bitmap
        } catch (e: Exception) {
            XLog.e("SettingsViewModel", "生成二维码失败", e)
            null
        }
    }

    /**
     * 菜单动作枚举
     */
    enum class MenuAction {
        DINGDING, FEISHU, QQ, DISCORD, TELEGRAM, WECHAT,
        API_TOKEN,
        LAN_CONFIG,
        PC_PAIRING,
        LLM_CONFIG,
        PUBLISH_RELAY,
        FLOATING_CLICK,
        FLOATING_SIZE
    }

    /**
     * 电脑配对：把本机局域网地址 + 控制台 Token 编码成配对码 + 二维码，
     * 让电脑端 LumiClaw「手机控制台 → 扫码配对」一次性填好，免去手动输 IP/端口/Token。
     */
    fun showPcPairingQr(context: Context) {
        try {
            val ip = com.apk.claw.android.server.ConfigServerManager.getLanIpAddress(context)
            if (ip.isNullOrBlank()) {
                Toast.makeText(context, "未连接 WiFi/局域网，无法生成配对码", Toast.LENGTH_LONG).show()
                return
            }
            val token = com.apk.claw.android.utils.KVUtils.getApiToken()
            if (token.isBlank()) {
                Toast.makeText(context, "请先在「API Token」里设置控制台令牌", Toast.LENGTH_LONG).show()
                return
            }
            if (!ConfigServerManager.isRunning()) {
                val started = ConfigServerManager.start(context)
                if (started) {
                    KVUtils.setConfigServerEnabled(true)
                    updateTrailingText(MenuAction.LAN_CONFIG.name, getLanConfigTrailingText())
                }
            }
            val readiness = PcPairingReadinessPolicy.evaluate(
                lanIp = ip,
                tokenConfigured = TokenValidator.isTokenConfigured(),
                serverRunning = ConfigServerManager.isRunning(),
                serverPort = ConfigServerManager.getPort()
            )
            if (!readiness.ready) {
                Toast.makeText(context, readiness.message, Toast.LENGTH_LONG).show()
                updateTrailingText(MenuAction.LAN_CONFIG.name, getLanConfigTrailingText())
                return
            }
            val baseUrl = readiness.baseUrl
            val name = android.os.Build.MODEL ?: "APKClaw"
            val enc = { s: String -> java.net.URLEncoder.encode(s, "UTF-8") }
            val code = "lumi://pair?b=${enc(baseUrl)}&t=${enc(token)}&n=${enc(name)}"
            val bmp = generateQrBitmap(code, 560)
            if (bmp == null) {
                Toast.makeText(context, "二维码生成失败", Toast.LENGTH_SHORT).show()
                return
            }
            QRCodeDialog.show(
                context = context,
                title = "电脑配对",
                subtitle = "在电脑 LumiClaw「手机控制台」点「新增」，把下面这串配对码粘进「配对码」框即可：\n\n$code",
                qrBitmap = bmp
            )
        } catch (e: Exception) {
            Toast.makeText(context, "生成配对码失败：${e.message}", Toast.LENGTH_SHORT).show()
        }
    }
}
