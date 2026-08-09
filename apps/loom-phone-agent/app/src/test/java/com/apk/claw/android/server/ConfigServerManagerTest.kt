package com.apk.claw.android.server

import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
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

        assertFalse(
            "A network address change must preserve a healthy loopback server",
            source.contains("restarting ConfigServer")
        )
        assertTrue(source.contains("lifecycle.onNetworkAvailable(generation)"))
        assertTrue(source.contains("override fun onLinkPropertiesChanged"))
        assertTrue(source.contains("ADDRESS_STABILITY_DELAY_MS"))
    }

    @Test
    fun user_disable_persists_false_before_unregistering_and_stopping() {
        val effects = FakeEffects()
        val coordinator = ConfigServerLifecycleCoordinator(effects)
        coordinator.userEnable()
        effects.events.clear()

        coordinator.userDisable()

        awaitPhase(coordinator, ConfigServerLifecyclePhase.STOPPED)
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
        awaitPhase(coordinator, ConfigServerLifecyclePhase.STOPPED)
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

        awaitPhase(coordinator, ConfigServerLifecyclePhase.STOPPED)
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

        awaitPhase(coordinator, ConfigServerLifecyclePhase.STOPPED)
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

        awaitPhase(coordinator, ConfigServerLifecyclePhase.STOPPED)
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
            awaitPhase(coordinator, ConfigServerLifecyclePhase.STOPPED)
        }

        assertFalse(effects.enabled)
        assertFalse(effects.alive)
        assertEquals(ConfigServerLifecyclePhase.STOPPED, coordinator.state.phase)
        assertEquals(50, effects.startCalls)
        assertEquals(50, effects.stopCalls)
    }

    @Test
    fun blocked_stop_does_not_hold_the_lifecycle_monitor_or_overwrite_a_new_generation() {
        val effects = BlockingStopEffects()
        val coordinator = ConfigServerLifecycleCoordinator(effects)
        coordinator.userEnable()
        val disableReturned = CountDownLatch(1)
        val enableReturned = CountDownLatch(1)

        val disabling = thread {
            coordinator.userDisable()
            disableReturned.countDown()
        }
        assertTrue(effects.stopEntered.await(1, TimeUnit.SECONDS))
        val enabling = thread {
            coordinator.userEnable()
            enableReturned.countDown()
        }

        assertTrue("Disable must not wait for a blocking server stop", disableReturned.await(250, TimeUnit.MILLISECONDS))
        assertTrue("Enable must be able to replace a stopping generation", enableReturned.await(250, TimeUnit.MILLISECONDS))

        effects.releaseStop.countDown()
        disabling.join(1000)
        enabling.join(1000)
        assertEquals(ConfigServerLifecyclePhase.READY, coordinator.state.phase)
        assertTrue(coordinator.state.generation > 1)
    }

    @Test
    fun adapter_stop_contract_is_bounded_and_reports_timeout_instead_of_false_stopped() {
        val source = File("src/main/java/com/apk/claw/android/server/ConfigServerManager.kt").readText()

        assertTrue(source.contains("STOP_TIMEOUT_MS = 750L"))
        assertTrue(source.contains("worker.join(STOP_TIMEOUT_MS)"))
        assertTrue(source.contains("ConfigServerStopOutcome.TIMED_OUT"))
    }

    @Test
    fun settings_toggle_uses_io_and_immediately_exposes_transitional_state() {
        val source = File("src/main/java/com/apk/claw/android/ui/settings/SettingsViewModel.kt").readText()

        assertTrue(source.contains("withContext(Dispatchers.IO)"))
        assertTrue(source.contains("ConfigServerLifecyclePhase.STOPPING"))
        assertTrue(source.contains("ConfigServerLifecyclePhase.STARTING"))
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
        var serverGeneration: Long? = null
        val publishedPhases = mutableListOf<ConfigServerLifecyclePhase>()

        override fun isDesiredEnabled(): Boolean = enabled

        override fun persistEnabled(enabled: Boolean) {
            this.enabled = enabled
            events += "persist:$enabled"
        }

        override fun currentListeningPort(generation: Long?): Int? =
            if (alive && (generation == null || generation == serverGeneration)) nextStartPort else null

        override fun startServer(generation: Long): Int? {
            startCalls += 1
            events += "start"
            alive = nextStartPort != null
            serverGeneration = generation.takeIf { alive }
            return nextStartPort
        }

        override fun stopServer(upToGeneration: Long): ConfigServerStopOutcome {
            stopCalls += 1
            events += "stop"
            if ((serverGeneration ?: Long.MAX_VALUE) <= upToGeneration) {
                alive = false
                serverGeneration = null
            }
            return ConfigServerStopOutcome.STOPPED
        }

        override fun registerNetworkCallback(generation: Long) {
            registerCalls += 1
            callbackGeneration = generation
            events += "register:$generation"
        }

        override fun unregisterNetworkCallback(upToGeneration: Long) {
            if ((callbackGeneration ?: Long.MAX_VALUE) <= upToGeneration) callbackGeneration = null
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

    private class BlockingStopEffects : ConfigServerLifecycleEffects {
        val stopEntered = CountDownLatch(1)
        val releaseStop = CountDownLatch(1)
        private var enabled = false
        private var alive = false
        private var serverGeneration: Long? = null

        override fun isDesiredEnabled(): Boolean = enabled

        override fun persistEnabled(enabled: Boolean) {
            this.enabled = enabled
        }

        override fun currentListeningPort(generation: Long?): Int? =
            if (alive && (generation == null || generation == serverGeneration)) 9527 else null

        override fun startServer(generation: Long): Int? {
            alive = true
            serverGeneration = generation
            return 9527
        }

        override fun stopServer(upToGeneration: Long): ConfigServerStopOutcome {
            stopEntered.countDown()
            releaseStop.await(1, TimeUnit.SECONDS)
            if ((serverGeneration ?: Long.MAX_VALUE) <= upToGeneration) {
                alive = false
                serverGeneration = null
            }
            return ConfigServerStopOutcome.STOPPED
        }

        override fun registerNetworkCallback(generation: Long) = Unit

        override fun unregisterNetworkCallback(upToGeneration: Long) = Unit

        override fun onAddressChanged() = Unit

        override fun onStateChanged(
            previous: ConfigServerState,
            current: ConfigServerState,
            reason: String
        ) = Unit
    }

    private fun awaitPhase(
        coordinator: ConfigServerLifecycleCoordinator,
        expected: ConfigServerLifecyclePhase,
        timeoutMs: Long = 1000
    ) {
        val deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMs)
        while (coordinator.state.phase != expected && System.nanoTime() < deadline) {
            Thread.yield()
        }
        assertEquals(expected, coordinator.state.phase)
    }
}
