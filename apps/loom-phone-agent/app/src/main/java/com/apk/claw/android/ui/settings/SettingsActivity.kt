package com.apk.claw.android.ui.settings

import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.apk.claw.android.R
import com.apk.claw.android.base.BaseActivity
import com.apk.claw.android.widget.AlertDialog
import com.apk.claw.android.widget.CommonToolbar
import com.apk.claw.android.widget.MenuGroup
import com.apk.claw.android.widget.MenuItem
import kotlinx.coroutines.launch
import android.content.Intent
import com.apk.claw.android.appViewModel
import com.apk.claw.android.floating.FloatingCircleManager
import com.apk.claw.android.server.ConfigServerManager

/**
 * 设置页面
 */
class SettingsActivity : BaseActivity() {

    private val viewModel by lazy {
        ViewModelProvider(this)[SettingsViewModel::class.java]
    }

    // 保存 MenuItem 引用以便动态更新
    private val menuItems = mutableMapOf<String, MenuItem>()

    // 注册 LLM 配置页返回后刷新
    private val llmConfigLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { _ ->
        viewModel.refresh()
    }

    // 注册手机配对页返回后刷新
    private val pcPairingLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { _ ->
        viewModel.refresh()
    }

    // 注册通道配置结果回调
    private val channelConfigLauncher = ChannelConfigActivity.registerLauncher(this) { result ->
        result?.let {
            // 配置成功后刷新设置项（刷新"已绑定"/"未绑定"状态）
            viewModel.refresh()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        initToolbar()
        initMenuGroups()
        observeViewModel()
    }

    override fun onResume() {
        super.onResume()
        refreshSettings()
    }

    private fun initToolbar() {
        findViewById<CommonToolbar>(R.id.toolbar).apply {
            setTitle(getString(R.string.settings_title))
            showBackButton(true) { finish() }
        }
    }

    private fun refreshSettings() {
        viewModel.refresh()
    }

    private fun initMenuGroups() {
        val connectionGroup = findViewById<MenuGroup>(R.id.connectionGroup)
        connectionGroup.setTitle(getString(R.string.settings_group_connection))

        menuItems[SettingsViewModel.MenuAction.PC_PAIRING.name] = connectionGroup.addMenuItem(
            leadingIcon = R.drawable.ic_pc_pairing,
            title = getString(R.string.menu_pc_pairing),
            onClick = { viewModel.onMenuItemClick(SettingsViewModel.MenuAction.PC_PAIRING) },
            showDivider = true
        )
        menuItems[SettingsViewModel.MenuAction.PC_PAIRING.name]?.setLeadingIconColor(getColor(R.color.colorTextPrimary))
        menuItems[SettingsViewModel.MenuAction.LAN_CONFIG.name] = connectionGroup.addMenuItem(
            leadingIcon = R.drawable.ic_lan_config,
            title = getString(R.string.menu_lan_config),
            onClick = { viewModel.onMenuItemClick(SettingsViewModel.MenuAction.LAN_CONFIG) },
            showDivider = true
        )
        menuItems[SettingsViewModel.MenuAction.LAN_CONFIG.name]?.setLeadingIconColor(getColor(R.color.colorTextPrimary))
        menuItems[SettingsViewModel.MenuAction.CONNECTION_DIAGNOSTICS.name] = connectionGroup.addMenuItem(
            leadingIcon = R.drawable.ic_settings,
            title = getString(R.string.menu_connection_diagnostics),
            onClick = { viewModel.onMenuItemClick(SettingsViewModel.MenuAction.CONNECTION_DIAGNOSTICS) },
            showDivider = false
        )
        menuItems[SettingsViewModel.MenuAction.CONNECTION_DIAGNOSTICS.name]?.setLeadingIconColor(getColor(R.color.colorTextPrimary))

        // 通道
        val channelGroup = findViewById<MenuGroup>(R.id.channelGroup)
        channelGroup.setTitle(getString(R.string.settings_group_channel))

        menuItems[SettingsViewModel.MenuAction.DINGDING.name] = channelGroup.addMenuItem(
            leadingIcon = R.drawable.ic_channel_dingtalk,
            title = getString(R.string.menu_dingtalk),
            onClick = { viewModel.onMenuItemClick(SettingsViewModel.MenuAction.DINGDING) },
            showDivider = true
        )
        menuItems[SettingsViewModel.MenuAction.FEISHU.name] = channelGroup.addMenuItem(
            leadingIcon = R.drawable.ic_channel_feishu,
            title = getString(R.string.menu_feishu),
            onClick = { viewModel.onMenuItemClick(SettingsViewModel.MenuAction.FEISHU) },
            showDivider = true
        )
        menuItems[SettingsViewModel.MenuAction.QQ.name] = channelGroup.addMenuItem(
            leadingIcon = R.drawable.ic_channel_qq,
            title = getString(R.string.menu_qq),
            onClick = { viewModel.onMenuItemClick(SettingsViewModel.MenuAction.QQ) },
            showDivider = true
        )
        menuItems[SettingsViewModel.MenuAction.DISCORD.name] = channelGroup.addMenuItem(
            leadingIcon = R.drawable.ic_channel_discord,
            title = getString(R.string.menu_discord),
            onClick = { viewModel.onMenuItemClick(SettingsViewModel.MenuAction.DISCORD) },
            showDivider = true
        )
        menuItems[SettingsViewModel.MenuAction.TELEGRAM.name] = channelGroup.addMenuItem(
            leadingIcon = R.drawable.ic_channel_telegram,
            title = getString(R.string.menu_telegram),
            onClick = { viewModel.onMenuItemClick(SettingsViewModel.MenuAction.TELEGRAM) },
            showDivider = true
        )
        menuItems[SettingsViewModel.MenuAction.WECHAT.name] = channelGroup.addMenuItem(
            leadingIcon = R.drawable.ic_channel_wechat,
            title = getString(R.string.menu_wechat),
            onClick = { viewModel.onMenuItemClick(SettingsViewModel.MenuAction.WECHAT) },
            showDivider = true
        )
        val modelGroup = findViewById<MenuGroup>(R.id.modelGroup)
        modelGroup.setTitle(getString(R.string.settings_group_model))

        menuItems[SettingsViewModel.MenuAction.LLM_CONFIG.name] = modelGroup.addMenuItem(
            leadingIcon = R.drawable.icon_current_model,
            title = getString(R.string.menu_llm_config),
            onClick = { viewModel.onMenuItemClick(SettingsViewModel.MenuAction.LLM_CONFIG) },
            showDivider = false
        )
        menuItems[SettingsViewModel.MenuAction.LLM_CONFIG.name]?.setLeadingIconColor(getColor(R.color.colorTextPrimary))

        val displayGroup = findViewById<MenuGroup>(R.id.displayGroup)
        displayGroup.setTitle(getString(R.string.settings_group_display))

        menuItems[SettingsViewModel.MenuAction.FLOATING_CLICK.name] = displayGroup.addMenuItem(
            leadingIcon = R.drawable.ic_lumi_agent_mark,
            title = getString(R.string.menu_floating_click_enabled),
            onClick = {
                viewModel.setFloatingClickEnabled(!FloatingCircleManager.isFloatingClickEnabled())
            },
            showTrailingIcon = false,
            showDivider = true
        ).apply {
            setSwitchVisible(true)
            setSwitchChecked(FloatingCircleManager.isFloatingClickEnabled())
            setOnSwitchChangedListener(viewModel::setFloatingClickEnabled)
        }

        menuItems[SettingsViewModel.MenuAction.FLOATING_SIZE.name] = displayGroup.addMenuItem(
            leadingIcon = R.drawable.ic_lumi_agent_mark,
            title = getString(R.string.menu_floating_circle_size),
            onClick = { viewModel.onMenuItemClick(SettingsViewModel.MenuAction.FLOATING_SIZE) },
            showDivider = false
        )
    }

    private fun observeViewModel() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                // 监听设置项变化，动态更新 UI
                launch {
                    viewModel.settingItems.collect { items ->
                        items.forEach { (key, value) ->
                            when (value) {
                                is SettingsViewModel.SettingValue.Text -> {
                                    menuItems[key]?.setTrailingText(value.text)
                                }
                                is SettingsViewModel.SettingValue.Switch -> {
                                    menuItems[key]?.setSwitchChecked(value.isOn)
                                }
                            }
                        }
                    }
                }

                // 监听 H5 页面配置变更（含 LLM/通道），刷新 UI 并重新初始化 Agent 与通道
                launch {
                    ConfigServerManager.configChanged.collect {
                        viewModel.refresh()
                        appViewModel.initAgent()
                        appViewModel.afterInit()
                    }
                }

                // 监听菜单点击事件
                launch {
                    viewModel.menuClickEvent.collect { action ->
                        when (action) {
                            SettingsViewModel.MenuAction.DINGDING -> {
                                if (viewModel.isDingtalkBound()) {
                                    showUnbindDialog(getString(R.string.channel_dingtalk)) {
                                        viewModel.unbindDingtalk()
                                        Toast.makeText(this@SettingsActivity, R.string.common_unbound_success, Toast.LENGTH_SHORT).show()
                                    }
                                } else {
                                    channelConfigLauncher.launch(ChannelConfigActivity.ChannelType.DINGTALK)
                                }
                            }
                            SettingsViewModel.MenuAction.FEISHU -> {
                                if (viewModel.isFeishuBound()) {
                                    showUnbindDialog(getString(R.string.channel_feishu)) {
                                        viewModel.unbindFeishu()
                                        Toast.makeText(this@SettingsActivity, R.string.common_unbound_success, Toast.LENGTH_SHORT).show()
                                    }
                                } else {
                                    channelConfigLauncher.launch(ChannelConfigActivity.ChannelType.FEISHU)
                                }
                            }
                            SettingsViewModel.MenuAction.WECHAT -> {
                                if (viewModel.isWechatBound()) {
                                    showUnbindDialog(getString(R.string.channel_wechat)) {
                                        viewModel.unbindWeChat()
                                        Toast.makeText(this@SettingsActivity, R.string.common_unbound_success, Toast.LENGTH_SHORT).show()
                                    }
                                } else {
                                    viewModel.startWeChatQrLogin(this@SettingsActivity)
                                }
                            }
                            SettingsViewModel.MenuAction.QQ -> {
                                if (viewModel.isQqBound()) {
                                    showUnbindDialog(getString(R.string.channel_qq)) {
                                        viewModel.unbindQq()
                                        Toast.makeText(this@SettingsActivity, R.string.common_unbound_success, Toast.LENGTH_SHORT).show()
                                    }
                                } else {
                                    channelConfigLauncher.launch(ChannelConfigActivity.ChannelType.QQ)
                                }
                            }
                            SettingsViewModel.MenuAction.DISCORD -> {
                                if (viewModel.isDiscordBound()) {
                                    showUnbindDialog(getString(R.string.channel_discord)) {
                                        viewModel.unbindDiscord()
                                        Toast.makeText(this@SettingsActivity, R.string.common_unbound_success, Toast.LENGTH_SHORT).show()
                                    }
                                } else {
                                    channelConfigLauncher.launch(ChannelConfigActivity.ChannelType.DISCORD)
                                }
                            }
                            SettingsViewModel.MenuAction.TELEGRAM -> {
                                if (viewModel.isTelegramBound()) {
                                    showUnbindDialog(getString(R.string.channel_telegram)) {
                                        viewModel.unbindTelegram()
                                        Toast.makeText(this@SettingsActivity, R.string.common_unbound_success, Toast.LENGTH_SHORT).show()
                                    }
                                } else {
                                    channelConfigLauncher.launch(ChannelConfigActivity.ChannelType.TELEGRAM)
                                }
                            }
                            SettingsViewModel.MenuAction.LAN_CONFIG -> {
                                viewModel.toggleConfigServer(this@SettingsActivity)
                            }
                            SettingsViewModel.MenuAction.CONNECTION_DIAGNOSTICS -> {
                                AlertDialog.show(
                                    this@SettingsActivity,
                                    getString(R.string.connection_diagnostics_title),
                                    viewModel.connectionDiagnostics()
                                )
                            }
                            SettingsViewModel.MenuAction.PC_PAIRING -> {
                                pcPairingLauncher.launch(Intent(this@SettingsActivity, PcPairingActivity::class.java))
                            }
                            SettingsViewModel.MenuAction.LLM_CONFIG -> {
                                llmConfigLauncher.launch(Intent(this@SettingsActivity, LlmConfigActivity::class.java))
                            }
                            SettingsViewModel.MenuAction.FLOATING_CLICK -> Unit
                            SettingsViewModel.MenuAction.FLOATING_SIZE -> {
                                showFloatingSizeDialog()
                            }
                            null -> {}
                        }
                        viewModel.clearMenuClickEvent()
                    }
                }
            }
        }
    }

    /**
     * 显示解除绑定确认弹窗
     */
    private fun showUnbindDialog(channelName: String, onUnbind: () -> Unit) {
        AlertDialog.showWarm(
            context = this,
            title = getString(R.string.unbind_title),
            message = getString(R.string.unbind_message, channelName, channelName),
            actionTitle = getString(R.string.unbind_action),
            onAction = onUnbind
        )
    }

    private fun showFloatingSizeDialog() {
        val sizes = FloatingCircleManager.FloatingSize.entries.toTypedArray()
        val labels = sizes.map { size ->
            when (size) {
                FloatingCircleManager.FloatingSize.SMALL -> getString(R.string.floating_size_small)
                FloatingCircleManager.FloatingSize.MEDIUM -> getString(R.string.floating_size_medium)
                FloatingCircleManager.FloatingSize.LARGE -> getString(R.string.floating_size_large)
            }
        }.toTypedArray()
        val currentIndex = sizes.indexOf(FloatingCircleManager.getFloatingSize()).coerceAtLeast(0)
        android.app.AlertDialog.Builder(this)
            .setTitle(getString(R.string.menu_floating_circle_size))
            .setSingleChoiceItems(labels, currentIndex) { dialog, which ->
                FloatingCircleManager.setFloatingSize(sizes[which])
                viewModel.refresh()
                Toast.makeText(this, getString(R.string.floating_size_saved, labels[which]), Toast.LENGTH_SHORT).show()
                dialog.dismiss()
            }
            .setNegativeButton(R.string.common_cancel, null)
            .show()
    }
}
