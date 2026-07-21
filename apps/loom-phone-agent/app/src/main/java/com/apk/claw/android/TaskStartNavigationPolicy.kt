package com.apk.claw.android

import com.apk.claw.android.agent.AgentToolPolicy

object TaskStartNavigationPolicy {
    fun shouldPressHomeBeforeChannelTask(): Boolean = false

    fun shouldPressHomeBeforeHttpTask(toolPolicy: AgentToolPolicy): Boolean {
        return toolPolicy == AgentToolPolicy.FULL_ACCESS
    }
}
