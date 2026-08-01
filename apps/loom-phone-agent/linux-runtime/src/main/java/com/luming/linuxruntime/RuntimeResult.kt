package com.luming.linuxruntime

data class RuntimeResult(
    val success: Boolean,
    val code: String,
    val output: String = "",
    val durationMs: Long = 0L
)
