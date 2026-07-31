package com.apk.claw.android.ui.settings

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import android.view.LayoutInflater
import android.widget.RadioGroup
import com.apk.claw.android.R
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PcPairingActivityTest {
    @Test
    fun pairing_layout_exposes_both_transport_choices_and_endpoint() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val root = LayoutInflater.from(context).inflate(R.layout.activity_pc_pairing, null)
        val selector = root.findViewById<RadioGroup>(R.id.pairingTransportSelector)

        assertNotNull(selector)
        assertNotNull(root.findViewById(R.id.rbPairingUsb))
        assertNotNull(root.findViewById(R.id.rbPairingLan))
        assertNotNull(root.findViewById(R.id.tvPairingEndpoint))
        assertEquals(R.id.rbPairingUsb, selector.checkedRadioButtonId)
    }
}
