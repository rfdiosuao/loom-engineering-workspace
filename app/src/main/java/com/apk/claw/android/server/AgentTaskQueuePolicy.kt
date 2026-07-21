package com.apk.claw.android.server

object AgentTaskQueuePolicy {
    data class Item(
        val id: String,
        val status: String,
        val priority: Int,
        val createdAt: Long
    )

    fun nextQueuedId(items: Collection<Item>): String? {
        return items
            .filter { it.status == "queued" }
            .sortedWith(compareByDescending<Item> { it.priority }.thenBy { it.createdAt })
            .firstOrNull()
            ?.id
    }

    fun queueDepth(items: Collection<Item>): Int {
        return items.count { it.status == "queued" }
    }

    fun activeCount(items: Collection<Item>): Int {
        return items.count { it.status == "queued" || it.status == "running" }
    }

    fun canAcceptNewTask(items: Collection<Item>, maxActive: Int): Boolean {
        return activeCount(items) < maxActive.coerceAtLeast(1)
    }

    fun queuePosition(items: Collection<Item>, taskId: String): Int? {
        val queued = items
            .filter { it.status == "queued" }
            .sortedWith(compareByDescending<Item> { it.priority }.thenBy { it.createdAt })
        val index = queued.indexOfFirst { it.id == taskId }
        return if (index >= 0) index + 1 else null
    }

    fun canCancel(status: String): Boolean {
        return status == "queued" || status == "running"
    }
}
