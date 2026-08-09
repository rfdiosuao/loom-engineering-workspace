package com.apk.claw.android.privilege

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PrivilegeBackendSelectorTest {
    @Test
    fun `missing stopped and unauthorized Shizuku always preserve standard mode`() {
        val missing = PrivilegeBackendSelector.select(PrivilegeProbe(shizukuInstalled = false))
        val stopped = PrivilegeBackendSelector.select(
            PrivilegeProbe(shizukuInstalled = true, userEnabled = true, binderAlive = false)
        )
        val unauthorized = PrivilegeBackendSelector.select(
            PrivilegeProbe(
                shizukuInstalled = true,
                userEnabled = true,
                binderAlive = true,
                permissionGranted = false,
                identityUid = 2000
            )
        )

        assertEquals(PrivilegeBackendKind.STANDARD, missing.backend)
        assertEquals("shizuku_not_installed", missing.reasonCode)
        assertEquals(PrivilegeBackendKind.STANDARD, stopped.backend)
        assertEquals("shizuku_service_stopped", stopped.reasonCode)
        assertEquals(PrivilegeBackendKind.STANDARD, unauthorized.backend)
        assertEquals("shizuku_permission_required", unauthorized.reasonCode)
        assertTrue(listOf(missing, stopped, unauthorized).all { it.standardCapabilitiesAvailable })
    }

    @Test
    fun `authorized adb identity selects Shizuku and binder death falls back immediately`() {
        val ready = PrivilegeBackendSelector.select(
            PrivilegeProbe(
                shizukuInstalled = true,
                userEnabled = true,
                binderAlive = true,
                permissionGranted = true,
                identityUid = 2000
            )
        )
        val dead = PrivilegeBackendSelector.select(
            PrivilegeProbe(
                shizukuInstalled = true,
                userEnabled = true,
                binderAlive = false,
                permissionGranted = true,
                identityUid = 2000
            )
        )

        assertEquals(PrivilegeBackendKind.SHIZUKU, ready.backend)
        assertTrue(ready.enhancedActionsAvailable)
        assertEquals(PrivilegeBackendKind.STANDARD, dead.backend)
        assertFalse(dead.enhancedActionsAvailable)
        assertEquals("shizuku_binder_dead", dead.reasonCode)
    }

    @Test
    fun `reboot revocation and local disable do not trigger permission loops`() {
        val rebooted = PrivilegeBackendSelector.select(
            PrivilegeProbe(
                shizukuInstalled = true,
                userEnabled = true,
                binderAlive = true,
                permissionGranted = false,
                permissionPermanentlyDenied = true,
                identityUid = 2000
            )
        )
        val disabled = PrivilegeBackendSelector.select(
            PrivilegeProbe(
                shizukuInstalled = true,
                userEnabled = false,
                binderAlive = true,
                permissionGranted = true,
                identityUid = 2000
            )
        )

        assertFalse(rebooted.shouldRequestPermission)
        assertEquals("shizuku_permission_denied", rebooted.reasonCode)
        assertFalse(disabled.shouldRequestPermission)
        assertEquals("enhanced_mode_disabled", disabled.reasonCode)
    }

    @Test
    fun `root or Sui identity is disabled unless a separate local gate opts in`() {
        val defaultSelection = PrivilegeBackendSelector.select(
            PrivilegeProbe(
                shizukuInstalled = true,
                userEnabled = true,
                binderAlive = true,
                permissionGranted = true,
                identityUid = 0,
                allowSui = false
            )
        )
        val optedIn = PrivilegeBackendSelector.select(
            PrivilegeProbe(
                shizukuInstalled = true,
                userEnabled = true,
                binderAlive = true,
                permissionGranted = true,
                identityUid = 0,
                allowSui = true
            )
        )

        assertEquals(PrivilegeBackendKind.STANDARD, defaultSelection.backend)
        assertEquals("sui_root_disabled", defaultSelection.reasonCode)
        assertEquals(PrivilegeBackendKind.SUI, optedIn.backend)
    }
}
