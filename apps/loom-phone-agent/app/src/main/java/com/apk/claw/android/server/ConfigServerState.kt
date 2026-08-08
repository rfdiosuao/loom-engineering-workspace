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

enum class ConfigServerStopOutcome {
    STOPPED,
    TIMED_OUT,
    FAILED
}

/**
 * Android-free boundary for the config server lifecycle. The coordinator only protects intent,
 * state and generation with its monitor. Potentially blocking adapter work always runs outside it.
 */
interface ConfigServerLifecycleEffects {
    fun isDesiredEnabled(): Boolean
    fun persistEnabled(enabled: Boolean)
    fun currentListeningPort(generation: Long? = null): Int?
    fun startServer(generation: Long): Int?
    fun stopServer(upToGeneration: Long): ConfigServerStopOutcome
    fun registerNetworkCallback(generation: Long)
    fun unregisterNetworkCallback(upToGeneration: Long)
    fun onAddressChanged()
    fun onStateChanged(previous: ConfigServerState, current: ConfigServerState, reason: String)
}

class ConfigServerLifecycleCoordinator(
    private val effects: ConfigServerLifecycleEffects,
    private val launchStopWork: ((() -> Unit) -> Unit) = { work ->
        Thread(work, "lumi-config-server-stop").apply {
            isDaemon = true
            start()
        }
    }
) {
    private data class Transition(
        val previous: ConfigServerState,
        val current: ConfigServerState,
        val reason: String
    )

    private val stateLock = Any()

    @Volatile
    var state: ConfigServerState = ConfigServerState()
        private set

    fun userEnable(): Boolean {
        effects.persistEnabled(true)
        return startInternal("user_enable")
    }

    fun userDisable() {
        // Persist first so every late callback sees the user's final intent.
        effects.persistEnabled(false)
        stopInternal("user_disable")
    }

    fun runtimeStart(): Boolean = startInternal("runtime_start", requireDesiredEnabled = false)

    fun startIfDesired(): Boolean = startInternal("auto_start")

    fun runtimeStop() {
        stopInternal("runtime_stop")
    }

    fun onNetworkAvailable(callbackGeneration: Long) {
        val current = state
        if (callbackGeneration != current.generation || !effects.isDesiredEnabled()) return

        if (effects.currentListeningPort(callbackGeneration) != null) {
            effects.onAddressChanged()
            return
        }
        startInternal("network_recovery")
    }

    fun onNetworkLost(callbackGeneration: Long) {
        if (callbackGeneration != state.generation) return
        // USB forwarding uses loopback, so losing an address only changes the advertised endpoint.
        effects.onAddressChanged()
    }

    private fun startInternal(reason: String, requireDesiredEnabled: Boolean = true): Boolean {
        if (requireDesiredEnabled && !effects.isDesiredEnabled()) return false

        val runningPort = effects.currentListeningPort()
        val claim = synchronized(stateLock) {
            when {
                state.phase == ConfigServerLifecyclePhase.READY && runningPort != null -> null
                state.phase == ConfigServerLifecyclePhase.STARTING -> return false
                else -> transitionLocked(
                    ConfigServerState(
                        phase = ConfigServerLifecyclePhase.STARTING,
                        generation = state.generation + 1
                    ),
                    reason
                )
            }
        }
        if (claim == null) return true
        emit(claim)

        val generation = claim.current.generation
        effects.unregisterNetworkCallback(generation - 1)
        val port = try {
            effects.startServer(generation)
        } catch (_: Exception) {
            null
        }
        val started = port != null && port > 0 && effects.currentListeningPort(generation) == port

        val completion = synchronized(stateLock) {
            if (!isCurrentLocked(generation, ConfigServerLifecyclePhase.STARTING)) {
                null
            } else if (started) {
                transitionLocked(
                    ConfigServerState(ConfigServerLifecyclePhase.READY, generation, port = port),
                    reason
                )
            } else {
                transitionLocked(
                    ConfigServerState(
                        phase = ConfigServerLifecyclePhase.ERROR,
                        generation = generation,
                        error = "Config server could not listen on an available port. Check the connection service and try again."
                    ),
                    reason
                )
            }
        }

        if (completion == null) {
            launchCleanup(generation)
            return false
        }
        emit(completion)

        if (!started) {
            launchCleanup(generation)
            return false
        }

        effects.registerNetworkCallback(generation)
        val stillCurrent = synchronized(stateLock) {
            isCurrentLocked(generation, ConfigServerLifecyclePhase.READY)
        }
        if (!stillCurrent) {
            effects.unregisterNetworkCallback(generation)
            launchCleanup(generation)
            return false
        }
        return true
    }

    private fun stopInternal(reason: String) {
        val claim = synchronized(stateLock) {
            when (state.phase) {
                ConfigServerLifecyclePhase.STOPPED,
                ConfigServerLifecyclePhase.STOPPING -> null
                else -> transitionLocked(
                    ConfigServerState(
                        phase = ConfigServerLifecyclePhase.STOPPING,
                        generation = state.generation + 1
                    ),
                    reason
                )
            }
        } ?: return
        emit(claim)

        val generation = claim.current.generation
        effects.unregisterNetworkCallback(generation)
        launchStopWork {
            val outcome = try {
                effects.stopServer(generation)
            } catch (_: Exception) {
                ConfigServerStopOutcome.FAILED
            }
            val completion = synchronized(stateLock) {
                if (!isCurrentLocked(generation, ConfigServerLifecyclePhase.STOPPING)) {
                    null
                } else if (outcome == ConfigServerStopOutcome.STOPPED) {
                    transitionLocked(
                        ConfigServerState(ConfigServerLifecyclePhase.STOPPED, generation),
                        reason
                    )
                } else {
                    transitionLocked(
                        ConfigServerState(
                            phase = ConfigServerLifecyclePhase.ERROR,
                            generation = generation,
                            error = if (outcome == ConfigServerStopOutcome.TIMED_OUT) {
                                "Config server is still stopping. Try again."
                            } else {
                                "Config server could not stop cleanly. Try again."
                            }
                        ),
                        reason
                    )
                }
            }
            completion?.let(::emit)
        }
    }

    private fun launchCleanup(generation: Long) {
        effects.unregisterNetworkCallback(generation)
        launchStopWork {
            try {
                effects.stopServer(generation)
            } catch (_: Exception) {
                // A stale generation never owns the current state; cleanup is best effort only.
            }
        }
    }

    private fun isCurrentLocked(generation: Long, phase: ConfigServerLifecyclePhase): Boolean =
        state.generation == generation && state.phase == phase

    private fun transitionLocked(next: ConfigServerState, reason: String): Transition {
        val previous = state
        state = next
        return Transition(previous, next, reason)
    }

    private fun emit(transition: Transition) {
        effects.onStateChanged(transition.previous, transition.current, transition.reason)
    }
}
