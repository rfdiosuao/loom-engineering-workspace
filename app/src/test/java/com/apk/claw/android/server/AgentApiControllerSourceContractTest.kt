package com.apk.claw.android.server

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentApiControllerSourceContractTest {
    @Test
    fun execute_task_has_unhandled_exception_guard_that_releases_busy_state() {
        val source = File("src/main/java/com/apk/claw/android/server/AgentApiController.kt").readText()

        assertTrue(source.contains("catch (t: Throwable)"))
        assertTrue(source.contains("agent_unhandled_exception"))
        assertTrue(source.contains("CrashLogApiController.recordThrowable(ClawApplication.instance, \"agent-execute-task\", t)"))
        assertTrue(source.contains("synchronized(taskLock) { releaseTaskSlotLocked() }"))
    }

    @Test
    fun action_fast_reports_observable_verify_fields() {
        val source = File("src/main/java/com/apk/claw/android/server/AgentApiController.kt").readText()

        assertTrue(source.contains("addProperty(\"actionMs\""))
        assertTrue(source.contains("addProperty(\"verifyMs\""))
        assertTrue(source.contains("addProperty(\"beforeHash\""))
        assertTrue(source.contains("addProperty(\"afterHash\""))
        assertTrue(source.contains("addProperty(\"changed\""))
    }

    @Test
    fun async_worker_claims_global_task_slot_before_marking_task_running() {
        val source = File("src/main/java/com/apk/claw/android/server/AgentApiController.kt").readText()

        assertTrue(source.contains("claimTaskSlotLocked()"))
        assertTrue(source.contains("releaseTaskSlotLocked()"))
        assertTrue(source.contains("it.status = \"running\""))
    }

    @Test
    fun async_task_and_event_endpoints_expose_compatible_progress_log() {
        val source = File("src/main/java/com/apk/claw/android/server/AgentApiController.kt").readText()
        val eventsHandler = source
            .substringAfter("fun handleGetAsyncTaskEvents")
            .substringBefore("fun handleCancelAsyncTask")
        val taskState = source
            .substringAfter("private class AsyncTaskState")
            .substringBefore("private class ApiMetrics")

        assertEquals(2, Regex("AgentProgressLogBuilder\\.attachTo\\(this, eventArray\\)").findAll(source).count())
        assertTrue(eventsHandler.contains("add(\"events\", eventArray)"))
        assertTrue(eventsHandler.contains("AgentProgressLogBuilder.attachTo(this, eventArray)"))
        assertTrue(taskState.contains("AgentProgressLogBuilder.attachTo(this, eventArray)"))
    }
}
