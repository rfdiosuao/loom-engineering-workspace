package com.apk.claw.android.rpa

class LumaPlane private constructor(
    val width: Int,
    val height: Int,
    private val storage: IntArray,
    @Suppress("UNUSED_PARAMETER") owned: Boolean
) {
    constructor(width: Int, height: Int, pixels: IntArray) : this(
        width,
        height,
        copyValidated(width, height, pixels),
        false
    )

    init {
        validateShape(width, height, storage.size)
        require(storage.all { it in MIN_LUMA..MAX_LUMA }) { "luma_value_invalid" }
    }

    operator fun get(x: Int, y: Int): Int {
        if (x !in 0 until width || y !in 0 until height) {
            throw IndexOutOfBoundsException("luma_coordinate_out_of_bounds")
        }
        return storage[y * width + x]
    }

    fun toIntArray(): IntArray = storage.copyOf()

    internal fun pixelAt(index: Int): Int = storage[index]

    companion object {
        const val MIN_LUMA = 0
        const val MAX_LUMA = 255
        const val MAX_PIXELS = 16_777_216L

        private fun validateShape(width: Int, height: Int, sourceSize: Int) {
            require(width > 0 && height > 0) { "luma_dimensions_invalid" }
            val pixelCount = width.toLong() * height.toLong()
            require(pixelCount <= MAX_PIXELS) { "luma_dimensions_too_large" }
            require(pixelCount == sourceSize.toLong()) { "luma_pixel_length_invalid" }
        }

        private fun copyValidated(width: Int, height: Int, pixels: IntArray): IntArray {
            validateShape(width, height, pixels.size)
            return pixels.copyOf()
        }

        internal fun owned(width: Int, height: Int, pixels: IntArray): LumaPlane =
            LumaPlane(width, height, pixels, true)
    }
}
