package com.luming.linuxruntime

import android.content.Context
import android.os.Build
import android.util.Log
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.zip.GZIPInputStream

class LinuxRuntimeInstaller(private val context: Context) {
    private val runtimeBase = File(context.filesDir, "runtime")
    private val activeDir = File(runtimeBase, VERSION_DIRECTORY)
    private val stagingDir = File(runtimeBase, "staging-$VERSION_DIRECTORY")
    private val rollbackDir = File(runtimeBase, "rollback-$VERSION_DIRECTORY")

    @Synchronized
    fun status(): RuntimeResult {
        if (!activeDir.isDirectory) return RuntimeResult(false, "missing")
        val verification = verifyInstalledArtifacts(activeDir)
        if (!verification.success) return verification
        return healthCheck(activeDir)
    }

    @Synchronized
    fun install(): RuntimeResult {
        status().takeIf { it.success }?.let { return it }
        runtimeBase.mkdirs()
        stagingDir.deleteRecursivelyInside(runtimeBase)
        stagingDir.mkdirs()
        val architecture = supportedArchitecture() ?: return RuntimeResult(false, "abi_unsupported")
        return try {
            stageAssets(architecture, stagingDir)
            verifyInstalledArtifacts(stagingDir).takeIf { !it.success }?.let { failure ->
                stagingDir.deleteRecursivelyInside(runtimeBase)
                return failure
            }
            extractRootfs(stagingDir).takeIf { !it.success }?.let { failure ->
                stagingDir.deleteRecursivelyInside(runtimeBase)
                return failure
            }
            makeExecutablesReady(stagingDir)
            healthCheck(stagingDir).takeIf { !it.success }?.let { failure ->
                stagingDir.deleteRecursivelyInside(runtimeBase)
                return failure
            }

            rollbackDir.deleteRecursivelyInside(runtimeBase)
            if (activeDir.exists() && !activeDir.renameTo(rollbackDir)) {
                stagingDir.deleteRecursivelyInside(runtimeBase)
                return RuntimeResult(false, "rollback_prepare_failed")
            }
            if (!stagingDir.renameTo(activeDir)) {
                rollbackDir.renameTo(activeDir)
                return RuntimeResult(false, "atomic_activate_failed")
            }
            val activated = healthCheck(activeDir)
            if (!activated.success) {
                activeDir.deleteRecursivelyInside(runtimeBase)
                rollbackDir.renameTo(activeDir)
                return RuntimeResult(false, "rollback_after_health_failure")
            }
            rollbackDir.deleteRecursivelyInside(runtimeBase)
            activated
        } catch (error: Exception) {
            stagingDir.deleteRecursivelyInside(runtimeBase)
            Log.e(TAG, "Linux runtime installation failed", error)
            RuntimeResult(
                success = false,
                code = "install_failed",
                output = error.javaClass.simpleName + ":" + (error.message ?: "unknown")
            )
        }
    }

    fun activeRuntimeDirectory(): File? = status().takeIf { it.success }?.let { activeDir }

    private fun stageAssets(architecture: String, destination: File) {
        val binDir = File(destination, "bin").apply { mkdirs() }
        val libDir = File(destination, "lib").apply { mkdirs() }
        val tmpDir = File(destination, "tmp").apply { mkdirs() }
        require(tmpDir.isDirectory)
        copyAsset("runtime/$architecture/proot", File(binDir, "proot"))
        copyAsset("runtime/$architecture/loader", File(binDir, "loader"))
        copyAsset("runtime/$architecture/libandroid-shmem.so", File(libDir, "libandroid-shmem.so"))
        copyAsset("runtime/$architecture/libtalloc.so.2", File(libDir, "libtalloc.so.2"))
        // AAPT treats .gz as a special single-file resource and strips the suffix.
        // Store the verified gzip stream as .tgz, then restore its fixed runtime name.
        copyAsset("runtime/$architecture/rootfs.tgz", File(destination, "rootfs.tar.gz"))
        copyAsset("runtime/$architecture/manifest.json", File(destination, "manifest.json"))
    }

