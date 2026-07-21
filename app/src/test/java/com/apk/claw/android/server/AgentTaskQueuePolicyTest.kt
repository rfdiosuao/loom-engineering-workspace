package com.apk.claw.android.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AgentTaskQueuePolicyTest {
    @Test
    fun selects_highest_priority_then_oldest_queued_task() {
        val tasks = listOf(
            AgentTaskQueuePolicy.Item(id = "old-low", status = "queued", priority = 0, createdAt = 1000L),
            AgentTaskQueuePolicy.Item(id = "new-high", status = "queued", priority = 10, createdAt = 3000L),
            AgentTaskQueuePolicy.Item(id = "old-high", status = "queued", priority = 10, createdAt = 2000L),
            AgentTaskQueuePolicy.Item(id = "running-high", status = "running", priority = 99, createdAt = 1L),
            AgentTaskQueuePolicy.Item(id = "cancelled-high", status = "cancelled", priority = 99, createdAt = 2L),
        )

        assertEquals("old-high", AgentTaskQueuePolicy.nextQueuedId(tasks))
        assertEquals(3, AgentTaskQueuePolicy.queueDepth(tasks))
        assertEquals(1, AgentTaskQueuePolicy.queuePosition(tasks, "old-high"))
        assertEquals(2, AgentTaskQueuePolicy.queuePosition(tasks, "new-high"))
        assertEquals(3, AgentTaskQueuePolicy.queuePosition(tasks, "old-low"))
        assertNull(AgentTaskQueuePolicy.queuePosition(tasks, "running-high"))
    }

    @Test
    fun cancel_only_marks_queued_or_running_tasks_as_cancellable() {
        assertEquals(true, AgentTaskQueuePolicy.canCancel("queued"))
        assertEquals(true, AgentTaskQueuePolicy.canCancel("running"))
        assertEquals(false, AgentTaskQueuePolicy.canCancel("success"))
        assertEquals(false, AgentTaskQueuePolicy.canCancel("error"))
        assertEquals(false, AgentTaskQueuePolicy.canCancel("cancelled"))
    }

    @Test
    fun active_queue_capacity_counts_only_queued_and_running_tasks() {
        val tasks = listOf(
            AgentTaskQueuePolicy.Item(id = "queued-1", status = "queued", priority = 0, createdAt = 1000L),
            AgentTaskQueuePolicy.Item(id = "running-1", status = "running", priority = 0, createdAt = 1001L),
            AgentTaskQueuePolicy.Item(id = "success-1", status = "success", priority = 0, createdAt = 1002L),
            AgentTaskQueuePolicy.Item(id = "error-1", status = "error", priority = 0, createdAt = 1003L),
        )

        assertEquals(2, AgentTaskQueuePolicy.activeCount(tasks))
        assertEquals(false, AgentTaskQueuePolicy.canAcceptNewTask(tasks, maxActive = 2))
        assertEquals(true, AgentTaskQueuePolicy.canAcceptNewTask(tasks, maxActive = 3))
    }
}
