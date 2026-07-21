package com.apk.claw.android.server

import android.content.Context
import com.apk.claw.android.utils.CrashReportStore
import com.apk.claw.android.utils.XLog
import com.google.gson.JsonObject
import fi.iki.elonen.NanoHTTPD
import java.io.File

object CrashLogApiController {
    private const val TAG = "CrashLogApiController"
    private const val MIME_JSON_UTF8 = "application/json; charset=utf-8"

    fun handleLatest(context: Context, session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError
        val latest = CrashReportStore.latestCrash(context)
        val data = JsonObject().apply {
            addProperty("available", latest != null)
            addProperty("directory", File(context.cacheDir, "crashes").absolutePath)
            if (latest != null) {
                addProperty("path", latest.absolutePath)
                addProperty("filename", latest.name)
                addProperty("size", latest.length())
                addProperty("content", latest.readText(Charsets.UTF_8).take(24_000))
            }
        }
        return LumiSecurityController.jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    fun handleExport(context: Context, session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError
        return try {
            val bundle = CrashReportStore.exportBundle(context)
            val latest = CrashReportStore.latestCrash(context)
            val data = JsonObject().apply {
                addProperty("path", bundle.absolutePath)
                addProperty("directory", bundle.parentFile?.absolutePath ?: "")
                addProperty("filename", bundle.name)
                addProperty("size", bundle.length())
                addProperty("available", true)
                addProperty("latestCrashPath", latest?.absolutePath ?: "")
                addProperty("latestCrashName", latest?.name ?: "")
            }
            LumiSecurityController.jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
        } catch (e: Exception) {
            XLog.e(TAG, "Failed to export crash logs", e)
            LumiSecurityController.jsonElementResponse(NanoHTTPD.Response.Status.INTERNAL_ERROR, false, null, e.message ?: "Failed to export crash logs")
        }
    }

    fun recordThrowable(context: Context, scope: String, throwable: Throwable) {
        try {
            CrashReportStore.recordThrowable(context, scope, Thread.currentThread().name, throwable)
        } catch (e: Exception) {
            XLog.e(TAG, "Failed to record throwable", e)
        }
    }
}
