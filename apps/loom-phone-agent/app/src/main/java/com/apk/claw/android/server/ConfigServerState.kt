package com.apk.claw.android.server

enum class ConfigServerLifecyclePhase {
    STOPPED,
    STARTING,
    READY,
    STOPPING,
    ERROR
}

data class ConfigServerState(
    val phase: ConfigServerLifecyclePhase = ConfigServerLifecyclePhase.STOPPED,
    val generation: Long = 0,
    val port: Int? = null,
    val error: String? = null
)

/**
 * Android-free boundary for the config server lifecycle. All callers enter through a synchronized
 * transition, while the adapter owns the bounded server start/stop operations.
 */
interface ConfigServerLifecycleEffects {
    fun isDesiredEnabled(): Boolean
    fun persistEnabled(enabled: Boolean)
    fun currentListeningPort(): Int?
    fun startServer(): Int?
    fun stopServer()
    fun registerNetworkCallback(generation: Long)
    fun unregisterNetworkCallback()
    fun onAddressChanged()
    fun onStateChanged(previous: ConfigServerState, current: ConfigServerState, reason: String)
}

class ConfigServerLifecycleCoordinator(
    private val effects: ConfigServerLifecycleEffects
) {
    @Volatile
    var state: ConfigServerState = ConfigServerState()
        private set

    @Synchronized
    fun userEnable(): Boolean {
        effects.persistEnabled(true)
        return startInternal("user_enable")
    }

    @Synchronized
    fun userDisable() {
        // Persisting first makes every late callback observe the user's final intent.
        effects.persistEnabled(false)
        stopInternal("user_disable")
    }

    @Synchronized
    fun runtimeStart(): Boolean = startInternal("runtime_start", requireDesiredEnabled = false)

    @Synchronized
    fun startIfDesired(): Boolean = startInternal("auto_start")

    @Synchronized
    fun runtimeStop() {
        stopInternal("runtime_stop")
    }

    @Synchronized
    fun onNetworkAvailable(callbackGeneration: Long) {
        if (callbackGeneration != state.generation) return
        if (!effects.isDesiredEnabled()) return

        if (effects.currentListeningPort() != null) {
            effects.onAddressChanged()
            return
        }
        startInternal("network_recovery")
    }

    @Synchronized
    fun onNetworkLost(callbackGeneration: Long) {
        if (callbackGeneration != state.generation) return
        // USB forwarding uses loopback, so an address loss is only an address-state update.
        effects.onAddressChanged()
    }

    private fun startInternal(reason: String, requireDesiredEnabled: Boolean = true): Boolean {
        if (requireDesiredEnabled && !effects.isDesiredEnabled()) return false

        val runningPort = effects.currentListeningPort()
        if (state.phase == ConfigServerLifecyclePhase.READY && runningPort != null) return true
        if (state.phase == ConfigServerLifecyclePhase.STARTING) return false

        val generation = state.generation + 1
        publish(ConfigServerState(ConfigServerLifecyclePhase.STARTING, generation), reason)
        effects.unregisterNetworkCallback()

        val port = try {
            effects.startServer()
        } catch (_: Exception) {
            null
        }
        if (port != null && port > 0 && effects.currentListeningPort() == port) {
            publish(ConfigServerState(ConfigServerLifecyclePhase.READY, generation, port = port), reason)
            effects.registerNetworkCallback(generation)
            return true
        }

        effects.stopServer()
        publish(
            ConfigServerState(
                phase = ConfigServerLifecyclePhase.ERROR,
                generation = generation,
                error = "Config server could not listen on an available port. Check the connection service and try again."
            ),
            reason
        )
        return false
    }

    private fun stopInternal(reason: String) {
        if (state.phase == ConfigServerLifecyclePhase.STOPPED) return

        val generation = state.generation + 1
        publish(ConfigServerState(ConfigServerLifecyclePhase.STOPPING, generation), reason)
        effects.unregisterNetworkCallback()
        try {
            effects.stopServer()
        } catch (_: Exception) {
            // The final state is still stopped: no callback may keep the old lifecycle alive.
        }
        publish(ConfigServerState(ConfigServerLifecyclePhase.STOPPED, generation), reason)
    }

    private fun publish(next: ConfigServerState, reason: String) {
        val previous = state
        state = next
        effects.onStateChanged(previous, next, reason)
    }
}
