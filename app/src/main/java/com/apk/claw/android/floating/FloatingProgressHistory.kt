package com.apk.claw.android.floating

class FloatingProgressHistory(
    private val capacity: Int = 3
) {
    enum class Kind {
        THINKING,
        TOOL,
        SUCCESS,
        ERROR
    }

    data class Entry(
        val kind: Kind,
        val round: Int = 0,
        val stage: Int = 0,
        val value: String = ""
    )

    private val entries = ArrayDeque<Entry>()
    private val thinkingRounds = mutableSetOf<Int>()
    private var nextStage = 1

    fun beginTask(round: Int) {
        entries.clear()
        thinkingRounds.clear()
        nextStage = round.coerceAtLeast(1)
        recordThinking(round)
    }

    fun recordThinking(round: Int) {
        val normalizedRound = round.coerceAtLeast(1)
        if (!thinkingRounds.add(normalizedRound)) return
        append(Entry(Kind.THINKING, normalizedRound, takeNextStage()))
    }

    fun recordTool(round: Int, toolId: String) {
        val normalizedRound = round.coerceAtLeast(1)
        val normalizedToolId = toolId.trim().lowercase()
        val latest = entries.lastOrNull()
        if (latest?.kind == Kind.TOOL && latest.round == normalizedRound && latest.value == normalizedToolId) return
        append(Entry(Kind.TOOL, normalizedRound, takeNextStage(), normalizedToolId))
    }

    fun recordSuccess() {
        append(Entry(Kind.SUCCESS))
    }

    fun recordError() {
        append(Entry(Kind.ERROR))
    }

    fun snapshot(): List<Entry> = entries.toList()

    fun isEmpty(): Boolean = entries.isEmpty()

    private fun append(entry: Entry) {
        if (entries.lastOrNull() == entry) return
        entries.addLast(entry)
        while (entries.size > capacity.coerceAtLeast(1)) {
            entries.removeFirst()
        }
    }

    private fun takeNextStage(): Int = nextStage++
}
