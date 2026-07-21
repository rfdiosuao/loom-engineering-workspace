package com.apk.claw.android.service

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ForegroundServiceStartPolicyTest {
    @Test
    fun notification_permission_denial_must_not_block_foreground_service_start() {
        assertTrue(
            ForegroundServiceStartPolicy.shouldAttemptStart(
                sdkInt = 33,
                notificationPermissionGranted = false
            )
        )
    }

    @Test
    fun explicit_user_stop_is_the_only_restart_suppression() {
        assertTrue(ForegroundServiceStartPolicy.shouldRestartAfterServiceDestroyed(explicitUserStop = false))
        assertFalse(ForegroundServiceStartPolicy.shouldRestartAfterServiceDestroyed(explicitUserStop = true))
    }

    @Test
    fun system_destroy_must_not_stop_enabled_config_server() {
        assertFalse(
            ForegroundServiceStartPolicy.shouldStopConfigServerOnDestroy(
                explicitUserStop = false,
                configServerEnabled = true
            )
        )
    }

    @Test
    fun explicit_stop_or_disabled_config_server_should_stop_config_server_on_destroy() {
        assertTrue(
            ForegroundServiceStartPolicy.shouldStopConfigServerOnDestroy(
                explicitUserStop = true,
                configServerEnabled = true
            )
        )
        assertTrue(
            ForegroundServiceStartPolicy.shouldStopConfigServerOnDestroy(
                explicitUserStop = false,
                configServerEnabled = false
            )
        )
    }

    @Test
    fun android_oreo_and_newer_restart_should_use_foreground_service_pending_intent() {
        assertFalse(ForegroundServiceStartPolicy.shouldUseForegroundServicePendingIntent(sdkInt = 25))
        assertTrue(ForegroundServiceStartPolicy.shouldUseForegroundServicePendingIntent(sdkInt = 26))
        assertTrue(ForegroundServiceStartPolicy.shouldUseForegroundServicePendingIntent(sdkInt = 35))
    }
}
