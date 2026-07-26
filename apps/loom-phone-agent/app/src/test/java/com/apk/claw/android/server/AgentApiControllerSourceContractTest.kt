package com.apk.claw.android.server

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentApiControllerSourceContractTest {
    private val controllerSource = File("src/main/java/com/apk/claw/android/server/AgentApiController.kt").readText()
    private val appViewModelSource = File("src/main/java/com/apk/claw/android/AppViewModel.kt").readText()

    @Test
    fun execute_task_has_unhandled_exception_guard_that_releases_busy_state() {
        val source = controllerSource

        assertTrue(source.contains("catch (t: Throwable)"))
        assertTrue(source.contains("agent_unhandled_exception"))
        assertTrue(source.contains("CrashLogApiController.recordThrowable(ClawApplication.instance, \"agent-execute-task\", t)"))
        assertTrue(source.contains("synchronized(taskLock) { releaseTaskSlotLocked() }"))
    }

    @Test
    fun action_fast_reports_observable_verify_fields() {
        val source = controllerSource

        assertTrue(source.contains("addProperty(\"actionMs\""))
        assertTrue(source.contains("addProperty(\"verifyMs\""))
        assertTrue(source.contains("addProperty(\"beforeHash\""))
        assertTrue(source.contains("addProperty(\"afterHash\""))
        assertTrue(source.contains("addProperty(\"changed\""))
    }

    @Test
    fun async_worker_claims_global_task_slot_before_marking_task_running() {
        val source = controllerSource

        assertTrue(source.contains("claimTaskSlotLocked()"))
        assertTrue(source.contains("releaseTaskSlotLocked()"))
        assertTrue(source.contains("it.status = \"running\""))
    }

    @Test
    fun async_task_and_event_endpoints_expose_compatible_progress_log() {
        val source = controllerSource

        assertTrue(source.contains("add(\"progressLog\", AgentProgressLogBuilder.fromEvents"))
    }

    @Test
    fun learning_is_opt_in_sanitized_completion_only_and_draft_only() {
        val source = controllerSource

        assertTrue(source.contains("if (learnTemplate) AgentTrajectoryRecorder() else null"))
        assertTrue(source.contains("trajectoryRecorder?.beforeAction"))
        assertTrue(source.contains("trajectoryRecorder?.afterAction"))
        assertTrue(source.contains("HybridTemplateCompiler.compile"))
        assertTrue(source.contains("WorkflowTemplateManager.saveDraft"))
        assertTrue(source.contains("DeviceProfileProvider.current()"))
        assertTrue(source.contains("riskDeclaration = null"))
        assertTrue(!source.contains("riskDeclaration = TemplateRiskLevel.READ_ONLY"))
        assertTrue(source.contains("override fun onTerminal"))
        assertTrue(source.contains("if (terminal.shouldCompile && learnTemplate)"))
        assertTrue(source.contains("allowReplayFailedStep = false"))
        assertTrue(source.indexOf("HybridTemplateCompiler.compile") > source.indexOf("override fun onComplete"))
        assertTrue(!source.contains("learnFromExecution("))
    }

    @Test
    fun production_agent_configs_use_policy_absolute_round_cap() {
        assertTrue(controllerSource.contains(".maxIterations(AgentExecutionPolicy.absoluteMaxRounds())"))
        assertTrue(!controllerSource.contains(".maxIterations(AgentExecutionPolicy.defaultMaxRounds(AgentExecutionMode.FULL))"))
        assertTrue(appViewModelSource.contains(".maxIterations(AgentExecutionPolicy.absoluteMaxRounds())"))
        assertTrue(!appViewModelSource.contains(".maxIterations(60)"))
    }
}
