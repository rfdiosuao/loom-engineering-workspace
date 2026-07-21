package com.apk.claw.android.server

import java.util.concurrent.atomic.AtomicInteger

class PhoneEventStreamConnectionGate(private val maxActive: Int) {
    private val active = AtomicInteger(0)

    fun tryAcquire(): Lease? {
        while (true) {
            val current = active.get()
            if (current >= maxActive.coerceAtLeast(1)) return null
            if (active.compareAndSet(current, current + 1)) return Lease(active)
        }
    }

    fun activeCount(): Int = active.get()

    class Lease internal constructor(private val active: AtomicInteger) : AutoCloseable {
        private val closed = AtomicInteger(0)

        override fun close() {
            if (closed.compareAndSet(0, 1)) {
                active.updateAndGet { value -> (value - 1).coerceAtLeast(0) }
            }
        }
    }
}
