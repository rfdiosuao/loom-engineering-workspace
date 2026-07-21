package com.apk.claw.android.server

import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.OutputStream

class PhoneEventStreamResponseTest {
    @Test
    fun sends_chunked_sse_response_and_flushes_each_chunk() {
        val output = FlushCountingOutputStream()
        val response = TestResponse(
            ByteArrayInputStream("event: hello\ndata: {}\n\n".toByteArray(Charsets.UTF_8))
        )
        response.addHeader("Cache-Control", "no-cache")

        response.sendForTest(output)

        val text = output.toString(Charsets.UTF_8.name())
        assertTrue(text.startsWith("HTTP/1.1 200 OK"))
        assertTrue(text.contains("Content-Type: text/event-stream; charset=utf-8"))
        assertTrue(text.contains("Transfer-Encoding: chunked"))
        assertTrue(text.contains("event: hello"))
        assertTrue(output.flushCount >= 3)
    }

    private class TestResponse(input: ByteArrayInputStream) : PhoneEventStreamResponse(input) {
        fun sendForTest(outputStream: OutputStream) = send(outputStream)
    }

    private class FlushCountingOutputStream : ByteArrayOutputStream() {
        var flushCount = 0
            private set

        override fun flush() {
            flushCount += 1
            super.flush()
        }
    }
}
