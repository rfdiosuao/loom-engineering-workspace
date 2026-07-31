package com.apk.claw.android.ui.settings

import android.content.Intent
import android.view.View
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.apk.claw.android.R
import com.apk.claw.android.server.PhonePairingBootstrap
import org.hamcrest.Matchers.containsString
import org.hamcrest.Matchers.not
import org.hamcrest.Description
import org.hamcrest.TypeSafeMatcher
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.espresso.matcher.ViewMatchers.withText
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PcPairingActivityTest {
    private var runtimeOverride: AutoCloseable? = null

    @After
    fun clearRuntimeOverride() {
        runtimeOverride?.close()
        runtimeOverride = null
    }

    @Test
    fun lan_unavailable_then_usb_selection_revokes_old_payload_and_restores_loopback_code() {
        installRuntime(lanIp = null)
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        ActivityScenario.launch<PcPairingActivity>(Intent(context, PcPairingActivity::class.java)).use { scenario ->
            val originalUsbPayload = pairingPayload(scenario)

            onView(withId(R.id.rbPairingLan)).perform(click())
            onView(withId(R.id.tvPairingStatus))
                .check(matches(withText(R.string.pc_pairing_lan_unavailable)))
            onView(withId(R.id.tvTip))
                .check(matches(withText(R.string.pc_pairing_tip_lan_unavailable)))
            assertUsbPayloadIsRejected(originalUsbPayload)

            onView(withId(R.id.rbPairingUsb)).perform(click())
            assertUsbPairingVisible()
        }
    }

    @Test
    fun hotspot_runtime_keeps_usb_available_and_switches_to_lan_then_back() {
        installRuntime(lanIp = "192.168.43.1")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        ActivityScenario.launch<PcPairingActivity>(Intent(context, PcPairingActivity::class.java)).use {
            assertUsbPairingVisible()
            onView(withId(R.id.tvPairingPayload)).check(matches(withText(containsString("x=usb"))))

            onView(withId(R.id.rbPairingLan)).perform(click())
            onView(withId(R.id.pairingCodeSection)).check(matches(not(isDisplayed())))
            onView(withId(R.id.tvPairingEndpoint))
                .check(matches(withText("http://192.168.43.1:19527")))
            onView(withId(R.id.tvPairingPayload)).check(matches(withText(containsString("x=lan"))))

            onView(withId(R.id.rbPairingUsb)).perform(click())
            assertUsbPairingVisible()
            onView(withId(R.id.tvPairingPayload)).check(matches(withText(containsString("x=usb"))))
        }
    }

    @Test
    fun refreshing_usb_pairing_revokes_the_previous_payload() {
        installRuntime(lanIp = "192.168.43.1")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        ActivityScenario.launch<PcPairingActivity>(Intent(context, PcPairingActivity::class.java)).use { scenario ->
            val originalUsbPayload = pairingPayload(scenario)

            onView(withId(R.id.btnGenerate)).perform(click())
            assertUsbPairingVisible()
            assertUsbPayloadIsRejected(originalUsbPayload)
        }
    }

    private fun installRuntime(lanIp: String?) {
        runtimeOverride = PcPairingActivity.installPairingRuntimeProviderForTests {
            PcPairingActivity.PairingRuntime(
                lanIp = lanIp,
                serverRunning = true,
                serverPort = 19527
            )
        }
    }

    private fun assertUsbPairingVisible() {
        onView(withId(R.id.pairingCodeSection)).check(matches(isDisplayed()))
        onView(withId(R.id.tvPairingCode)).check(matches(withSixDigitCode()))
        onView(withId(R.id.tvPairingEndpoint))
            .check(matches(withText("http://127.0.0.1:19527")))
    }

    private fun pairingPayload(scenario: ActivityScenario<PcPairingActivity>): String {
        var payload = ""
        scenario.onActivity { activity ->
            payload = activity.findViewById<TextView>(R.id.tvPairingPayload).text.toString()
        }
        return payload
    }

    private fun assertUsbPayloadIsRejected(payload: String) {
        val query = java.net.URI(payload).rawQuery.split("&").associate { field ->
            val parts = field.split("=", limit = 2)
            parts[0] to java.net.URLDecoder.decode(parts.getOrElse(1) { "" }, "UTF-8")
        }
        val result = PhonePairingBootstrap.claim(
            PhonePairingBootstrap.ClaimRequest(
                sessionId = query.getValue("s"),
                code = query.getValue("c"),
                nonce = "",
                proof = "",
                transport = "usb",
                deviceInstanceId = query.getValue("d"),
                launcherId = "loom-instrumentation",
                launcherName = "LOOM"
            ),
            remoteAddress = "127.0.0.1"
        )

        assertFalse(result.success)
        assertEquals("phone_pairing_code_invalid", result.errorCode)
    }

    private fun withSixDigitCode() = object : TypeSafeMatcher<View>() {
        override fun describeTo(description: Description) {
            description.appendText("a six-digit pairing code")
        }

        override fun matchesSafely(view: View): Boolean =
            (view as? TextView)?.text.toString().matches(Regex("\\d{6}"))
    }
}
