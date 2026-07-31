package com.apk.claw.android.ui.settings

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.ImageView
import android.widget.RadioGroup
import android.widget.TextView
import android.widget.Toast
import com.apk.claw.android.R
import com.apk.claw.android.base.BaseActivity
import com.apk.claw.android.server.ConfigServerManager
import com.apk.claw.android.server.PcPairingReadinessPolicy
import com.apk.claw.android.server.PairingTransportMode
import com.apk.claw.android.server.PhonePairingBootstrap
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.widget.CommonToolbar
import com.apk.claw.android.widget.KButton
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter

/**
 * Creates a phone-owned, short-lived pairing code without exposing the
 * long-lived phone credential to the user.
 */
class PcPairingActivity : BaseActivity() {
    data class PairingRuntime(
        val lanIp: String?,
        val serverRunning: Boolean,
        val serverPort: Int?
    )

    companion object {
        @Volatile
        private var pairingRuntimeForTests: PairingRuntime? = null

        @JvmStatic
        fun setPairingRuntimeForTests(runtime: PairingRuntime?) {
            pairingRuntimeForTests = runtime
        }
    }

    private val handler = Handler(Looper.getMainLooper())
    private var session: PhonePairingBootstrap.SessionView? = null
    private var transportMode = PairingTransportMode.USB

    private lateinit var codeView: TextView
    private lateinit var codeSection: View
    private lateinit var expiryView: TextView
    private lateinit var endpointView: TextView
    private lateinit var tipView: TextView
    private lateinit var statusView: TextView
    private lateinit var payloadView: TextView
    private lateinit var qrView: ImageView

    private val countdown = object : Runnable {
        override fun run() {
            val active = session ?: return
            val remainingSeconds = ((active.expiresAt - System.currentTimeMillis()).coerceAtLeast(0L) + 999L) / 1000L
            expiryView.text = if (remainingSeconds > 0L) {
                getString(R.string.pc_pairing_expiry, remainingSeconds)
            } else {
                getString(R.string.pc_pairing_expired)
            }
            if (remainingSeconds > 0L) handler.postDelayed(this, 1_000L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_pc_pairing)

        findViewById<CommonToolbar>(R.id.toolbar).apply {
            setTitle(getString(R.string.pc_pairing_title))
            showBackButton(true) { finish() }
        }
        tipView = findViewById(R.id.tvTip)
        codeSection = findViewById(R.id.pairingCodeSection)
        codeView = findViewById(R.id.tvPairingCode)
        expiryView = findViewById(R.id.tvPairingExpiry)
        endpointView = findViewById(R.id.tvPairingEndpoint)
        statusView = findViewById(R.id.tvPairingStatus)
        payloadView = findViewById(R.id.tvPairingPayload)
        qrView = findViewById(R.id.ivPairingQr)

        findViewById<KButton>(R.id.btnCopy).setOnClickListener { copyPayload() }
        findViewById<KButton>(R.id.btnGenerate).setOnClickListener { createPairingSession() }
        findViewById<RadioGroup>(R.id.pairingTransportSelector)
            .setOnCheckedChangeListener { _, checkedId ->
                val selectedMode = when (checkedId) {
                    R.id.rbPairingUsb -> PairingTransportMode.USB
                    else -> PairingTransportMode.LAN
                }
                if (selectedMode != transportMode) {
                    transportMode = selectedMode
                    createPairingSession()
                }
            }
        createPairingSession()
    }

    override fun onDestroy() {
        handler.removeCallbacks(countdown)
        super.onDestroy()
    }

    private fun createPairingSession() {
        handler.removeCallbacks(countdown)
        val runtime = currentPairingRuntime() ?: return
        val readiness = PcPairingReadinessPolicy.evaluate(
            lanIp = runtime.lanIp,
            serverRunning = runtime.serverRunning,
            serverPort = runtime.serverPort,
            transportMode = transportMode
        )
        if (!readiness.ready) {
            showUnavailable(readiness.message)
            return
        }
        val next = PhonePairingBootstrap.createSession(
            baseUrl = readiness.baseUrl,
            deviceInstanceId = KVUtils.ensureLumiDeviceInstanceId(),
            deviceName = Build.MODEL ?: "Android Phone",
            transportHint = readiness.transportHint
        )
        session = next
        val usesUsbCode = next.transportHint == "usb"
        codeSection.visibility = if (usesUsbCode) View.VISIBLE else View.GONE
        codeView.text = if (usesUsbCode) next.code else ""
        endpointView.text = readiness.baseUrl
        tipView.setText(
            if (usesUsbCode) R.string.pc_pairing_tip_usb else R.string.pc_pairing_tip_lan
        )
        payloadView.text = next.payload
        qrView.setImageBitmap(generateQrBitmap(next.payload, 720))
        statusView.text = if (usesUsbCode) {
            getString(R.string.pc_pairing_usb_ready)
        } else {
            getString(R.string.pc_pairing_lan_ready)
        }
        handler.post(countdown)
    }

    private fun currentPairingRuntime(): PairingRuntime? {
        pairingRuntimeForTests?.let { return it }
        if (!ConfigServerManager.isRunning()) {
            if (!ConfigServerManager.start(this)) {
                showUnavailable(getString(R.string.pc_pairing_server_failed))
                return null
            }
            KVUtils.setConfigServerEnabled(true)
        }
        return PairingRuntime(
            lanIp = ConfigServerManager.getLanIpAddress(this),
            serverRunning = ConfigServerManager.isRunning(),
            serverPort = ConfigServerManager.getPort()
        )
    }

    private fun copyPayload() {
        val payload = session?.payload.orEmpty()
        if (payload.isBlank()) {
            Toast.makeText(this, R.string.pc_pairing_expired, Toast.LENGTH_SHORT).show()
            return
        }
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("LOOM pairing", payload))
        Toast.makeText(this, R.string.pc_pairing_copied, Toast.LENGTH_SHORT).show()
    }

    private fun showUnavailable(message: String) {
        session = null
        codeSection.visibility = View.GONE
        codeView.text = "------"
        expiryView.text = ""
        endpointView.text = ""
        payloadView.text = ""
        qrView.setImageDrawable(null)
        statusView.text = message
    }

    private fun generateQrBitmap(content: String, size: Int): Bitmap {
        val hints = mapOf(
            EncodeHintType.MARGIN to 1,
            EncodeHintType.CHARACTER_SET to "UTF-8"
        )
        val matrix = QRCodeWriter().encode(content, BarcodeFormat.QR_CODE, size, size, hints)
        val bitmap = Bitmap.createBitmap(size, size, Bitmap.Config.RGB_565)
        for (x in 0 until size) {
            for (y in 0 until size) {
                bitmap.setPixel(x, y, if (matrix.get(x, y)) Color.BLACK else Color.WHITE)
            }
        }
        return bitmap
    }
}
