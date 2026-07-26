package com.apk.claw.android.rpa

import java.util.concurrent.atomic.AtomicReference

data class GenerationSnapshot(
    val uiGeneration: Long,
    val serviceGeneration: String
)

class UiGenerationTracker(serviceGeneration: String) {
    private val state = AtomicReference(GenerationSnapshot(0L, serviceGeneration))

    fun markUiChanged(): Long = incrementGeneration()

    fun markActionDispatched(): Long = incrementGeneration()

    fun snapshot(): GenerationSnapshot = state.get()

    private fun incrementGeneration(): Long {
        while (true) {
            val current = state.get()
            val updated = current.copy(uiGeneration = current.uiGeneration + 1L)
            if (state.compareAndSet(current, updated)) {
                return updated.uiGeneration
            }
        }
    }
}
