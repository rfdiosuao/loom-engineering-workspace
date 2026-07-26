package com.apk.claw.android.rpa

import android.graphics.Bitmap
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class BitmapLumaAdapterTest {
    @Test
    fun converts_real_bitmap_pixels_to_integer_bt601_luma() {
        val bitmap = Bitmap.createBitmap(
            intArrayOf(
                0xffff0000.toInt(),
                0xff00ff00.toInt(),
                0xff0000ff.toInt(),
                0xffffffff.toInt()
            ),
            2,
            2,
            Bitmap.Config.ARGB_8888
        )

        val plane = BitmapLumaAdapter.fromBitmap(bitmap)

        assertEquals(76, plane[0, 0])
        assertEquals(150, plane[1, 0])
        assertEquals(29, plane[0, 1])
        assertEquals(255, plane[1, 1])
        bitmap.recycle()
    }
}
