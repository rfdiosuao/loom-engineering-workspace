package com.apk.claw.android.rpa;

import java.io.File;
import java.io.RandomAccessFile;
import java.nio.channels.FileLock;

public final class Task6TestInterop {
    private Task6TestInterop() {}

    public static ActionDispatcher nullDispatcher() {
        return action -> null;
    }

    public static OutcomeVerifier nullVerifier() {
        return (action, dispatchedAt) -> null;
    }

    public static void main(String[] args) throws Exception {
        File lockFile = new File(args[0]);
        File readyFile = new File(args[1]);
        File releaseFile = new File(args[2]);
        File parent = lockFile.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
            throw new IllegalStateException("claim lock parent unavailable");
        }
        try (RandomAccessFile handle = new RandomAccessFile(lockFile, "rw");
             FileLock ignored = handle.getChannel().lock()) {
            if (!readyFile.createNewFile()) throw new IllegalStateException("ready signal unavailable");
            long deadline = System.currentTimeMillis() + 30_000L;
            while (!releaseFile.exists() && System.currentTimeMillis() < deadline) {
                Thread.sleep(10L);
            }
            if (!releaseFile.exists()) throw new IllegalStateException("release signal timeout");
        }
    }
}
