package com.apk.claw.android.rpa

import android.content.Context
import android.os.Build
import com.apk.claw.android.utils.XLog
import java.io.File

object HybridRuntimeInstaller {
    private const val TAG = "HybridRuntimeInstaller"

    fun install(context: Context): Boolean = installSafely {
        install(filesDirectory = context.filesDir, apiLevel = Build.VERSION.SDK_INT)
    }

    internal fun installSafely(block: () -> Unit): Boolean = try {
        block()
        true
    } catch (error: Exception) {
        RpaWorkflowRunner.installHybridEngine(null)
        runCatching { XLog.e(TAG, "Hybrid runtime unavailable: ${error.javaClass.simpleName}") }
        false
    }

    internal fun install(
        filesDirectory: File,
        apiLevel: Int,
        serviceProvider: ProductionPlatformServiceProvider = CurrentClawPlatformServiceProvider,
        visualAssetReader: VisualAssetReader? = null,
        visualDecoder: VisualAssetDecoder = AndroidVisualAssetDecoder,
        clock: () -> Long = System::currentTimeMillis
    ) {
        RpaWorkflowRunner.installHybridEngine(
            ProductionHybridWorkflowExecutor(
                filesDirectory = filesDirectory,
                apiLevel = apiLevel,
                serviceProvider = serviceProvider,
                visualAssetReader = visualAssetReader,
                visualDecoder = visualDecoder,
                clock = clock
            )
        )
    }
}