    private fun verifyInstalledArtifacts(directory: File): RuntimeResult {
        val manifestFile = File(directory, "manifest.json")
        if (!manifestFile.isFile) return RuntimeResult(false, "manifest_missing")
        val manifest = runCatching { JSONObject(manifestFile.readText()) }
            .getOrElse { return RuntimeResult(false, "manifest_invalid") }
        val files = manifest.optJSONObject("files") ?: return RuntimeResult(false, "manifest_invalid")
        val required = mapOf(
            "proot" to File(directory, "bin/proot"),
            "loader" to File(directory, "bin/loader"),
            "libandroid-shmem.so" to File(directory, "lib/libandroid-shmem.so"),
            "libtalloc.so.2" to File(directory, "lib/libtalloc.so.2"),
            "rootfs.tar.gz" to File(directory, "rootfs.tar.gz")
        )
        for ((name, file) in required) {
            if (!file.isFile) return RuntimeResult(false, "artifact_missing")
            val expected = files.optString(name)
            if (expected.length != 64 || sha256(file) != expected) {
                return RuntimeResult(false, "hash_mismatch")
            }
        }
        val sbom = context.assets.open("runtime-sbom.spdx.json").bufferedReader().use { it.readText() }
        if (!sbom.contains("SPDX-2.3") || !sbom.contains("5.1.107.89") || !sbom.contains("3.22.5")) {
            return RuntimeResult(false, "sbom_invalid")
        }
        return RuntimeResult(true, "artifacts_verified")
    }

    private fun extractRootfs(directory: File): RuntimeResult {
        val rootfs = File(directory, "rootfs").apply { mkdirs() }
        val tarFile = File(directory, "rootfs.tar")
        return try {
            GZIPInputStream(FileInputStream(File(directory, "rootfs.tar.gz"))).use { input ->
                FileOutputStream(tarFile).use { output -> input.copyTo(output) }
            }
            val result = runFixedProcess(
                listOf(
                    "/system/bin/toybox",
                    "tar",
                    "-xf",
                    tarFile.absolutePath,
                    "-C",
                    rootfs.absolutePath
                ),
                timeoutMs = 30_000
            )
            val releaseMatches = File(rootfs, "etc/alpine-release").run {
                isFile && readText().trim() == ALPINE_VERSION
            }
            if ((result.success || ownershipWarningsOnly(result.output)) && releaseMatches) {
                RuntimeResult(true, "rootfs_extracted")
            } else {
                RuntimeResult(false, "rootfs_extract_failed", result.output)
            }
        } catch (error: Exception) {
            RuntimeResult(false, "rootfs_decompress_failed", error.javaClass.simpleName)
        } finally {
            tarFile.delete()
        }
    }

    private fun ownershipWarningsOnly(output: String): Boolean {
        val lines = output.lineSequence().filter { it.isNotBlank() }.toList()
        return lines.isNotEmpty() && lines.all { line -> OWNERSHIP_WARNING.matches(line) }
    }

    private fun makeExecutablesReady(directory: File) {
        require(File(directory, "bin/proot").setExecutable(true, true))
        require(File(directory, "bin/loader").setExecutable(true, true))
    }

    private fun healthCheck(directory: File): RuntimeResult {
        val result = runProot(
            directory = directory,
            executable = "/bin/cat",
            arguments = listOf("/etc/alpine-release"),
            input = "",
            timeoutMs = 10_000
        )
        return if (result.success && result.output.trim() == ALPINE_VERSION) {
            RuntimeResult(true, "ready", ALPINE_VERSION, result.durationMs)
        } else {
            RuntimeResult(false, "health_check_failed", result.output, result.durationMs)
        }
    }

    internal fun runProot(
        directory: File,
        executable: String,
        arguments: List<String>,
        input: String,
        timeoutMs: Long
    ): RuntimeResult {
        val proot = File(directory, "bin/proot")
        val rootfs = File(directory, "rootfs")
        val process = ProcessBuilder(
            listOf(
                proot.absolutePath,
                "-0",
                "-r",
                rootfs.absolutePath,
                "-w",
                "/",
                executable
            ) + arguments
        ).redirectErrorStream(true)
        val environment = process.environment()
        environment.clear()
        environment["HOME"] = "/root"
        environment["PATH"] = "/usr/bin:/bin"
        environment["LANG"] = "C.UTF-8"
        environment["LD_LIBRARY_PATH"] = File(directory, "lib").absolutePath
        environment["PROOT_LOADER"] = File(directory, "bin/loader").absolutePath
        environment["PROOT_TMP_DIR"] = File(directory, "tmp").absolutePath
        environment["PROOT_NO_SECCOMP"] = "1"
        environment["PROOT_DONT_POLLUTE_ROOTFS"] = "1"
        val startedAt = System.currentTimeMillis()
        val child = process.start()
        child.outputStream.bufferedWriter(Charsets.UTF_8).use { writer -> writer.write(input) }
        val capture = captureOutput(child)
        if (!waitForProcess(child, timeoutMs)) {
            child.destroy()
            capture.thread.join(1_000)
            return RuntimeResult(false, "timed_out", durationMs = System.currentTimeMillis() - startedAt)
        }
        capture.thread.join(1_000)
        return RuntimeResult(
            success = child.exitValue() == 0,
            code = if (child.exitValue() == 0) "completed" else "process_failed",
            output = capture.output[0],
            durationMs = System.currentTimeMillis() - startedAt
        )
    }

