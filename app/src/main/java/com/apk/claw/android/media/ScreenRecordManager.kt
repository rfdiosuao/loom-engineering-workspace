package com.apk.claw.android.media

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Environment
import com.apk.claw.android.service.ScreenRecordService
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.atomic.AtomicReference

object ScreenRecordManager {

    private const val MAX_RECORD_SECONDS = 600
    private const val DEFAULT_RECORD_SECONDS = 180

    enum class State {
        IDLE,
        REQUESTING_PERMISSION,
        RECORDING,
        ERROR
    }

    data class Options(
        val width: Int = 0,
        val height: Int = 0,
        val fps: Int = 30,
        val bitRate: Int = 4_000_000,
        val maxSeconds: Int = DEFAULT_RECORD_SECONDS,
        val filename: String? = null
    )

    private val state = AtomicReference(State.IDLE)

    @Volatile
    private var pendingOptions: Options = Options()

    @Volatile
    private var currentFile: File? = null

    @Volatile
    private var latestFile: File? = null

    @Volatile
    private var currentStartedAt: Long = 0L

    @Volatile
    private var lastError: String? = null

    @Volatile
    private var lastWidth: Int = 0

    @Volatile
    private var lastHeight: Int = 0

    fun requestStart(context: Context, options: Options): JsonObject {
        val currentState = state.get()
        if (currentState == State.REQUESTING_PERMISSION || currentState == State.RECORDING) {
            return status(context).apply {
                addProperty("accepted", false)
                addProperty("reason", "screen_record_busy")
            }
        }

        state.set(State.REQUESTING_PERMISSION)
        pendingOptions = normalizeOptions(options)
        lastError = null

        val intent = Intent(context, ScreenCapturePermissionActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)

        return status(context).apply {
            addProperty("accepted", true)
            addProperty("reason", "permission_prompt_shown")
            addProperty("requiresUserConsent", true)
        }
    }

    fun buildCaptureIntent(activity: Activity): Intent {
        val manager = activity.getSystemService(MediaProjectionManager::class.java)
        return manager.createScreenCaptureIntent()
    }

