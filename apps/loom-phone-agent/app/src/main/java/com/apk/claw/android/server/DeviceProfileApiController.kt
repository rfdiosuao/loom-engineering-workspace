package com.apk.claw.android.server

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.Environment
import android.os.StatFs
import android.provider.Settings
import com.apk.claw.android.BuildConfig
import com.apk.claw.android.ClawApplication
import com.apk.claw.android.floating.FloatingCircleManager
import com.apk.claw.android.service.AccessibilityStateInspector
import com.apk.claw.android.service.ClawAccessibilityService
import com.apk.claw.android.utils.KVUtils
import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import fi.iki.elonen.NanoHTTPD
import java.io.File
import java.util.Locale

object DeviceProfileApiController {
    private const val MIME_JSON_UTF8 = "application/json; charset=utf-8"
    private val GAME_PACKAGES = setOf(
        "com.tencent.nrc",
        "com.tencent.tmgp.sgame",
        "com.tencent.tmgp.supercell.brawlstars",
        "com.tencent.start",
        "com.tencent.lolm",
        "com.playdigious.deadcells.epic",
        "com.tencent.tmgp.pubgmhd"
    )

    fun handleGetProfile(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError

        val app = ClawApplication.instance
        val includeApps = getBooleanParam(session, "includeApps") ?: true
        val appLimit = (getIntParam(session, "appLimit") ?: 160).coerceIn(20, 300)
        val accessibilityState = AccessibilityStateInspector.inspect(app)

        val data = JsonObject().apply {
            addProperty("profileVersion", 1)
            addProperty("capturedAt", System.currentTimeMillis())
            val currentScreen = buildCurrentScreenInfo()
            add("device", buildDeviceInfo(app))
            add("capabilities", buildCapabilities(accessibilityState))
            add("memory", buildMemoryInfo(app))
            add("storage", buildStorageInfo())
            add("battery", buildBatteryInfo(app))
            add("currentScreen", currentScreen)
            add("vision", buildVisionHints(currentScreen))
            add("publicDirectories", buildPublicDirectories())
            if (includeApps) {
                add("apps", buildLaunchableApps(app, appLimit))
            }
            addProperty(
                "privacyNote",
                "This profile lists device facts, launchable apps, public directory metadata, and the current accessibility tree summary. It does not read private file contents."
            )
        }

        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    fun buildCurrentScreenInfoForApi(): JsonObject = buildCurrentScreenInfo()

    fun buildVisionHintsForApi(currentScreen: JsonObject): JsonObject = buildVisionHints(currentScreen)

    private fun buildDeviceInfo(context: Context): JsonObject {
        val metrics = context.resources.displayMetrics
        val configuration = context.resources.configuration
        return JsonObject().apply {
            addProperty("manufacturer", Build.MANUFACTURER ?: "")
            addProperty("brand", Build.BRAND ?: "")
            addProperty("model", Build.MODEL ?: "")
            addProperty("device", Build.DEVICE ?: "")
            addProperty("product", Build.PRODUCT ?: "")
            addProperty("androidRelease", Build.VERSION.RELEASE ?: "")
            addProperty("sdkInt", Build.VERSION.SDK_INT)
            addProperty("screenWidth", metrics.widthPixels)
            addProperty("screenHeight", metrics.heightPixels)
            addProperty("density", metrics.density)
            addProperty("densityDpi", metrics.densityDpi)
            addProperty("orientation", if (configuration.orientation == 2) "landscape" else "portrait")
            addProperty("locale", Locale.getDefault().toLanguageTag())
            addProperty("apkVersion", BuildConfig.VERSION_NAME)
            addProperty("apkVersionCode", BuildConfig.VERSION_CODE)
            addProperty("apkVersionInfo", BuildConfig.VERSION_INFO)
            ConfigServerStatusBuilder.addTo(
                target = this,
                running = ConfigServerManager.isRunning(),
                address = ConfigServerManager.getAddress(),
                actualPort = ConfigServerManager.getPort(),
                defaultPort = ConfigServer.PORT
            )
        }
    }

    private fun buildCapabilities(accessibilityState: AccessibilityStateInspector.State): JsonObject {
        val app = ClawApplication.instance
        val accessibilityRunning = accessibilityState.boundToProcess
        return JsonObject().apply {
            addProperty("accessibilityRunning", accessibilityRunning)
            addAccessibilityStateProperties(this, accessibilityState)
            addProperty("screenshotSupported", accessibilityState.healthy && Build.VERSION.SDK_INT >= Build.VERSION_CODES.R)
            addProperty("screenInfoSupported", accessibilityState.healthy)
            addProperty("overlayPermission", Settings.canDrawOverlays(app))
            addProperty("cursorOverlayEnabled", FloatingCircleManager.isShowing())
            addProperty("cursorPreviewSupported", true)
            addProperty("llmConfigured", KVUtils.hasLlmConfig())
        }
    }

    private fun buildMemoryInfo(context: Context): JsonObject {
        val manager = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val info = ActivityManager.MemoryInfo()
        manager.getMemoryInfo(info)
        return JsonObject().apply {
            addProperty("totalBytes", info.totalMem)
            addProperty("availableBytes", info.availMem)
            addProperty("usedBytes", (info.totalMem - info.availMem).coerceAtLeast(0))
            addProperty("lowMemory", info.lowMemory)
            addProperty("thresholdBytes", info.threshold)
        }
    }

    private fun buildStorageInfo(): JsonObject {
        return JsonObject().apply {
            add("data", statPath(Environment.getDataDirectory()))
            add("external", statPath(Environment.getExternalStorageDirectory()))
        }
    }

    private fun statPath(path: File): JsonObject {
        return try {
            val stat = StatFs(path.absolutePath)
            val total = stat.blockSizeLong * stat.blockCountLong
            val available = stat.blockSizeLong * stat.availableBlocksLong
            JsonObject().apply {
                addProperty("path", path.absolutePath)
                addProperty("totalBytes", total)
                addProperty("availableBytes", available)
                addProperty("usedBytes", (total - available).coerceAtLeast(0))
            }
        } catch (e: Exception) {
            JsonObject().apply {
                addProperty("path", path.absolutePath)
                addProperty("error", e.message ?: "stat_failed")
            }
        }
    }

    private fun buildBatteryInfo(context: Context): JsonObject {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = intent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = intent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val status = intent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val plugged = intent?.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1) ?: -1
        val percent = if (level >= 0 && scale > 0) (level * 100f / scale) else null
        return JsonObject().apply {
            if (percent != null) addProperty("percent", percent)
            addProperty("status", status)
            addProperty("plugged", plugged)
            addProperty("charging", status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL)
        }
    }

