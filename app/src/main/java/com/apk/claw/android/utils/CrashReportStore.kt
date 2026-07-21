package com.apk.claw.android.utils

import android.content.Context
import android.os.Build
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object CrashReportStore {
    private const val TAG = "CrashReportStore"
    private const val CRASH_DIR_NAME = "crashes"
    private const val EXPORT_DIR_NAME = "crash_exports"
    private const val MAX_CRASH_FILES = 12

    @Volatile
    private var installed = false

    @Volatile
    private var previousHandler: Thread.UncaughtExceptionHandler? = null

    fun install(context: Context) {
        if (installed) return
        synchronized(this) {
            if (installed) return
            previousHandler = Thread.getDefaultUncaughtExceptionHandler()
            Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
                try {
                    recordThrowable(context, "uncaught", thread.name, throwable)
                } catch (recordError: Exception) {
                    XLog.e(TAG, "Failed to record uncaught crash", recordError)
                }
                previousHandler?.uncaughtException(thread, throwable)
            }
            installed = true
        }
    }

    fun recordThrowable(context: Context, scope: String, threadName: String, throwable: Throwable): File {
        val crashDir = crashDir(context)
        if (!crashDir.exists()) {
            crashDir.mkdirs()
        }
        val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(Date())
        val file = File(crashDir, "crash_${timestamp}.txt")
        val writer = StringWriter()
        throwable.printStackTrace(PrintWriter(writer))
        val body = buildString {
            appendLine("timestamp=$timestamp")
            appendLine("scope=$scope")
            appendLine("thread=$threadName")
            appendLine("package=${context.packageName}")
            appendLine("version=${BuildConfigVersionHelper.versionName(context)}")
            appendLine("versionCode=${BuildConfigVersionHelper.versionCode(context)}")
            appendLine("device=${Build.BRAND} ${Build.MODEL}")
            appendLine("sdk=${Build.VERSION.SDK_INT}")
            appendLine()
            appendLine(writer.toString())
        }
        file.writeText(body, Charsets.UTF_8)
        pruneOldFiles(crashDir)
        XLog.e(TAG, "Crash report written: ${file.absolutePath}")
        return file
    }

    fun latestCrash(context: Context): File? {
        return crashDir(context)
            .listFiles()
            ?.filter { it.isFile && it.name.startsWith("crash_") && it.extension == "txt" }
            ?.sortedByDescending { it.lastModified() }
            ?.firstOrNull()
    }

    fun exportBundle(context: Context): File {
        val exportDir = File(context.cacheDir, EXPORT_DIR_NAME).apply { mkdirs() }
        val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(Date())
        val bundle = File(exportDir, "apkclaw-crash-report-$timestamp.zip")
        val crashDir = crashDir(context)
        val httpLogDir = File(context.cacheDir, "http_logs")
        val metaFile = File.createTempFile("apkclaw_crash_meta_", ".txt", exportDir)
        try {
            metaFile.writeText(buildString {
                appendLine("package=${context.packageName}")
                appendLine("version=${BuildConfigVersionHelper.versionName(context)}")
                appendLine("versionCode=${BuildConfigVersionHelper.versionCode(context)}")
                appendLine("device=${Build.BRAND} ${Build.MODEL}")
                appendLine("sdk=${Build.VERSION.SDK_INT}")
                appendLine("crashDir=${crashDir.absolutePath}")
                appendLine("httpLogDir=${httpLogDir.absolutePath}")
            }, Charsets.UTF_8)

            java.util.zip.ZipOutputStream(bundle.outputStream().buffered()).use { zip ->
                if (crashDir.exists()) {
                    crashDir.listFiles()?.forEach { file ->
                        if (file.isFile) {
                            zip.putNextEntry(java.util.zip.ZipEntry("crashes/${file.name}"))
                            file.inputStream().use { input -> input.copyTo(zip) }
                            zip.closeEntry()
                        }
                    }
                }
                if (httpLogDir.exists()) {
                    httpLogDir.listFiles()?.forEach { file ->
                        if (file.isFile) {
                            zip.putNextEntry(java.util.zip.ZipEntry("http_logs/${file.name}"))
                            file.inputStream().use { input -> input.copyTo(zip) }
                            zip.closeEntry()
                        }
                    }
                }
                if (metaFile.exists()) {
                    zip.putNextEntry(java.util.zip.ZipEntry("meta.txt"))
                    metaFile.inputStream().use { input -> input.copyTo(zip) }
                    zip.closeEntry()
                }
            }
        } finally {
            try {
                metaFile.delete()
            } catch (_: Exception) {
            }
        }
        return bundle
    }

    private fun crashDir(context: Context): File {
        return File(context.cacheDir, CRASH_DIR_NAME)
    }

    private fun pruneOldFiles(dir: File) {
        val files = dir.listFiles()
            ?.filter { it.isFile }
            ?.sortedByDescending { it.lastModified() }
            ?: return
        files.drop(MAX_CRASH_FILES).forEach {
            try {
                it.delete()
            } catch (_: Exception) {
            }
        }
    }
}

private object BuildConfigVersionHelper {
    fun versionName(context: Context): String {
        return try {
            val info = context.packageManager.getPackageInfo(context.packageName, 0)
            @Suppress("DEPRECATION")
            info.versionName ?: ""
        } catch (_: Exception) {
            ""
        }
    }

    fun versionCode(context: Context): Long {
        return try {
            val info = context.packageManager.getPackageInfo(context.packageName, 0)
            if (android.os.Build.VERSION.SDK_INT >= 28) {
                info.longVersionCode
            } else {
                @Suppress("DEPRECATION")
                info.versionCode.toLong()
            }
        } catch (_: Exception) {
            -1L
        }
    }
}
