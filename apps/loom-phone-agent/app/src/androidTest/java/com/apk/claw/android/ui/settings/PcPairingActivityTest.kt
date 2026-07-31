package com.apk.claw.android.ui.settings

import android.content.Intent
import android.view.View
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.apk.claw.android.R
import org.hamcrest.Matchers.containsString
import org.hamcrest.Description
import org.hamcrest.TypeSafeMatcher
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.espresso.matcher.ViewMatchers.withText
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PcPairingActivityTest {
    @Before
    fun configureUnavailableLan() {
        PcPairingActivity.setPairingRuntimeForTests(
            PcPairingActivity.PairingRuntime(
                lanIp = null,
                serverRunning = true,
                serverPort = 19527
            )
        )
    }

    @After
    fun clearRuntimeOverride() {
        PcPairingActivity.setPairingRuntimeForTests(null)
    }

    @Test
    fun lan_unavailable_then_usb_selection_restores_loopback_six_digit_pairing() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        ActivityScenario.launch<PcPairingActivity>(Intent(context, PcPairingActivity::class.java)).use {
            onView(withId(R.id.rbPairingLan)).perform(click())
            onView(withId(R.id.tvPairingStatus)).check(matches(withText(containsString("USB"))))

            onView(withId(R.id.rbPairingUsb)).perform(click())
            onView(withId(R.id.pairingCodeSection)).check(matches(isDisplayed()))
            onView(withId(R.id.tvPairingCode)).check(matches(withSixDigitCode()))
            onView(withId(R.id.tvPairingEndpoint))
                .check(matches(withText("http://127.0.0.1:19527")))
        }
    }

    private fun withSixDigitCode() = object : TypeSafeMatcher<View>() {
        override fun describeTo(description: Description) {
            description.appendText("a six-digit pairing code")
        }

        override fun matchesSafely(view: View): Boolean =
            (view as? TextView)?.text.toString().matches(Regex("\\d{6}"))
    }
}