    private fun runFixedProcess(arguments: List<String>, timeoutMs: Long): RuntimeResult {
        val startedAt = System.currentTimeMillis()
        val child = ProcessBuilder(arguments).redirectErrorStream(true).start()
        val capture = captureOutput(child)
        if (!waitForProcess(child, timeoutMs)) {
            child.destroy()
            capture.thread.join(1_000)
            return RuntimeResult(false, "timed_out", durationMs = System.currentTimeMillis() - startedAt)
        }
        capture.thread.join(1_000)
        return RuntimeResult(
            child.exitValue() == 0,
            if (child.exitValue() == 0) "completed" else "process_failed",
            capture.output[0],
            System.currentTimeMillis() - startedAt
        )
    }

    private data class OutputCapture(val thread: Thread, val output: Array<String>)

    private fun captureOutput(child: Process): OutputCapture {
        val output = arrayOf("")
        val thread = Thread({
            output[0] = runCatching {
                child.inputStream.bufferedReader(Charsets.UTF_8).use {
                    it.readTextLimited(MAX_OUTPUT_BYTES)
                }
            }.getOrDefault("")
        }, "luming-linux-output")
        thread.isDaemon = true
        thread.start()
        return OutputCapture(thread, output)
    }

    /** Process.waitFor(timeout) and Process.isAlive both require API 26. */
    private fun waitForProcess(child: Process, timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            try {
                child.exitValue()
                return true
            } catch (_: IllegalThreadStateException) {
                Thread.sleep(minOf(20L, maxOf(1L, deadline - System.currentTimeMillis())))
            }
        }
        return try {
            child.exitValue()
            true
        } catch (_: IllegalThreadStateException) {
            false
        }
    }

    private fun copyAsset(path: String, destination: File) {
        destination.parentFile?.mkdirs()
        context.assets.open(path).use { input ->
            FileOutputStream(destination).use { output -> input.copyTo(output) }
        }
    }

    private fun supportedArchitecture(): String? {
        return Build.SUPPORTED_ABIS.firstNotNullOfOrNull { abi ->
            when (abi) {
                "arm64-v8a" -> "arm64-v8a"
                "x86_64" -> "x86_64"
                else -> null
            }
        }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }
    }

    private fun File.deleteRecursivelyInside(parent: File) {
        val canonicalParent = parent.canonicalFile
        val canonicalTarget = canonicalFile
        val parentPrefix = canonicalParent.path.trimEnd(File.separatorChar) + File.separator
        if (canonicalTarget == canonicalParent || !canonicalTarget.path.startsWith(parentPrefix)) {
            throw IllegalStateException("unsafe_runtime_path")
        }
        if (exists()) deleteRecursively()
    }

    private fun java.io.Reader.readTextLimited(limit: Int): String {
        val result = StringBuilder()
        val buffer = CharArray(4096)
        while (result.length < limit) {
            val read = read(buffer, 0, minOf(buffer.size, limit - result.length))
            if (read < 0) break
            result.append(buffer, 0, read)
        }
        return result.toString()
    }

    companion object {
        private const val TAG = "LumingLinuxRuntime"
        const val RUNTIME_VERSION = "proot-5.1.107.89+alpine-3.22.5"
        private const val VERSION_DIRECTORY = "v1"
        private const val ALPINE_VERSION = "3.22.5"
        private const val MAX_OUTPUT_BYTES = 512 * 1024
        private val OWNERSHIP_WARNING = Regex(
            "^tar: chown [0-9]+:[0-9]+ '.+': Operation not permitted$"
        )
    }
}
