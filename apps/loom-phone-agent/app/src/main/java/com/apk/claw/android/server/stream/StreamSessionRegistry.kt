package com.apk.claw.android.server.stream

import java.io.ByteArrayInputStream
import java.io.InputStream
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import java.util.UUID
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.CopyOnWriteArraySet
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

data class PhoneStreamOptions(
    val fps: Int = 15,
    val maxLongSide: Int = 1280,
    val bitRate: Int = 2_400_000
) {
    fun normalized(): PhoneStreamOptions = copy(
        fps = fps.coerceIn(10, 20),
        maxLongSide = maxLongSide.coerceIn(480, 1600),
        bitRate = bitRate.coerceIn(600_000, 8_000_000)
    )
}

data class PhoneStreamGrant(
    val sessionId: String,
    val clientSessionId: String,
    val launcherId: String,
    val streamToken: String,
    val tokenExpiresAtEpochMs: Long,
    val state: String,
    val options: PhoneStreamOptions,
    val width: Int = 0,
    val height: Int = 0,
    val codec: String = "avc1.42E01F",
    val message: String = "",
    val requiresUserConsent: Boolean = false
)

class StreamSessionRegistry(
    private val clockMs: () -> Long = System::currentTimeMillis,
    private val tokenFactory: () -> String = ::secureToken
) {
    companion object {
        const val TOKEN_TTL_MS = 30_000L
        private const val SUBSCRIBER_QUEUE_CAPACITY = 6

        private fun secureToken(): String {
            val bytes = ByteArray(32)
            SecureRandom().nextBytes(bytes)
            return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
        }
    }

    private data class Session(
        val sessionId: String,
        val clientSessionId: String,
        val launcherId: String,
        var streamToken: String,
        var tokenExpiresAtEpochMs: Long,
        val options: PhoneStreamOptions,
        var state: String = "permission_required",
        var width: Int = 0,
        var height: Int = 0,
        var codec: String = "avc1.42E01F",
        var message: String = "",
        var requiresUserConsent: Boolean = true,
        val sequence: AtomicInteger = AtomicInteger(0),
        val subscribers: CopyOnWriteArraySet<SubscriberInputStream> = CopyOnWriteArraySet()
    )

    private val lock = Any()
    private var current: Session? = null

    fun createOrReuse(
        clientSessionId: String,
        launcherId: String,
        options: PhoneStreamOptions
    ): PhoneStreamGrant = synchronized(lock) {
        val normalized = options.normalized()
        val existing = current
        if (
            existing != null &&
            existing.clientSessionId == clientSessionId &&
            existing.launcherId == launcherId
        ) {
            if (existing.tokenExpiresAtEpochMs <= clockMs()) {
                existing.streamToken = tokenFactory()
                existing.tokenExpiresAtEpochMs = clockMs() + TOKEN_TTL_MS
            }
            return@synchronized existing.grant()
        }
        existing?.close()
        val next = Session(
            sessionId = UUID.randomUUID().toString(),
            clientSessionId = clientSessionId,
            launcherId = launcherId,
            streamToken = tokenFactory(),
            tokenExpiresAtEpochMs = clockMs() + TOKEN_TTL_MS,
            options = normalized
        )
        current = next
        next.grant()
    }

    fun currentGrant(sessionId: String): PhoneStreamGrant? = synchronized(lock) {
        current?.takeIf { it.sessionId == sessionId }?.grant()
    }

    fun isCurrent(sessionId: String): Boolean = synchronized(lock) {
        current?.sessionId == sessionId
    }

    fun markPermissionRequired(sessionId: String, message: String = "请在手机确认屏幕共享授权") {
        update(sessionId) {
            state = "permission_required"
            requiresUserConsent = true
            this.message = message
        }
    }

    fun markActive(sessionId: String, width: Int, height: Int, codec: String) {
        update(sessionId) {
            state = "active"
            requiresUserConsent = false
            this.width = width
            this.height = height
            this.codec = codec
            message = ""
        }
    }

    fun markError(sessionId: String, message: String) {
        update(sessionId) {
            state = "error"
            requiresUserConsent = false
            this.message = message.take(240)
        }
    }

    fun open(sessionId: String, streamToken: String, launcherId: String): InputStream? = synchronized(lock) {
        val session = current ?: return@synchronized null
        if (
            session.sessionId != sessionId ||
            session.launcherId != launcherId ||
            session.state != "active" ||
            session.tokenExpiresAtEpochMs <= clockMs() ||
            !constantTimeEquals(session.streamToken, streamToken)
        ) return@synchronized null
        SubscriberInputStream(session).also { session.subscribers += it }
    }

    fun publish(
        sessionId: String,
        payload: ByteArray,
        presentationTimeUs: Long,
        keyFrame: Boolean
    ) {
        val session = synchronized(lock) {
            current?.takeIf { it.sessionId == sessionId && it.state == "active" }
        } ?: return
        val packet = H264WireProtocol.packet(
            payload,
            presentationTimeUs,
            keyFrame,
            session.sequence.incrementAndGet()
        )
        session.subscribers.forEach { it.offer(packet) }
    }

    fun stop(sessionId: String, streamToken: String, launcherId: String): Boolean = synchronized(lock) {
        val session = current ?: return@synchronized false
        if (
            session.sessionId != sessionId ||
            session.launcherId != launcherId ||
            !constantTimeEquals(session.streamToken, streamToken)
        ) return@synchronized false
        session.close()
        current = null
        true
    }

    fun stopFromService(sessionId: String) = synchronized(lock) {
        val session = current?.takeIf { it.sessionId == sessionId } ?: return@synchronized
        session.close()
        current = null
    }

    private fun update(sessionId: String, block: Session.() -> Unit) = synchronized(lock) {
        current?.takeIf { it.sessionId == sessionId }?.apply(block)
    }

    private fun Session.grant(): PhoneStreamGrant = PhoneStreamGrant(
        sessionId = sessionId,
        clientSessionId = clientSessionId,
        launcherId = launcherId,
        streamToken = streamToken,
        tokenExpiresAtEpochMs = tokenExpiresAtEpochMs,
        state = state,
        options = options,
        width = width,
        height = height,
        codec = codec,
        message = message,
        requiresUserConsent = requiresUserConsent
    )

    private fun Session.close() {
        state = "stopped"
        subscribers.forEach { it.close() }
        subscribers.clear()
    }

    private inner class SubscriberInputStream(
        private val session: Session
    ) : InputStream() {
        private val closed = AtomicBoolean(false)
        private val queue = ArrayBlockingQueue<ByteArray>(SUBSCRIBER_QUEUE_CAPACITY)
        private var currentBytes: ByteArrayInputStream? = null

        fun offer(packet: ByteArray) {
            if (closed.get()) return
            while (!queue.offer(packet)) queue.poll()
        }

        override fun read(): Int {
            val one = ByteArray(1)
            val count = read(one, 0, 1)
            return if (count < 0) -1 else one[0].toInt() and 0xff
        }

        override fun read(target: ByteArray, offset: Int, length: Int): Int {
            if (closed.get()) return -1
            require(offset >= 0 && length >= 0 && offset + length <= target.size)
            if (length == 0) return 0
            while (!closed.get()) {
                val source = currentBytes
                if (source != null) {
                    val count = source.read(target, offset, length)
                    if (count >= 0) return count
                    currentBytes = null
                }
                val next = queue.poll(2, TimeUnit.SECONDS)
                if (next != null) currentBytes = ByteArrayInputStream(next)
                else if (!isCurrent(session.sessionId)) return -1
            }
            return -1
        }

        override fun close() {
            if (!closed.compareAndSet(false, true)) return
            queue.clear()
            currentBytes = null
            session.subscribers -= this
        }
    }
}

private fun constantTimeEquals(left: String, right: String): Boolean = MessageDigest.isEqual(
    left.toByteArray(Charsets.UTF_8),
    right.toByteArray(Charsets.UTF_8)
)

object PhoneStreamRuntime {
    val sessions = StreamSessionRegistry()
}
