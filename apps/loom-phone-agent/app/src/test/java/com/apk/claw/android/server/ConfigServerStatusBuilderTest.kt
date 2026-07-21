package com.apk.claw.android.server

import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ConfigServerStatusBuilderTest {
    @Test
    fun running_status_reports_actual_port_and_address() {
        val target = JsonObject()

        ConfigServerStatusBuilder.addTo(
            target = target,
            running = true,
            address = "192.168.1.8:9530",
            actualPort = 9530,
            defaultPort = 9527
        )

        assertTrue(target["configServerRunning"].asBoolean)
        assertEquals("192.168.1.8:9530", target["configServerAddress"].asString)
        assertEquals(9530, target["configServerPort"].asInt)
        assertEquals(9530, target["serverPort"].asInt)
    }

    @Test
    fun stopped_status_keeps_legacy_default_port_but_marks_runtime_fields_null() {
        val target = JsonObject()

        ConfigServerStatusBuilder.addTo(
            target = target,
            running = false,
            address = null,
            actualPort = null,
            defaultPort = 9527
        )

        assertEquals(false, target["configServerRunning"].asBoolean)
        assertTrue(target["configServerAddress"].isJsonNull)
        assertTrue(target["configServerPort"].isJsonNull)
        assertEquals(9527, target["serverPort"].asInt)
    }
}
