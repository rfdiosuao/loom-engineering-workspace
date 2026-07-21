package com.apk.claw.android.server

import com.apk.claw.android.utils.XLog
import fi.iki.elonen.NanoHTTPD
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.LinkedHashMap
import java.util.Locale
import java.util.TimeZone

open class PhoneEventStreamResponse(
    input: InputStream
) : NanoHTTPD.Response(
    NanoHTTPD.Response.Status.OK,
    PhoneEventStreamController.MIME_EVENT_STREAM,
    input,
    -1L
) {
    private val headers = LinkedHashMap<String, String>()

    override fun addHeader(name: String, value: String) {
        headers[name] = value
        super.addHeader(name, value)
    }

    override fun send(outputStream: OutputStream) {
        try {
            writeHeaders(outputStream)
            writeEventChunks(outputStream)
            outputStream.write(FINAL_CHUNK)
            outputStream.flush()
        } catch (e: IOException) {
            XLog.w(TAG, "SSE client disconnected: ${e.message}")
        } finally {
            try {
                data.close()
            } catch (_: IOException) {
            }
        }
    }

    private fun writeHeaders(outputStream: OutputStream) {
        val builder = StringBuilder()
            .append("HTTP/1.1 ")
            .append(status.description)
            .append("\r\n")
            .append("Content-Type: ")
            .append(mimeType)
            .append("\r\n")

        if (!hasHeader("date")) {
            builder.append("Date: ").append(httpDate()).append("\r\n")
        }
        headers.forEach { (name, value) ->
            builder.append(name).append(": ").append(value).append("\r\n")
        }
        if (!hasHeader("connection")) {
            builder.append("Connection: keep-alive\r\n")
        }
        if (!hasHeader("transfer-encoding")) {
            builder.append("Transfer-Encoding: chunked\r\n")
        }
        builder.append("\r\n")
        outputStream.write(builder.toString().toByteArray(Charsets.UTF_8))
        outputStream.flush()
    }

    private fun writeEventChunks(outputStream: OutputStream) {
        val bytes = ByteArray(CHUNK_BUFFER_BYTES)
        while (true) {
            val length = data.read(bytes, 0, bytes.size)
            if (length <= 0) return
            outputStream.write(length.toString(16).toByteArray(Charsets.US_ASCII))
            outputStream.write(CRLF)
            outputStream.write(bytes, 0, length)
            outputStream.write(CRLF)
            outputStream.flush()
        }
    }

    private fun hasHeader(name: String): Boolean {
        return headers.keys.any { it.equals(name, ignoreCase = true) }
    }

    private fun httpDate(): String {
        return SimpleDateFormat("E, d MMM yyyy HH:mm:ss 'GMT'", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("GMT")
        }.format(Date())
    }

    companion object {
        private const val TAG = "PhoneEventStream"
        private const val CHUNK_BUFFER_BYTES = 16 * 1024
        private val CRLF = "\r\n".toByteArray(Charsets.US_ASCII)
        private val FINAL_CHUNK = "0\r\n\r\n".toByteArray(Charsets.US_ASCII)
    }
}