    private fun buildCurrentScreenInfo(): JsonObject {
        val accessibilityState = AccessibilityStateInspector.inspect(ClawApplication.instance)
        val service = ClawAccessibilityService.getInstance()
        val tree = service?.getScreenTreeJson()
        val nodes = tree?.getAsJsonArray("nodes")
        val foregroundPackage = service?.getCurrentPackageName().orEmpty()
        val textNodeCount = nodes?.count { element ->
            val node = element.asJsonObject
            val text = node.stringOrEmpty("text")
            val desc = node.stringOrEmpty("description")
            text.isNotBlank() || desc.isNotBlank()
        } ?: 0
        val clickableNodeCount = nodes?.count { element ->
            element.asJsonObject.booleanOrFalse("clickable")
        } ?: 0
        val imageNodeCount = nodes?.count { element ->
            val className = element.asJsonObject.stringOrEmpty("className")
            className.contains("Image", ignoreCase = true)
        } ?: 0
        val treePackage = nodes
            ?.mapNotNull { it.asJsonObject.stringOrEmpty("packageName").takeIf { value -> value.isNotBlank() } }
            ?.firstOrNull()
        val resolvedPackage = listOf(foregroundPackage, treePackage)
            .firstOrNull { !it.isNullOrBlank() }
            .orEmpty()
        return JsonObject().apply {
            addProperty("accessibilityAvailable", service != null)
            addAccessibilityStateProperties(this, accessibilityState)
            addProperty("packageName", resolvedPackage)
            addProperty("foregroundPackageName", foregroundPackage)
            addProperty("nodeCount", nodes?.size() ?: 0)
            addProperty("textNodeCount", textNodeCount)
            addProperty("clickableNodeCount", clickableNodeCount)
            addProperty("imageNodeCount", imageNodeCount)
            val screen = tree?.getAsJsonObject("screen")
            if (screen != null) add("screen", screen)
        }
    }

