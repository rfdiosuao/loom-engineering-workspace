package com.apk.claw.android.server

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ConfigServerManagerTest {
    @Test
    fun user_disable_persists_preference_before_stopping_the_server() {
        val source = File("src/main/java/com/apk/claw/android/ui/settings/SettingsViewModel.kt").readText()
        val toggle = source.substringAfter("fun toggleConfigServer")
            .substringBefore("private fun getLanConfigTrailingText")

        assertTrue(
            "Settings must enter the user-intent path, which persists before callback teardown",
            toggle.contains("ConfigServerManager.disable()")
        )
        assertFalse(toggle.contains("ConfigServerManager.stop()"))
    }

    @Test
    fun healthy_network_callback_does_not_describe_or_perform_a_restart() {
        val source = File("src/main/java/com/apk/claw/android/server/ConfigServerManager.kt").readText()
        val available = source.substringAfter("override fun onAvailable(network: Network)")
            .substringBefore("        }\n\n        cm.registerNetworkCallback")

        assertFalse(
            "A network address change must preserve a healthy loopback server",
            available.contains("restarting ConfigServer")
        )
    }

    @Test
    fun user_disable_persists_false_before_unregistering_and_stopping() {
        val effects = FakeEffects()
        val coordinator = ConfigServerLifecycleCoordinator(effects)
        coordinator.userEnable()
        effects.events.clear()

        coordinator.userDisable()

        assertEquals(ConfigServerLifecyclePhase.STOPPED, coordinator.state.phase)
        assertTrue(effects.events.indexOf("persist:false") < effects.events.indexOf("unregister"))
        assertTrue(effects.events.indexOf("persist:false") < effects.events.indexOf("stop"))
    }

    @Test
    fun stale_available_callback_after_disable_cannot_restart_server() {
        val effects = FakeEffects()
        val coordinator = ConfigServerLifecycleCoordinator(effects)
        coordinator.userEnable()
        val staleGeneration = effects.callbackGeneration!!
        coordinator.userDisable()
        val startsBeforeStaleCallback = effects.startCalls

        coordinator.onNetworkAvailable(staleGeneration)

        assertEquals(startsBeforeStaleCallback, effects.startCalls)
        assertEquals(ConfigServerLifecyclePhase.STOPPED, coordinator.state.phase)
    }

    @Test
    fun repeated_start_is_idempotent_without_second_server_or_callback() {
        val effects = FakeEffects()
        val coordinator = ConfigServerLifecycleCoordinator(effects)

        assertTrue(coordinator.userEnable())
        assertTrue(coordinator.userEnable())

        assertEquals(1, effects.startCalls)
        assertEquals(1, effects.registerCalls)
        assertEquals(ConfigServerLifecyclePhase.READY, coordinator.state.phase)
    }

    @Test
    fun repeated_stop_is_idempotent_and_ends_stopped() {
        val effects = FakeEffects()
        val coordinator = ConfigServerLifecycleCoordinator(effects)
        coordinator.userEnable()

        coordinator.runtimeStop()
        coordinator.runtimeStop()

        assertEquals(1, effects.stopCalls)
        assertEquals(ConfigServerLifecyclePhase.STOPPED, coordinator.state.phase)
    }

    @Test
    fun stop_publishes_stopping_before_stopped() {
        val effects = FakeEffects()
        val coordinator = ConfigServerLifecycleCoordinator(effects)
        coordinator.userEnable()
        effects.publishedPhases.clear()

        coordinator.userDisable()

        assertEquals(
            listOf(ConfigServerLifecyclePhase.STOPPING, ConfigServerLifecyclePhase.STOPPED),
            effects.publishedPhases
        )
    }

    @Test
    fun runtime_stop_keeps_the_user_enabled_preference() {
        val effects = FakeEffects()
        val coordinator = ConfigServerLifecycleCoordinator(effects)
        coordinator.userEnable()

        coordinator.runtimeStop()

        assertTrue(effects.enabled)
        assertEquals(ConfigServerLifecyclePhase.STOPPED, coordinator.state.phase)
    }

    @Test
    fun healthy_network_available_updates_address_without_restart() {
        val effects = FakeEffects()
        val coordinator = ConfigServerLifecycleCoordinator(effects)
        coordinator.userEnable()
        val generation = effects.callbackGeneration!!

        coordinator.onNetworkAvailable(generation)

        assertEquals(1, effects.startCalls)
        assertEquals(1, effects.addressUpdates)
    }

    @Test
    fun dead_desired_enabled_server_recovers_once_and_stale_generation_cannot_recover() {
        val effects = FakeEffects()
        val coordinator = ConfigServerLifecycleCoordinator(effects)
        coordinator.userEnable()
        val originalGeneration = effects.callbackGeneration!!
        effects.alive = false

        coordinator.onNetworkAvailable(originalGeneration)
        val recoveredGeneration = effects.callbackGeneration!!
        coordinator.onNetworkAvailable(originalGeneration)

        assertTrue(recoveredGeneration > originalGeneration)
        assertEquals(2, effects.startCalls)
        assertEquals(ConfigServerLifecyclePhase.READY, coordinator.state.phase)
    }

    @Test
    fun start_failure_publishes_error_without_ready() {
        val effects = FakeEffects(nextStartPort = null)
        val coordinator = ConfigServerLifecycleCoordinator(effects)

        assertFalse(coordinator.userEnable())

        assertEquals(ConfigServerLifecyclePhase.ERROR, coordinator.state.phase)
        assertNull(coordinator.state.port)
        assertTrue(coordinator.state.error!!.contains("could not listen"))
        assertEquals(0, effects.registerCalls)
    }

    @Test
    fun fifty_sequential_toggles_end_in_a_single_deterministic_stopped_state() {
        val effects = FakeEffects()
        val coordinator = ConfigServerLifecycleCoordinator(effects)

        repeat(50) {
            coordinator.userEnable()
            coordinator.userDisable()
        }

        assertFalse(effects.enabled)
        assertFalse(effects.alive)
        assertEquals(ConfigServerLifecyclePhase.STOPPED, coordinator.state.phase)
        assertEquals(50, effects.startCalls)
        assertEquals(50, effects.stopCalls)
    }

    private class FakeEffects(
        private val nextStartPort: Int? = 9527
    ) : ConfigServerLifecycleEffects {
        val events = mutableListOf<String>()
        var enabled = false
        var alive = false
        var startCalls = 0
        var stopCalls = 0
        var registerCalls = 0
        var addressUpdates = 0
        var callbackGeneration: Long? = null
        val publishedPhases = mutableListOf<ConfigServerLifecyclePhase>()

        override fun isDesiredEnabled(): Boolean = enabled

        override fun persistEnabled(enabled: Boolean) {
            this.enabled = enabled
            events += "persist:$enabled"
        }

        override fun currentListeningPort(): Int? = if (alive) nextStartPort else null

        override fun startServer(): Int? {
            startCalls += 1
            events += "start"
            alive = nextStartPort != null
            return nextStartPort
        }

        override fun stopServer() {
            stopCalls += 1
            events += "stop"
            alive = false
        }

        override fun registerNetworkCallback(generation: Long) {
            registerCalls += 1
            callbackGeneration = generation
            events += "register:$generation"
        }

        override fun unregisterNetworkCallback() {
            callbackGeneration = null
            events += "unregister"
        }

        override fun onAddressChanged() {
            addressUpdates += 1
        }

        override fun onStateChanged(
            previous: ConfigServerState,
            current: ConfigServerState,
            reason: String
        ) {
            events += "state:${previous.phase}->${current.phase}:$reason"
            publishedPhases += current.phase
        }
    }
}
