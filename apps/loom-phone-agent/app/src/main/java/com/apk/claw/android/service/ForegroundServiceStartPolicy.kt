package com.apk.claw.android.service

import android.os.Build

object ForegroundServiceStartPolicy {
    fun shouldAttemptStart(
        sdkInt: Int,
        notificationPermissionGranted: Boolean
    ): Boolean {
        return true
    }

    fun shouldRestartAfterServiceDestroyed(explicitUserStop: Boolean): Boolean {
        return !explicitUserStop
    }

    fun shouldStopConfigServerOnDestroy(
        explicitUserStop: Boolean,
        configServerEnabled: Boolean
    ): Boolean {
        return explicitUserStop || !configServerEnabled
    }

    fun shouldUseForegroundServicePendingIntent(sdkInt: Int): Boolean {
        return sdkInt >= Build.VERSION_CODES.O
    }
}
