package com.luming.linuxruntime

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri
import android.os.Bundle

class LinuxRuntimeProvider : ContentProvider() {
    private lateinit var installer: LinuxRuntimeInstaller
    private lateinit var engine: LinuxSkillEngine

    override fun onCreate(): Boolean {
        val appContext = context?.applicationContext ?: return false
        installer = LinuxRuntimeInstaller(appContext)
        engine = LinuxSkillEngine(installer)
        return true
    }

    override fun call(method: String, arg: String?, extras: Bundle?): Bundle = when (method) {
        "status" -> installer.status().toBundle()
        "install" -> installer.install().toBundle()
        "execute" -> executeAllowlistedSkill(arg, extras).toBundle()
        else -> RuntimeResult(false, "method_not_allowlisted").toBundle()
    }

    private fun executeAllowlistedSkill(skillId: String?, extras: Bundle?): RuntimeResult {
        val fixedSkillId = skillId ?: return RuntimeResult(false, "skill_id_missing")
        if (fixedSkillId !in setOf("workspace.text.batch", "workspace.jsonl.transform")) {
            return RuntimeResult(false, "skill_not_allowlisted")
        }
        val operation = extras?.getString("operation") ?: return RuntimeResult(false, "operation_missing")
        val input = extras.getString("input") ?: return RuntimeResult(false, "input_missing")
        return engine.execute(fixedSkillId, operation, input)
    }

    private fun RuntimeResult.toBundle() = Bundle().apply {
        putBoolean("success", success)
        putString("code", code)
        putString("output", output)
        putLong("duration_ms", durationMs)
        putString("runtime_version", LinuxRuntimeInstaller.RUNTIME_VERSION)
    }

    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?
    ): Cursor? = null

    override fun getType(uri: Uri): String? = null

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

    override fun update(
        uri: Uri,
        values: ContentValues?,
        selection: String?,
        selectionArgs: Array<out String>?
    ): Int = 0
}
