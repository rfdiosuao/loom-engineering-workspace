package com.apk.claw.android

import com.apk.claw.android.agent.AgentToolPolicy
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TaskStartNavigationPolicyTest {
    @Test
    fun channel_tasks_should_not_force_home_by_default() {
        assertFalse(TaskStartNavigationPolicy.shouldPressHomeBeforeChannelTask())
    }

    @Test
    fun only_full_access_http_tasks_keep_legacy_home_behavior() {
        assertFalse(TaskStartNavigationPolicy.shouldPressHomeBeforeHttpTask(AgentToolPolicy.SAFE_ACTION))
        assertTrue(TaskStartNavigationPolicy.shouldPressHomeBeforeHttpTask(AgentToolPolicy.FULL_ACCESS))
    }
}
