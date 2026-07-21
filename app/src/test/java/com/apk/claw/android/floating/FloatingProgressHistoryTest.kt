package com.apk.claw.android.floating

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FloatingProgressHistoryTest {

    @Test
    fun keepsTheLatestSequentialEventsAfterTaskCompletion() {
        val history = FloatingProgressHistory(capacity = 3)

        history.beginTask(1)
        history.recordTool(1, "open_app")
        history.recordThinking(2)
        history.recordTool(2, "get_screen_info")
        history.recordSuccess()

        assertEquals(3, history.snapshot().size)
        assertEquals(FloatingProgressHistory.Kind.THINKING, history.snapshot()[0].kind)
        assertEquals(2, history.snapshot()[0].round)
        assertEquals("get_screen_info", history.snapshot()[1].value)
        assertEquals(FloatingProgressHistory.Kind.SUCCESS, history.snapshot()[2].kind)
    }

    @Test
    fun oneRoundReportsThinkingThenToolOnceInOrder() {
        val history = FloatingProgressHistory(capacity = 4)

        history.beginTask(4)
        history.recordThinking(4)
        history.recordTool(4, "get_screen_info")
        history.recordTool(4, "get_screen_info")
        history.recordThinking(5)

        val entries = history.snapshot()
        assertEquals(3, entries.size)
        assertEquals(FloatingProgressHistory.Kind.THINKING, entries[0].kind)
        assertEquals(4, entries[0].round)
        assertEquals(4, entries[0].stage)
        assertEquals(FloatingProgressHistory.Kind.TOOL, entries[1].kind)
        assertEquals(4, entries[1].round)
        assertEquals(5, entries[1].stage)
        assertEquals("get_screen_info", entries[1].value)
        assertEquals(FloatingProgressHistory.Kind.THINKING, entries[2].kind)
        assertEquals(5, entries[2].round)
        assertEquals(6, entries[2].stage)
    }

    @Test
    fun newTaskReplacesPreviousTaskAndDuplicateStepsAreIgnored() {
        val history = FloatingProgressHistory(capacity = 3)
        history.beginTask(1)
        history.recordTool(1, "open_app")
        history.recordSuccess()

        history.beginTask(1)
        history.recordThinking(1)

        val entries = history.snapshot()
        assertEquals(1, entries.size)
        assertEquals(FloatingProgressHistory.Kind.THINKING, entries.single().kind)
        assertTrue(entries.none { it.kind == FloatingProgressHistory.Kind.SUCCESS })
    }
}
