package com.apk.claw.android.server

import fi.iki.elonen.NanoHTTPD
import java.io.ByteArrayInputStream
import java.io.InputStream

class CachedBodySession(
    private val delegate: NanoHTTPD.IHTTPSession,
    private val bodyBytes: ByteArray
) : NanoHTTPD.IHTTPSession {
    private val cachedHeaders = delegate.headers.toMutableMap().apply {
        this["content-length"] = bodyBytes.size.toString()
        this["Content-Length"] = bodyBytes.size.toString()
    }

    override fun execute() = delegate.execute()
    override fun getCookies(): NanoHTTPD.CookieHandler = delegate.cookies
    override fun getHeaders(): MutableMap<String, String> = cachedHeaders
    override fun getInputStream(): InputStream = ByteArrayInputStream(bodyBytes)
    override fun getMethod(): NanoHTTPD.Method = delegate.method
    override fun getParms(): MutableMap<String, String> = delegate.parms
    override fun getParameters(): MutableMap<String, MutableList<String>> = delegate.parameters
    override fun getQueryParameterString(): String = delegate.queryParameterString
    override fun getUri(): String = delegate.uri
    override fun getRemoteIpAddress(): String = delegate.remoteIpAddress
    override fun getRemoteHostName(): String = delegate.remoteHostName

    override fun parseBody(files: MutableMap<String, String>) {
        if (bodyBytes.isNotEmpty()) {
            files["postData"] = String(bodyBytes, Charsets.UTF_8)
        }
    }
}
