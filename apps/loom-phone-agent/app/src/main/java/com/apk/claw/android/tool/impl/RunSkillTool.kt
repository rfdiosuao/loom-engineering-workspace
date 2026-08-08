package com.apk.claw.android.tool.impl

import com.apk.claw.android.runtime.LinuxRuntimeCompanionClient
import com.apk.claw.android.tool.BaseTool
import com.apk.claw.android.tool.ToolParameter
import com.apk.claw.android.tool.ToolResult

class RunSkillTool : BaseTool() {
    override fun getName(): String = "run_skill"

    override fun getDisplayName(): String = "调用 Skill"

    override fun getDescriptionEN(): String =
        "Run an installed, allowlisted Skill by its fixed identifier. Supports workspace.text.batch and workspace.jsonl.transform."

    override fun getDescriptionCN(): String =
        "按固定标识调用已安装的 Skill。仅支持 workspace.text.batch 和 workspace.jsonl.transform，不接受任意脚本。"

    override fun getParameters(): List<ToolParameter> = listOf(
        ToolParameter("skill_id", "string", "Fixed Skill identifier", true),
        ToolParameter("operation", "string", "Allowlisted operation for this Skill", false),
        ToolParameter("input", "string", "UTF-8 input, at most 256 KiB", true)
    )

    override fun execute(params: Map<String, Any>): ToolResult {
        val skillId = requireString(params, "skill_id")
        val input = requireString(params, "input")
        val operation = optionalString(
            params,
            "operation",
            LinuxRuntimeCompanionClient.defaultOperation(skillId)
        )
        val result = LinuxRuntimeCompanionClient.execute(skillId, operation, input)
        return if (result.success) {
            ToolResult.success(
                "skill_id=$skillId\nbackend=proot-alpine\nruntime=${result.runtimeVersion}\n" +
                    "duration_ms=${result.durationMs}\noutput:\n${result.output}"
            )
        } else {
            ToolResult.error("Skill execution failed: ${result.code}")
        }
    }
}