    private fun buildVisionHints(currentScreen: JsonObject): JsonObject {
        val packageName = currentScreen.stringOrEmpty("packageName")
        val foregroundPackageName = currentScreen.stringOrEmpty("foregroundPackageName")
        val nodeCount = currentScreen.intOrZero("nodeCount")
        val textNodeCount = currentScreen.intOrZero("textNodeCount")
        val clickableNodeCount = currentScreen.intOrZero("clickableNodeCount")
        val imageNodeCount = currentScreen.intOrZero("imageNodeCount")

        val gamePackage = isGamePackage(packageName)
        val noNodes = nodeCount <= 0
        val lowNodeDensity = nodeCount in 1..4
        val imageHeavy = nodeCount >= 6 && textNodeCount <= 2 && imageNodeCount >= 4
        val recommended = noNodes || gamePackage || lowNodeDensity || imageHeavy
        val reason = when {
            noNodes -> "no_accessibility_nodes"
            gamePackage -> "game_package"
            imageHeavy -> "image_heavy_screen"
            lowNodeDensity -> "low_node_density"
            else -> "accessibility_sufficient"
        }
        val confidence = when {
            noNodes -> 0.98
            gamePackage -> 0.96
            imageHeavy -> 0.84
            lowNodeDensity -> 0.78
            else -> 0.24
        }

        return JsonObject().apply {
            addProperty("recommended", recommended)
            addProperty("mode", if (recommended) "vision" else "accessibility")
            addProperty("reason", reason)
            addProperty("confidence", confidence)
            add("signals", JsonObject().apply {
                addProperty("packageName", packageName)
                addProperty("foregroundPackageName", foregroundPackageName)
                addProperty("nodeCount", nodeCount)
                addProperty("textNodeCount", textNodeCount)
                addProperty("clickableNodeCount", clickableNodeCount)
                addProperty("imageNodeCount", imageNodeCount)
                addProperty("gamePackage", gamePackage)
            })
        }
    }

    private fun isGamePackage(packageName: String): Boolean {
        val lower = packageName.lowercase(Locale.US)
        return GAME_PACKAGES.any { candidate ->
            lower == candidate || lower.startsWith("$candidate.")
        } || lower.contains("game") || lower.contains("tencent.gcloud")
    }

    private fun JsonObject.stringOrEmpty(name: String): String {
        val value = get(name) ?: return ""
        if (value.isJsonNull) return ""
        return try {
            value.asString.orEmpty()
        } catch (_: Exception) {
            ""
        }
    }

    private fun JsonObject.booleanOrFalse(name: String): Boolean {
        val value = get(name) ?: return false
        if (value.isJsonNull) return false
        return try {
            value.asBoolean
        } catch (_: Exception) {
            false
        }
    }

    private fun JsonObject.intOrZero(name: String): Int {
        val value = get(name) ?: return 0
        if (value.isJsonNull) return 0
        return try {
            value.asInt
        } catch (_: Exception) {
            0
        }
    }

