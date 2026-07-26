package com.apk.claw.android.service;

import android.graphics.Bitmap;

/** Owns one immutable ARGB screenshot copy until detached or closed. */
public final class ScreenshotFrame implements AutoCloseable {
    public static final String SOURCE_FRESH = "fresh";
    public static final String SOURCE_CACHE = "cache";
    public static final String SOURCE_STALE_FALLBACK = "stale_fallback";

    private final String frameId;
    private final String source;
    private final long capturedAt;
    private final long ageMs;
    private final int width;
    private final int height;
    private Bitmap bitmap;

    private ScreenshotFrame(
            String frameId,
            String source,
            Bitmap sourceBitmap,
            long capturedAt,
            long observedAt
    ) {
        if (sourceBitmap == null || sourceBitmap.isRecycled()) {
            throw new IllegalArgumentException("Screenshot bitmap must be live");
        }
        Bitmap copied = sourceBitmap.copy(Bitmap.Config.ARGB_8888, false);
        if (copied == null) {
            throw new IllegalStateException("Unable to copy screenshot bitmap");
        }
        this.frameId = frameId;
        this.source = source;
        this.capturedAt = capturedAt;
        this.ageMs = Math.max(0L, observedAt - capturedAt);
        this.width = copied.getWidth();
        this.height = copied.getHeight();
        this.bitmap = copied;
    }

    public static ScreenshotFrame fresh(
            String frameId,
            Bitmap bitmap,
            long capturedAt,
            long observedAt
    ) {
        return new ScreenshotFrame(frameId, SOURCE_FRESH, bitmap, capturedAt, observedAt);
    }

    public static ScreenshotFrame cached(
            String frameId,
            Bitmap bitmap,
            long capturedAt,
            long observedAt
    ) {
        return new ScreenshotFrame(frameId, SOURCE_CACHE, bitmap, capturedAt, observedAt);
    }

    public static ScreenshotFrame stale(
            String frameId,
            Bitmap bitmap,
            long capturedAt,
            long observedAt
    ) {
        return new ScreenshotFrame(frameId, SOURCE_STALE_FALLBACK, bitmap, capturedAt, observedAt);
    }

    public String getFrameId() {
        return frameId;
    }

    public String getSource() {
        return source;
    }

    public long getCapturedAt() {
        return capturedAt;
    }

    public long getAgeMs() {
        return ageMs;
    }

    public int getWidth() {
        return width;
    }

    public int getHeight() {
        return height;
    }

    public synchronized Bitmap detachBitmap() {
        Bitmap detached = bitmap;
        bitmap = null;
        return detached;
    }

    @Override
    public synchronized void close() {
        if (bitmap != null && !bitmap.isRecycled()) {
            bitmap.recycle();
        }
        bitmap = null;
    }
}
