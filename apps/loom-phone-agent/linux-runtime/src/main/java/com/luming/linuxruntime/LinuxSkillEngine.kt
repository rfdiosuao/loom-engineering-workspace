package com.luming.linuxruntime

class LinuxSkillEngine(private val installer: LinuxRuntimeInstaller) {
    fun execute(skillId: String, operation: String, input: String): RuntimeResult {
        if (input.toByteArray(Charsets.UTF_8).size > MAX_INPUT_BYTES) {
            return RuntimeResult(false, "input_budget_exceeded")
        }
        val executable = fixedExecutable(skillId, operation)
            ?: return RuntimeResult(false, "operation_not_allowlisted")
        val runtime = installer.activeRuntimeDirectory() ?: run {
            val installed = installer.install()
            if (!installed.success) return installed
            installer.activeRuntimeDirectory()
        } ?: return RuntimeResult(false, "runtime_missing")
        return installer.runProot(
            directory = runtime,
            executable = executable.first,
            arguments = executable.second,
            input = input,
            timeoutMs = TASK_TIMEOUT_MS
        )
    }

    private fun fixedExecutable(skillId: String, operation: String): Pair<String, List<String>>? = when (skillId) {
        "workspace.text.batch" -> when (operation) {
            "unique_sort" -> "/usr/bin/sort" to listOf("-u")
            "trim_lines" -> "/bin/sed" to listOf("-e", "s/^[[:space:]]*//", "-e", "s/[[:space:]]*$//")
            "lowercase" -> "/usr/bin/tr" to listOf("[:upper:]", "[:lower:]")
            else -> null
        }
        "workspace.jsonl.transform" -> when (operation) {
            "compact_lines" -> "/usr/bin/awk" to listOf("NF { print }")
            "unique_sort" -> "/usr/bin/sort" to listOf("-u")
            else -> null
        }
        else -> null
    }

    companion object {
        private const val MAX_INPUT_BYTES = 256 * 1024
        private const val TASK_TIMEOUT_MS = 15_000L
    }
}