    private fun addAccessibilityStateProperties(
        target: JsonObject,
        state: AccessibilityStateInspector.State
    ) {
        target.addProperty("accessibilityRunning", state.boundToProcess)
        target.addProperty("accessibilityMasterEnabled", state.masterEnabled)
        target.addProperty("accessibilityListedInSettings", state.listedInSettings)
        target.addProperty("accessibilityEnabledInSettings", state.enabledInSettings)
        target.addProperty("accessibilityBound", state.boundToProcess)
        target.addProperty("accessibilityStale", state.staleEnabledNotBound)
        target.addProperty("accessibilityHealthy", state.healthy)
        target.addProperty("accessibilityState", state.machineState)
        target.addProperty("accessibilityLegacyState", state.legacyMachineState)
        target.addProperty("accessibilityErrorCode", state.errorCode)
        target.addProperty("accessibilityRetryable", state.retryable)
        if (state.recoveryHint.isNotBlank()) target.addProperty("accessibilityRecoveryHint", state.recoveryHint)
    }

    private fun buildPublicDirectories(): JsonArray {
        val dirs = listOf(
            Environment.DIRECTORY_DOWNLOADS,
            Environment.DIRECTORY_DOCUMENTS,
            Environment.DIRECTORY_DCIM,
            Environment.DIRECTORY_PICTURES,
            Environment.DIRECTORY_MOVIES
        )
        val result = JsonArray()
        dirs.forEach { type ->
            val dir = Environment.getExternalStoragePublicDirectory(type)
            result.add(JsonObject().apply {
                addProperty("type", type)
                addProperty("path", dir.absolutePath)
                addProperty("exists", dir.exists())
                addProperty("canRead", dir.canRead())
                addProperty("canWrite", dir.canWrite())
            })
        }
        return result
    }

    private fun buildLaunchableApps(context: Context, limit: Int): JsonArray {
        val pm = context.packageManager
        val intent = Intent(Intent.ACTION_MAIN, null).apply {
            addCategory(Intent.CATEGORY_LAUNCHER)
        }
        val apps = pm.queryIntentActivities(intent, 0)
            .map { info ->
                val label = info.loadLabel(pm)?.toString().orEmpty()
                val packageName = info.activityInfo?.packageName.orEmpty()
                val activityName = info.activityInfo?.name.orEmpty()
                Triple(label, packageName, activityName)
            }
            .filter { it.second.isNotBlank() }
            .distinctBy { it.second + "/" + it.third }
            .sortedWith(compareBy(
                { browserPriority(it.first, it.second) },
                { it.first.lowercase(Locale.getDefault()) },
                { it.second }
            ))
            .take(limit)

        val result = JsonArray()
        apps.forEach { (label, packageName, activityName) ->
            result.add(JsonObject().apply {
                addProperty("label", label)
                addProperty("packageName", packageName)
                addProperty("activityName", activityName)
                addProperty("launchable", true)
            })
        }
        return result
    }

    private fun browserPriority(label: String, packageName: String): Int {
        val lowerLabel = label.lowercase(Locale.US).trim()
        val lowerPackage = packageName.lowercase(Locale.US).trim()
        return when {
            lowerPackage == "mark.via" || lowerPackage == "mark.via.gp" -> 0
            lowerPackage.startsWith("mark.via") -> 0
            lowerLabel == "via" || lowerLabel.contains("via browser") -> 0
            else -> 1
        }
    }

    private fun jsonElementResponse(
        status: NanoHTTPD.Response.IStatus,
        success: Boolean,
        data: JsonElement?,
        error: String?
    ): NanoHTTPD.Response {
        val json = JsonObject().apply {
            addProperty("success", success)
            if (data != null) add("data", data)
            if (error != null) addProperty("error", error)
        }
        val response = NanoHTTPD.newFixedLengthResponse(status, MIME_JSON_UTF8, json.toString())
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.addHeader("Access-Control-Allow-Headers", "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN")
        return response
    }

    private fun getIntParam(session: NanoHTTPD.IHTTPSession, name: String): Int? {
        return session.parameters[name]?.firstOrNull()?.toIntOrNull()
    }

    private fun getBooleanParam(session: NanoHTTPD.IHTTPSession, name: String): Boolean? {
        return session.parameters[name]?.firstOrNull()?.lowercase(Locale.US)?.let {
            when (it) {
                "true", "1", "yes", "on" -> true
                "false", "0", "no", "off" -> false
                else -> null
            }
        }
    }
}