    fun onPermissionResult(context: Context, resultCode: Int, data: Intent?) {
        if (resultCode != Activity.RESULT_OK || data == null) {
            state.set(State.ERROR)
            lastError = "Screen capture permission denied"
            return
        }

        val intent = Intent(context, ScreenRecordService::class.java).apply {
            action = ScreenRecordService.ACTION_START
            putExtra(ScreenRecordService.EXTRA_RESULT_CODE, resultCode)
            putExtra(ScreenRecordService.EXTRA_RESULT_DATA, data)
            putExtra(ScreenRecordService.EXTRA_WIDTH, pendingOptions.width)
            putExtra(ScreenRecordService.EXTRA_HEIGHT, pendingOptions.height)
            putExtra(ScreenRecordService.EXTRA_FPS, pendingOptions.fps)
            putExtra(ScreenRecordService.EXTRA_BIT_RATE, pendingOptions.bitRate)
            putExtra(ScreenRecordService.EXTRA_MAX_SECONDS, pendingOptions.maxSeconds)
            putExtra(ScreenRecordService.EXTRA_FILENAME, pendingOptions.filename)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent)
        } else {
            context.startService(intent)
        }
    }

    fun stop(context: Context): JsonObject {
        if (state.get() != State.RECORDING) {
            return status(context).apply {
                addProperty("accepted", false)
                addProperty("reason", "screen_record_not_running")
            }
        }
        val intent = Intent(context, ScreenRecordService::class.java).apply {
            action = ScreenRecordService.ACTION_STOP
        }
        context.startService(intent)
        return status(context).apply {
            addProperty("accepted", true)
            addProperty("reason", "stop_requested")
        }
    }

    fun onRecordingStarted(file: File, width: Int, height: Int) {
        currentFile = file
        latestFile = file
        currentStartedAt = System.currentTimeMillis()
        lastWidth = width
        lastHeight = height
        lastError = null
        state.set(State.RECORDING)
    }

    fun onRecordingStopped(file: File?) {
        latestFile = file ?: currentFile ?: latestFile
        currentFile = null
        currentStartedAt = 0L
        state.set(State.IDLE)
    }

    fun onRecordingError(message: String) {
        lastError = message
        currentFile = null
        currentStartedAt = 0L
        state.set(State.ERROR)
    }

    fun status(context: Context): JsonObject {
        return JsonObject().apply {
            addProperty("state", state.get().name.lowercase(Locale.US))
            addProperty("recording", state.get() == State.RECORDING)
            addProperty("startedAt", if (currentStartedAt > 0L) iso(currentStartedAt) else "")
            addProperty("durationMs", if (currentStartedAt > 0L) System.currentTimeMillis() - currentStartedAt else 0L)
            addProperty("width", lastWidth)
            addProperty("height", lastHeight)
            addProperty("lastError", lastError ?: "")
            add("current", fileJson(currentFile, context))
            add("latest", fileJson(latestFile, context))
        }
    }

    fun listRecordings(context: Context): JsonArray {
        val result = JsonArray()
        recordingsDir(context).listFiles()
            ?.filter { it.isFile && it.extension.lowercase(Locale.US) == "mp4" }
            ?.sortedByDescending { it.lastModified() }
            ?.forEach { result.add(fileJson(it, context)) }
        return result
    }

    fun createOutputFile(context: Context, requestedName: String?): File {
        val dir = recordingsDir(context)
        if (!dir.exists()) dir.mkdirs()
        val fallback = "apkclaw_record_${timestamp()}.mp4"
        val clean = sanitizeFilename(requestedName).ifBlank { fallback }
        val withExt = if (clean.lowercase(Locale.US).endsWith(".mp4")) clean else "$clean.mp4"
        return dedupeFile(dir, withExt)
    }

    fun resolveRecording(context: Context, id: String?): File? {
        val name = sanitizeFilename(id).ifBlank { return null }
        val dir = recordingsDir(context).canonicalFile
        val file = File(dir, name).canonicalFile
        if (!file.path.startsWith(dir.path) || !file.isFile || file.extension.lowercase(Locale.US) != "mp4") {
            return null
        }
        return file
    }

    private fun recordingsDir(context: Context): File {
        return File(context.getExternalFilesDir(Environment.DIRECTORY_MOVIES), "recordings")
    }

    private fun normalizeOptions(options: Options): Options {
        return options.copy(
            fps = options.fps.coerceIn(10, 60),
            bitRate = options.bitRate.coerceIn(800_000, 20_000_000),
            maxSeconds = options.maxSeconds.coerceIn(1, MAX_RECORD_SECONDS),
            filename = sanitizeFilename(options.filename).ifBlank { null }
        )
    }

    private fun fileJson(file: File?, context: Context): JsonObject {
        val data = JsonObject()
        if (file == null) {
            data.addProperty("exists", false)
            return data
        }
        data.addProperty("exists", file.exists())
        data.addProperty("id", file.name)
        data.addProperty("filename", file.name)
        data.addProperty("path", file.absolutePath)
        data.addProperty("sizeBytes", if (file.exists()) file.length() else 0L)
        data.addProperty("modifiedAt", if (file.exists()) iso(file.lastModified()) else "")
        data.addProperty("downloadUrl", "/api/media/video?id=${file.name}")
        data.addProperty("mimeType", "video/mp4")
        return data
    }

    private fun dedupeFile(dir: File, filename: String): File {
        val base = filename.substringBeforeLast('.', filename)
        val ext = filename.substringAfterLast('.', "")
        var candidate = File(dir, filename)
        var index = 1
        while (candidate.exists()) {
            candidate = File(dir, if (ext.isBlank()) "${base}_$index" else "${base}_$index.$ext")
            index += 1
        }
        return candidate
    }

    private fun sanitizeFilename(value: String?): String {
        return value
            ?.substringAfterLast('/')
            ?.substringAfterLast('\\')
            ?.trim()
            ?.replace(Regex("[\\\\/:*?\"<>|\\p{Cntrl}]"), "_")
            ?.replace(Regex("_+"), "_")
            ?.trim('_', '.', ' ')
            ?.take(96)
            .orEmpty()
    }

    private fun timestamp(): String {
        return SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
    }

    private fun iso(value: Long): String {
        return SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(Date(value))
    }
}
