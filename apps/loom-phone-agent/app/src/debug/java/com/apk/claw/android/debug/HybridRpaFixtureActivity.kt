package com.apk.claw.android.debug

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.AttributeSet
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.apk.claw.android.R
import com.apk.claw.android.server.ConfigServerManager
import com.apk.claw.android.server.TokenValidator
import com.apk.claw.android.utils.KVUtils

/** Debug-only deterministic surface for exercising the hybrid RPA runtime. */
class HybridRpaFixtureActivity : AppCompatActivity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var resultText: TextView
    private val delayedResult = Runnable { resultText.text = DELAYED_VERIFIED }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_hybrid_rpa_fixture)
        resultText = findViewById(R.id.result_text)
        findViewById<Button>(R.id.native_target).setOnClickListener {
            handler.removeCallbacks(delayedResult)
            resultText.text = NATIVE_VERIFIED
        }
        findViewById<Button>(R.id.delayed_target).setOnClickListener {
            handler.removeCallbacks(delayedResult)
            resultText.text = DELAYED_PENDING
            handler.postDelayed(delayedResult, 700L)
        }
        findViewById<Button>(R.id.reset_target).setOnClickListener { resetFixture() }
        configureFromAdb(intent)
        resetFixture()
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        configureFromAdb(intent)
    }

    override fun onDestroy() {
        handler.removeCallbacks(delayedResult)
        super.onDestroy()
    }

    private fun resetFixture() {
        handler.removeCallbacks(delayedResult)
        resultText.text = FIXTURE_READY
    }

    private fun configureFromAdb(intent: android.content.Intent) {
        if (intent.getBooleanExtra(HYBRID_RPA_RESTORE, false)) {
            restoreDebugConfiguration()
            return
        }
        if (intent.getBooleanExtra(HYBRID_RPA_SNAPSHOT_ONLY, false)) {
            ensureRecoverySnapshot()
            return
        }
        if (!intent.getBooleanExtra(HYBRID_RPA_CONFIGURE, false)) return
        val candidate = intent.getStringExtra(HYBRID_RPA_TOKEN)?.trim().orEmpty()
        if (candidate.length !in MIN_TOKEN_LENGTH..MAX_TOKEN_LENGTH) return

        if (!ensureRecoverySnapshot()) return

        // This debug-only hook delegates token storage and server lifecycle to production APIs.
        TokenValidator.setToken(candidate)
        val enabledSaved = KVUtils.setConfigServerEnabled(true)
        KVUtils.sync()
        if (!enabledSaved || KVUtils.getApiToken() != candidate || !KVUtils.isConfigServerEnabled()) return
        if (!ConfigServerManager.start(applicationContext)) return
        resetFixture()
    }

    private fun ensureRecoverySnapshot(): Boolean {
        val recovery = getSharedPreferences(RECOVERY_PREFS, Context.MODE_PRIVATE)
        if (recovery.getBoolean(KEY_SNAPSHOT_TAKEN, false)) return true
        return recovery.edit()
            .putString(KEY_ORIGINAL_TOKEN, KVUtils.getApiToken())
            .putBoolean(KEY_ORIGINAL_SERVER_ENABLED, KVUtils.isConfigServerEnabled())
            .putBoolean(KEY_ORIGINAL_SERVER_RUNNING, ConfigServerManager.isRunning())
            .putBoolean(KEY_SNAPSHOT_TAKEN, true)
            .commit()
    }

    private fun restoreDebugConfiguration() {
        val recovery = getSharedPreferences(RECOVERY_PREFS, Context.MODE_PRIVATE)
        if (!recovery.getBoolean(KEY_SNAPSHOT_TAKEN, false)) return

        val originalToken = recovery.getString(KEY_ORIGINAL_TOKEN, "").orEmpty()
        val originalServerEnabled = recovery.getBoolean(KEY_ORIGINAL_SERVER_ENABLED, false)
        val originalServerRunning = recovery.getBoolean(KEY_ORIGINAL_SERVER_RUNNING, false)
        ConfigServerManager.stop()
        TokenValidator.setToken(originalToken)
        val enabledSaved = KVUtils.setConfigServerEnabled(originalServerEnabled)
        KVUtils.sync()
        val storageRestored = enabledSaved &&
            KVUtils.getApiToken() == originalToken &&
            KVUtils.isConfigServerEnabled() == originalServerEnabled
        val serverRestored = storageRestored &&
            (!originalServerRunning || ConfigServerManager.start(applicationContext))
        if (serverRestored) recovery.edit().clear().commit()
    }

    companion object {
        const val HYBRID_RPA_CONFIGURE = "com.apk.claw.android.debug.HYBRID_RPA_CONFIGURE"
        const val HYBRID_RPA_TOKEN = "com.apk.claw.android.debug.HYBRID_RPA_TOKEN"
        const val HYBRID_RPA_RESTORE = "com.apk.claw.android.debug.HYBRID_RPA_RESTORE"
        const val HYBRID_RPA_SNAPSHOT_ONLY = "com.apk.claw.android.debug.HYBRID_RPA_SNAPSHOT_ONLY"
        private const val RECOVERY_PREFS = "hybrid_rpa_fixture_recovery"
        private const val KEY_SNAPSHOT_TAKEN = "snapshot_taken"
        private const val KEY_ORIGINAL_TOKEN = "original_token"
        private const val KEY_ORIGINAL_SERVER_ENABLED = "original_server_enabled"
        private const val KEY_ORIGINAL_SERVER_RUNNING = "original_server_running"
        private const val MIN_TOKEN_LENGTH = 16
        private const val MAX_TOKEN_LENGTH = 128
        private const val FIXTURE_READY = "fixture_ready"
        private const val NATIVE_VERIFIED = "native_verified"
        private const val DELAYED_PENDING = "delayed_pending"
        private const val DELAYED_VERIFIED = "delayed_verified"
    }
}

class HybridVisualTargetView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(0, 232, 255) }
    private val outline = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.BLACK
        style = Paint.Style.STROKE
        strokeWidth = 8f
    }
    private val marker = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(255, 46, 120) }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val inset = 12f
        canvas.drawRect(inset, inset, width - inset, height - inset, fill)
        canvas.drawRect(inset, inset, width - inset, height - inset, outline)
        canvas.drawCircle(width / 2f, height / 2f, width.coerceAtMost(height) / 5f, marker)
        canvas.drawLine(width * .2f, height / 2f, width * .8f, height / 2f, outline)
        canvas.drawLine(width / 2f, height * .2f, width / 2f, height * .8f, outline)
    }
}
