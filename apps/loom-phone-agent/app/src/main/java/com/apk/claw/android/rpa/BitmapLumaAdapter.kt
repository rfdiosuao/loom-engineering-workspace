package com.apk.claw.android.rpa

import android.graphics.Bitmap

object BitmapLumaAdapter {
    fun fromBitmap(bitmap: Bitmap): LumaPlane {
        val width = bitmap.width
        val height = bitmap.height
        require(width > 0 && height > 0) { "bitmap_dimensions_invalid" }
        val pixelCount = width.toLong() * height.toLong()
        require(pixelCount <= LumaPlane.MAX_PIXELS) { "bitmap_dimensions_too_large" }

        val pixels = IntArray(pixelCount.toInt())
        bitmap.getPixels(pixels, 0, width, 0, 0, width, height)
        for (index in pixels.indices) {
            pixels[index] = bt601(pixels[index])
        }
        return LumaPlane.owned(width, height, pixels)
    }

    internal fun bt601(argb: Int): Int {
        val red = argb ushr 16 and 0xff
        val green = argb ushr 8 and 0xff
        val blue = argb and 0xff
        return (299 * red + 587 * green + 114 * blue + 500) / 1_000
    }
}
