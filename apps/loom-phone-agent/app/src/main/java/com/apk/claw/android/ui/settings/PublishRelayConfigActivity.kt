package com.apk.claw.android.ui.settings

import android.os.Bundle
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.lifecycle.lifecycleScope
import com.apk.claw.android.R
import com.apk.claw.android.base.BaseActivity
import com.apk.claw.android.publish.PublishRelayManager
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.widget.CommonToolbar
import com.apk.claw.android.widget.KButton
import com.google.android.material.switchmaterial.SwitchMaterial
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class PublishRelayConfigActivity : BaseActivity() {

    private lateinit var etBaseUrl: EditText
    private lateinit var etChannelId: EditText
    private lateinit var etRelayToken: EditText
    private lateinit var swEnabled: SwitchMaterial
    private lateinit var tvStatus: TextView
    private lateinit var btnSave: KButton

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_publish_relay_config)

        findViewById<CommonToolbar>(R.id.toolbar).apply {
            setTitle(getString(R.string.publish_relay_config_title))
            showBackButton(true) { finish() }
        }

        etBaseUrl = findViewById(R.id.etBaseUrl)
        etChannelId = findViewById(R.id.etChannelId)
        etRelayToken = findViewById(R.id.etRelayToken)
        swEnabled = findViewById(R.id.swEnabled)
        tvStatus = findViewById(R.id.tvStatus)
        btnSave = findViewById(R.id.btnSave)

        etBaseUrl.setText(KVUtils.getPublishRelayBaseUrl())
        etChannelId.setText(KVUtils.getPublishRelayChannelId())
        etRelayToken.setText(KVUtils.getPublishRelayToken())
        swEnabled.isChecked = KVUtils.isPublishRelayEnabled()
        tvStatus.text = getString(
            if (KVUtils.isPublishRelayEnabled()) {
                R.string.publish_relay_status_on
            } else {
                R.string.publish_relay_status_off
            }
        )

        btnSave.setOnClickListener {
            saveConfig()
        }
    }

    private fun saveConfig() {
        val baseUrl = etBaseUrl.text.toString().trim().trimEnd('/')
        val channelId = etChannelId.text.toString().trim()
        val relayToken = etRelayToken.text.toString().trim()
        val enabled = swEnabled.isChecked

        if (enabled && baseUrl.isBlank()) {
            Toast.makeText(this, R.string.publish_relay_config_missing_url, Toast.LENGTH_SHORT).show()
            return
        }
        if (enabled && channelId.isBlank()) {
            Toast.makeText(this, R.string.publish_relay_config_missing_channel, Toast.LENGTH_SHORT).show()
            return
        }
        if (enabled && !baseUrl.startsWith("http://", ignoreCase = true) && !baseUrl.startsWith("https://", ignoreCase = true)) {
            Toast.makeText(this, R.string.publish_relay_config_invalid_url, Toast.LENGTH_SHORT).show()
            return
        }

        KVUtils.setPublishRelayBaseUrl(baseUrl)
        KVUtils.setPublishRelayChannelId(channelId)
        KVUtils.setPublishRelayToken(relayToken)

        if (!enabled) {
            KVUtils.setPublishRelayEnabled(false)
            PublishRelayManager.syncFromStorage()
            setResult(RESULT_OK)
            Toast.makeText(this, R.string.publish_relay_config_saved, Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        btnSave.isEnabled = false
        tvStatus.text = getString(R.string.publish_relay_config_checking)
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                PublishRelayManager.checkRelayConfig(baseUrl, channelId, relayToken)
            }
            btnSave.isEnabled = true
            if (result.ok) {
                KVUtils.setPublishRelayEnabled(true)
                PublishRelayManager.syncFromStorage()
                tvStatus.text = getString(R.string.publish_relay_config_check_ok)
                setResult(RESULT_OK)
                Toast.makeText(this@PublishRelayConfigActivity, R.string.publish_relay_config_saved, Toast.LENGTH_SHORT).show()
                finish()
            } else {
                KVUtils.setPublishRelayEnabled(false)
                PublishRelayManager.syncFromStorage()
                swEnabled.isChecked = false
                tvStatus.text = getString(R.string.publish_relay_config_check_failed, result.message)
                Toast.makeText(this@PublishRelayConfigActivity, R.string.publish_relay_config_check_failed_short, Toast.LENGTH_SHORT).show()
            }
        }
    }
}
