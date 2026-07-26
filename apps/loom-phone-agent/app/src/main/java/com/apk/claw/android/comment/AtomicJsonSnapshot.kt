package com.apk.claw.android.comment

import java.io.File
import java.io.FileOutputStream

internal data class AtomicSnapshotRead<T>(
    val value: T,
    val recoveredFromBackup: Boolean
)

internal class AtomicJsonSnapshot(
    directory: File,
    baseName: String
) {
    private val root = directory.canonicalFile
    private val primary = File(root, baseName)
    private val backup = File(root, "$baseName.bak")
    private val corrupt = File(root, "$baseName.corrupt")

    fun write(json: String) {
        root.mkdirs()
        writeAtomically(primary, json)
        writeAtomically(backup, json)
    }

    fun <T> read(parse: (String) -> T): AtomicSnapshotRead<T>? {
        if (!primary.exists() && !backup.exists()) return null
        if (primary.exists()) {
            try {
                return AtomicSnapshotRead(parse(primary.readText(Charsets.UTF_8)), false)
            } catch (primaryError: Exception) {
                if (!backup.exists()) throw primaryError
                val recovered = parse(backup.readText(Charsets.UTF_8))
                preserveCorruptPrimary()
                writeAtomically(primary, backup.readText(Charsets.UTF_8))
                return AtomicSnapshotRead(recovered, true)
            }
        }
        val recovered = parse(backup.readText(Charsets.UTF_8))
        writeAtomically(primary, backup.readText(Charsets.UTF_8))
        return AtomicSnapshotRead(recovered, true)
    }

    private fun preserveCorruptPrimary() {
        if (!primary.exists()) return
        if (corrupt.exists()) check(corrupt.delete())
        moveReplacing(primary, corrupt)
    }

    private fun writeAtomically(target: File, json: String) {
        val pending = File(root, "${target.name}.tmp")
        FileOutputStream(pending).use { output ->
            output.write(json.toByteArray(Charsets.UTF_8))
            output.fd.sync()
        }
        moveReplacing(pending, target)
    }

    private fun moveReplacing(source: File, destination: File) {
        val displaced = File(root, "${destination.name}.replace")
        if (displaced.exists()) {
            check(displaced.delete()) { "Unable to remove stale snapshot replacement: $displaced" }
        }
        if (destination.exists()) {
            check(destination.renameTo(displaced)) {
                "Unable to preserve existing snapshot before replacement: $destination"
            }
        }
        if (!source.renameTo(destination)) {
            if (displaced.exists()) {
                displaced.renameTo(destination)
            }
            error("Unable to replace snapshot: $destination")
        }
        if (displaced.exists()) {
            check(displaced.delete()) { "Unable to remove replaced snapshot: $displaced" }
        }
    }
}
