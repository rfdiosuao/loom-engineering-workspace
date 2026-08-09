package com.apk.claw.android.runtime

import android.content.Context
import android.net.Uri
import android.os.Bundle
import com.apk.claw.android.ClawApplication
import com.apk.claw.android.skill.LinuxSkillRuntimeState

data class LinuxCompanionResult(
    val success: Boolean,
    val code: String,
    val output: String = "",
    val durationMs: Long = 0L,
    val runtimeVersion: String = ""
)

object LinuxRuntimeCompanionClient {
    const val COMPANION_PACKAGE = "com.luming.linuxruntime"
    const val AUTHORITY = "com.luming.linuxruntime.runtime"
    private val uri: Uri = Uri.parse("content://$AUTHORITY")

    fun status(context: Context = ClawApplication.instance): LinuxCompanionResult =
        invoke(context, "status", null, Bundle.EMPTY)

    fun install(context: Context = ClawApplication.instance): LinuxCompanionResult =
        invoke(context, "install", null, Bundle.EMPTY)

    fun runtimeState(context: Context = ClawApplication.instance): LinuxSkillRuntimeState {
        val result = status(context)
        return when {
            result.success && result.code == "ready" -> LinuxSkillRuntimeState.READY
            result.code == "disabled" -> LinuxSkillRuntimeState.DISABLED
            result.code in setOf("damaged", "hash_mismatch", "health_check_failed") -> LinuxSkillRuntimeState.DAMAGED
            else -> LinuxSkillRuntimeState.MISSING
        }
    }

    fun execute(
        skillId: String,
        operation: String,
        input: String,
        context: Context = ClawApplication.instance
    ): LinuxCompanionResult {
        if (skillId !in ALLOWED_SKILLS) return LinuxCompanionResult(false, "skill_not_allowlisted")
        if (operation !in allowedOperations(skillId)) return LinuxCompanionResult(false, "operation_not_allowlisted")
        if (input.toByteArray(Charsets.UTF_8).size > MAX_INPUT_BYTES) {
            return LinuxCompanionResult(false, "input_budget_exceeded")
        }
        return invoke(
            context = context,
            method = "execute",
            arg = skillId,
            extras = Bundle().apply {
                putString("operation", operation)
                putString("input", input)
            }
        )
    }

    fun defaultOperation(skillId: String): String = when (skillId) {
        "workspace.text.batch" -> "unique_sort"
        "workspace.jsonl.transform" -> "compact_lines"
        else -> ""
    }

    private fun invoke(context: Context, method: String, arg: String?, extras: Bundle): LinuxCompanionResult =
        try {
            val reply = context.contentResolver.call(uri, method, arg, extras)
                ?: return LinuxCompanionResult(false, "empty_companion_response")
            LinuxCompanionResult(
                success = reply.getBoolean("success", false),
                code = reply.getString("code", "unknown") ?: "unknown",
                output = reply.getString("output", "") ?: "",
                durationMs = reply.getLong("duration_ms", 0L),
                runtimeVersion = reply.getString("runtime_version", "") ?: ""
            )
        } catch (_: SecurityException) {
            LinuxCompanionResult(false, "signature_mismatch")
        } catch (_: IllegalArgumentException) {
            LinuxCompanionResult(false, "companion_missing")
        } catch (_: Exception) {
            LinuxCompanionResult(false, "companion_unavailable")
        }

    private fun allowedOperations(skillId: String): Set<String> = when (skillId) {
        "workspace.text.batch" -> setOf("unique_sort", "trim_lines", "lowercase")
        "workspace.jsonl.transform" -> setOf("compact_lines", "unique_sort")
        else -> emptySet()
    }

    private val ALLOWED_SKILLS = setOf("workspace.text.batch", "workspace.jsonl.transform")
    private const val MAX_INPUT_BYTES = 256 * 1024
}
