package com.apk.claw.android.ui.settings

import android.os.Bundle
import android.widget.Toast
import com.apk.claw.android.R
import com.apk.claw.android.base.BaseActivity
import com.apk.claw.android.server.TokenValidator
import com.apk.claw.android.widget.CommonToolbar
import com.apk.claw.android.widget.KButton
import android.widget.EditText
import java.security.SecureRandom

/**
 * API Token 配置页
 * 用于设置外部 HTTP API 认证 Token
 */
class ApiTokenConfigActivity : BaseActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_api_token_config)

        findViewById<CommonToolbar>(R.id.toolbar).apply {
            setTitle(getString(R.string.api_token_config_title))
            showBackButton(true) { finish() }
        }

        val etToken = findViewById<EditText>(R.id.etToken)
        val btnGenerate = findViewById<KButton>(R.id.btnGenerate)
        val btnSave = findViewById<KButton>(R.id.btnSave)

        // 显示当前 Token（脱敏显示后4位）
        val currentToken = TokenValidator.getMaskedToken()
        etToken.setText(currentToken)

        // 生成随机 Token
        btnGenerate.setOnClickListener {
            val randomToken = generateRandomToken(16)
            etToken.setText(randomToken)
        }

        // 保存 Token
        btnSave.setOnClickListener {
            val token = etToken.text.toString().trim()

            if (token.isEmpty()) {
                Toast.makeText(this, getString(R.string.api_token_config_required), Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            TokenValidator.setToken(token)
            Toast.makeText(this, getString(R.string.api_token_config_saved), Toast.LENGTH_SHORT).show()
            finish()
        }
    }

    /**
     * 生成随机 Token
     * 使用字母和数字，长度可配置
     */
    private fun generateRandomToken(length: Int): String {
        val chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        val random = SecureRandom()
        return StringBuilder(length).apply {
            for (i in 0 until length) {
                append(chars[random.nextInt(chars.length)])
            }
        }.toString()
    }
}