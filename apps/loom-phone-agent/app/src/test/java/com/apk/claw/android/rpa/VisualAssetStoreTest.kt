package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.TemplateStatus
import com.google.gson.JsonParser
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeNoException
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class VisualAssetStoreTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun write_and_read_use_structured_metadata_and_verify_sha256() {
        val root = temporaryFolder.newFolder("store")
        val store = VisualAssetStore(root)
        val bytes = webp(1, 2, 3, 4)

        val stored = store.writeAsset(
            templateId = "checkout-template",
            revision = 3,
            assetName = "step-01-anchor.webp",
            webpBytes = bytes,
            status = TemplateStatus.ACTIVE,
            retention = VisualAssetRetention.ROUTINE,
            updatedAt = 1_000L
        )

        assertEquals(64, stored.sha256.length)
        assertArrayEquals(bytes, store.readAsset("checkout-template", 3, "step-01-anchor.webp"))
        val manifest = File(root, "assets/checkout-template/r3/asset-manifest.json")
        assertTrue(manifest.readText().contains("\"sha256\""))
        assertTrue(manifest.readText().contains(stored.sha256))
    }

    @Test
    fun changed_checksum_is_refused_before_asset_use() {
        val root = temporaryFolder.newFolder("checksum")
        val store = VisualAssetStore(root)
        store.writeAsset("template", 1, "anchor.webp", webp(1), TemplateStatus.DRAFT)
        File(root, "assets/template/r1/anchor.webp").writeBytes(webp(9, 9, 9))

        assertNull(store.readAsset("template", 1, "anchor.webp"))
    }

    @Test
    fun interrupted_manifest_and_asset_replacements_recover_from_backups() {
        val root = temporaryFolder.newFolder("recovery")
        val store = VisualAssetStore(root)
        val bytes = webp(7, 8)
        store.writeAsset("template", 1, "anchor.webp", bytes, TemplateStatus.DRAFT)
        val revision = File(root, "assets/template/r1")

        val manifest = File(revision, "asset-manifest.json")
        assertTrue(manifest.renameTo(File(revision, "asset-manifest.json.bak-test")))
        assertArrayEquals(bytes, store.readAsset("template", 1, "anchor.webp"))
        assertTrue(manifest.exists())

        val asset = File(revision, "anchor.webp")
        asset.copyTo(File(revision, "anchor.webp.bak-test"), overwrite = true)
        asset.writeBytes(webp(99))
        assertArrayEquals(bytes, store.readAsset("template", 1, "anchor.webp"))
        assertArrayEquals(bytes, asset.readBytes())
    }

    @Test
    fun traversal_and_oversized_inputs_are_rejected() {
        val store = VisualAssetStore(temporaryFolder.newFolder("paths"))

        assertThrows(IllegalArgumentException::class.java) {
            store.writeAsset("../outside", 1, "anchor.webp", webp(1), TemplateStatus.DRAFT)
        }
        assertThrows(IllegalArgumentException::class.java) {
            store.writeAsset("template", 1, "../anchor.webp", webp(1), TemplateStatus.DRAFT)
        }
        assertThrows(IllegalArgumentException::class.java) {
            store.writeAsset(
                "template",
                1,
                "anchor.webp",
                ByteArray(VisualAssetStore.MAX_ASSET_BYTES + 1),
                TemplateStatus.DRAFT
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            store.writeAsset("template", 1, "prefix.webp", riffPrefixOnly(), TemplateStatus.DRAFT)
        }
        assertThrows(IllegalArgumentException::class.java) {
            store.writeAsset("template", 1, "overrun.webp", corruptChunkOverrun(), TemplateStatus.DRAFT)
        }
    }

    @Test
    fun concurrent_multi_instance_writers_preserve_both_assets_without_exceptions() {
        val root = temporaryFolder.newFolder("concurrent")
        val slowRename: (File, File) -> Boolean = { source, destination ->
            Thread.sleep(2L)
            source.renameTo(destination)
        }
        val stores = listOf(VisualAssetStore(root, slowRename), VisualAssetStore(root, slowRename))
        val executor = Executors.newFixedThreadPool(8)
        repeat(50) { round ->
            val start = CountDownLatch(1)
            val futures = (0 until 8).map { index ->
                executor.submit {
                    start.await()
                    val name = if (index and 1 == 0) "first.webp" else "second.webp"
                    stores[index % stores.size].writeAsset(
                        "shared",
                        1,
                        name,
                        webp(round, index),
                        TemplateStatus.ACTIVE,
                        updatedAt = round.toLong()
                    )
                }
            }
            start.countDown()
            futures.forEach { it.get(30, TimeUnit.SECONDS) }
            assertNotNull(stores[0].readAsset("shared", 1, "first.webp"))
            assertNotNull(stores[1].readAsset("shared", 1, "second.webp"))
        }
        executor.shutdown()
        assertTrue(executor.awaitTermination(30, TimeUnit.SECONDS))
    }

    @Test
    fun deterministic_file_alias_is_rejected_without_overwriting_active_target_for_50_rounds() {
        val root = temporaryFolder.newFolder("file-alias")
        val writer = VisualAssetStore(root)
        val activeBytes = webp(91)
        writer.writeAsset("template", 1, "victim.webp", activeBytes, TemplateStatus.ACTIVE)
        val revision = File(root, "assets/template/r1")
        val victim = File(revision, "victim.webp").canonicalFile
        val aliasStore = VisualAssetStore(
            rootDirectory = root,
            canonicalize = { file ->
                if (file.name.startsWith("alias-") && file.name.endsWith(".webp")) victim else file.canonicalFile
            }
        )

        repeat(50) { round ->
            val alias = File(revision, "alias-$round.webp")
            alias.writeBytes(webp(round))
            val error = assertThrows(IllegalArgumentException::class.java) {
                aliasStore.writeAsset("template", 1, alias.name, webp(round + 1), TemplateStatus.DRAFT)
            }
            assertEquals("asset_path_alias", error.message)
            assertArrayEquals(activeBytes, writer.readAsset("template", 1, "victim.webp"))
            assertTrue(alias.delete())
        }
    }

    @Test
    fun symlink_file_alias_is_rejected_without_overwriting_active_target_when_links_are_permitted() {
        val root = temporaryFolder.newFolder("file-symlink")
        val store = VisualAssetStore(root)
        val activeBytes = webp(92)
        store.writeAsset("template", 1, "victim.webp", activeBytes, TemplateStatus.ACTIVE)
        val revision = File(root, "assets/template/r1")
        val victim = File(revision, "victim.webp")
        val alias = File(revision, "alias.webp")
        try {
            Files.createSymbolicLink(alias.toPath(), victim.toPath())
        } catch (error: Exception) {
            assumeNoException(error)
        }

        val error = assertThrows(IllegalArgumentException::class.java) {
            store.writeAsset("template", 1, "alias.webp", webp(93), TemplateStatus.DRAFT)
        }

        assertEquals("asset_path_alias", error.message)
        assertArrayEquals(activeBytes, store.readAsset("template", 1, "victim.webp"))
    }

    @Test
    fun every_transaction_file_surface_rejects_a_canonical_alias_before_io() {
        listOf(
            "asset" to { file: File -> file.name == "alias.webp" },
            "manifest" to { file: File -> file.name == "asset-manifest.json" },
            "staging" to { file: File -> file.name.contains(".tmp-") },
            "backup" to { file: File -> file.name.contains(".bak-") },
            "lock" to { file: File -> file.name == ".visual-assets.lock" }
        ).forEach { (surface, matches) ->
            val root = temporaryFolder.newFolder("surface-$surface")
            val writer = VisualAssetStore(root)
            val activeBytes = webp(surface.length)
            writer.writeAsset("template", 1, "victim.webp", activeBytes, TemplateStatus.ACTIVE)
            val victim = File(root, "assets/template/r1/victim.webp").canonicalFile
            val store = VisualAssetStore(
                rootDirectory = root,
                canonicalize = { file -> if (matches(file.absoluteFile)) victim else file.canonicalFile }
            )

            val assetName = if (surface == "asset") "alias.webp" else "victim.webp"
            val error = assertThrows(IllegalArgumentException::class.java) {
                store.writeAsset("template", 1, assetName, webp(100 + surface.length), TemplateStatus.ACTIVE)
            }

            assertEquals("$surface did not fail as an alias", "asset_path_alias", error.message)
            assertArrayEquals("$surface changed its canonical target", activeBytes, victim.readBytes())
        }
    }

    @Test
    fun recovery_uses_highest_internal_generation_when_timestamps_are_equal() {
        val root = temporaryFolder.newFolder("manifest-generation")
        val store = VisualAssetStore(root)
        val timestamp = 44L
        val first = webp(1)
        val second = webp(2)
        store.writeAsset("template", 1, "a.webp", first, TemplateStatus.ACTIVE, updatedAt = timestamp)
        val revision = File(root, "assets/template/r1")
        val manifest = File(revision, "asset-manifest.json")
        val stale = withGeneration(manifest.readText(), 1L)
        store.writeAsset("template", 1, "b.webp", second, TemplateStatus.ACTIVE, updatedAt = timestamp)
        val current = withGeneration(manifest.readText(), 2L)
        assertTrue(manifest.delete())
        File(revision, "asset-manifest.json.bak-a-stale").writeText(stale)
        File(revision, "asset-manifest.json.bak-z-current").writeText(current)

        assertArrayEquals(second, store.readAsset("template", 1, "b.webp"))
        assertArrayEquals(first, store.readAsset("template", 1, "a.webp"))
        assertTrue(revision.listFiles()!!.none { it.name.startsWith("asset-manifest.json.bak-") })
    }

    @Test
    fun webp_rejects_invalid_dimensions_duplicate_rasters_and_incoherent_extended_canvas() {
        val store = VisualAssetStore(temporaryFolder.newFolder("strict-webp"))
        val validVp8 = riff(chunk("VP8 ", vp8Payload(width = 2, height = 3)))
        val validExtendedLossless = riff(
            chunk("VP8X", vp8xPayload(2, 3)),
            chunk("VP8L", vp8lPayload(2, 3))
        )
        store.writeAsset("template", 1, "valid-vp8.webp", validVp8, TemplateStatus.DRAFT)
        store.writeAsset("template", 1, "valid-vp8x.webp", validExtendedLossless, TemplateStatus.DRAFT)
        assertArrayEquals(validVp8, store.readAsset("template", 1, "valid-vp8.webp"))
        assertArrayEquals(validExtendedLossless, store.readAsset("template", 1, "valid-vp8x.webp"))

        val invalidVp8lVersion = vp8lPayload(1, 1).apply { this[4] = 0x20 }
        val invalidVp8xReservedFlag = vp8xPayload(1, 1).apply { this[0] = 0x80.toByte() }
        val invalidVp8xReservedByte = vp8xPayload(1, 1).apply { this[1] = 1 }
        val malformed = listOf(
            riff(chunk("VP8 ", vp8Payload(width = 0, height = 1))),
            riff(chunk("VP8 ", vp8Payload(width = 1, height = 1, keyFrame = false))),
            riff(chunk("VP8L", invalidVp8lVersion)),
            riff(chunk("VP8X", invalidVp8xReservedFlag), chunk("VP8L", vp8lPayload(1, 1))),
            riff(chunk("VP8X", invalidVp8xReservedByte), chunk("VP8L", vp8lPayload(1, 1))),
            riff(chunk("VP8L", vp8lPayload(1, 1)), chunk("VP8L", vp8lPayload(1, 1))),
            riff(chunk("VP8X", vp8xPayload(1, 1)), chunk("VP8X", vp8xPayload(1, 1)), chunk("VP8L", vp8lPayload(1, 1))),
            riff(chunk("VP8X", vp8xPayload(2, 2)), chunk("VP8L", vp8lPayload(1, 1))),
            riff(chunk("VP8L", vp8lPayload(16_384, 16_384)))
        )

        malformed.forEachIndexed { index, bytes ->
            assertThrows(IllegalArgumentException::class.java) {
                store.writeAsset("template", 1, "bad-$index.webp", bytes, TemplateStatus.DRAFT)
            }
        }
    }

    @Test
    fun pruning_keeps_active_and_newest_diagnostic_revision() {
        val root = temporaryFolder.newFolder("prune")
        val store = VisualAssetStore(root)
        val day = 24L * 60L * 60L * 1_000L
        val now = 50L * day
        writeRevision(store, "active", 1, TemplateStatus.ACTIVE, VisualAssetRetention.ROUTINE, now - 40L * day)
        writeRevision(store, "broken", 1, TemplateStatus.DEGRADED, VisualAssetRetention.DIAGNOSTIC, now - 40L * day)
        writeRevision(store, "broken", 2, TemplateStatus.DEGRADED, VisualAssetRetention.DIAGNOSTIC, now - 35L * day)
        writeRevision(store, "draft", 1, TemplateStatus.DRAFT, VisualAssetRetention.ROUTINE, now - 8L * day)
        writeRevision(store, "fresh", 1, TemplateStatus.DRAFT, VisualAssetRetention.ROUTINE, now - day)

        val result = store.prune(maxBytes = 128L * 1024L * 1024L, now = now)

        assertTrue(result.capMet)
        assertTrue(result.retained.any { it.status == TemplateStatus.ACTIVE })
        assertTrue(result.retained.any { it.templateId == "broken" && it.revision == 2 && it.isLatestDiagnostic })
        assertTrue(result.retained.any { it.templateId == "fresh" })
        assertTrue(result.deleted.any { it.templateId == "broken" && it.revision == 1 })
        assertTrue(result.deleted.any { it.templateId == "draft" })
    }

    @Test
    fun impossible_cap_is_reported_and_protected_revisions_are_preserved() {
        val root = temporaryFolder.newFolder("cap")
        val store = VisualAssetStore(root)
        writeRevision(store, "active", 1, TemplateStatus.ACTIVE, VisualAssetRetention.ROUTINE, 1L)
        writeRevision(store, "diagnostic", 4, TemplateStatus.DEGRADED, VisualAssetRetention.DIAGNOSTIC, 2L)

        val result = store.prune(maxBytes = 1L, now = 100L)

        assertFalse(result.capMet)
        assertEquals("protected_assets_exceed_cap", result.reason)
        assertEquals(2, result.retained.size)
        assertNotNull(store.readAsset("active", 1, "anchor.webp"))
        assertNotNull(store.readAsset("diagnostic", 4, "anchor.webp"))
    }

    @Test
    fun prune_recomputes_revision_bytes_after_manifest_recovery_removes_duplicate_backup() {
        val root = temporaryFolder.newFolder("post-recovery-accounting")
        val store = VisualAssetStore(root)
        val asset = webp()
        assertEquals(26, asset.size)
        store.writeAsset("t", 1, "a.webp", asset, TemplateStatus.DRAFT, updatedAt = 0L)
        val revision = File(root, "assets/t/r1")
        val manifest = File(revision, "asset-manifest.json")
        val originalManifest = manifest.readBytes()
        assertTrue("manifest was ${originalManifest.size} bytes", originalManifest.size <= 256)
        manifest.writeBytes(originalManifest + ByteArray(256 - originalManifest.size) { ' '.code.toByte() })
        File(revision, "asset-manifest.json.bak-crash").writeBytes(manifest.readBytes())

        val result = store.prune(maxBytes = 282L, now = 0L)

        assertTrue(result.capMet)
        assertTrue(result.deleted.isEmpty())
        assertEquals(282L, result.bytesBefore)
        assertEquals(282L, result.bytesAfter)
        assertEquals(282L, result.retained.single().bytes)
        assertArrayEquals(asset, store.readAsset("t", 1, "a.webp"))
    }

    @Test
    fun deterministic_canonical_alias_is_quarantined_and_cannot_delete_active_target() {
        val root = temporaryFolder.newFolder("canonical-alias")
        val writer = VisualAssetStore(root)
        val activeBytes = webp(1)
        writer.writeAsset("template", 1, "anchor.webp", activeBytes, TemplateStatus.ACTIVE, updatedAt = 1L)
        val revisionOne = File(root, "assets/template/r1").canonicalFile
        val lexicalAlias = File(root, "assets/template/r2").apply { mkdirs() }.absoluteFile
        File(lexicalAlias, "orphan.webp").writeBytes(webp(2))
        val aliasStore = VisualAssetStore(
            rootDirectory = root,
            canonicalize = { file ->
                if (file.absoluteFile.path.equals(lexicalAlias.path, ignoreCase = true)) revisionOne else file.canonicalFile
            }
        )

        val result = aliasStore.prune(maxBytes = 0L, now = 100L * DAY_MS)

        assertArrayEquals(activeBytes, aliasStore.readAsset("template", 1, "anchor.webp"))
        assertTrue(lexicalAlias.exists())
        assertTrue(result.quarantineReasons.toString(), result.quarantineReasons.contains("canonical_alias"))
        assertTrue(result.retained.any { it.revision == 2 && it.quarantineReason == "canonical_alias" })
    }

    @Test
    fun symlink_revision_alias_cannot_delete_active_target_when_links_are_permitted() {
        val root = temporaryFolder.newFolder("symlink-alias")
        val store = VisualAssetStore(root)
        val activeBytes = webp(7)
        store.writeAsset("template", 1, "anchor.webp", activeBytes, TemplateStatus.ACTIVE, updatedAt = 1L)
        val revisionOne = File(root, "assets/template/r1")
        val alias = File(root, "assets/template/r2")
        try {
            Files.createSymbolicLink(alias.toPath(), revisionOne.toPath())
        } catch (error: Exception) {
            assumeNoException(error)
        }

        val result = store.prune(maxBytes = 0L, now = 100L * DAY_MS)

        assertArrayEquals(activeBytes, store.readAsset("template", 1, "anchor.webp"))
        assertTrue(
            result.quarantineReasons.toString(),
            result.quarantineReasons.any { it == "canonical_alias" || it == "manifest_unreadable" }
        )
    }

    @Test
    fun unreadable_formerly_active_manifest_is_quarantined_never_pruned() {
        val root = temporaryFolder.newFolder("manifest-quarantine")
        val store = VisualAssetStore(root)
        store.writeAsset("template", 1, "anchor.webp", webp(3), TemplateStatus.ACTIVE, updatedAt = 1L)
        val revision = File(root, "assets/template/r1")
        File(revision, "asset-manifest.json").writeText("{not-json")

        val result = store.prune(maxBytes = 0L, now = 100L * DAY_MS)

        assertTrue(revision.exists())
        assertTrue(result.quarantineReasons.contains("manifest_unreadable"))
        assertTrue(result.retained.single().quarantined)
        assertEquals("manifest_unreadable", result.retained.single().quarantineReason)
    }

    @Test
    fun high_fanout_fails_closed_before_sorting_or_recursive_deletion() {
        val root = temporaryFolder.newFolder("fanout")
        val revision = File(root, "assets/template/r1").apply { mkdirs() }
        repeat(257) { index ->
            File(revision, "file-$index.bin").apply {
                writeText("x")
                setLastModified(1L)
            }
        }

        val result = VisualAssetStore(root).prune(maxBytes = 0L, now = 100L * DAY_MS)

        assertFalse(result.capMet)
        assertEquals("scan_limit_exceeded", result.reason)
        assertTrue(revision.exists())
        assertEquals(257, revision.list()?.size)
    }

    private fun writeRevision(
        store: VisualAssetStore,
        templateId: String,
        revision: Int,
        status: TemplateStatus,
        retention: VisualAssetRetention,
        updatedAt: Long
    ) {
        store.writeAsset(templateId, revision, "anchor.webp", webp(revision), status, retention, updatedAt)
    }

    private fun webp(vararg payload: Int): ByteArray {
        return riff(chunk("VP8L", vp8lPayload(1, 1) + payload.map(Int::toByte)))
    }

    private fun withGeneration(json: String, generation: Long): String =
        JsonParser.parseString(json).asJsonObject.apply { addProperty("generation", generation) }.toString()

    private fun riff(vararg chunks: ByteArray): ByteArray {
        val body = ascii("WEBP") + chunks.fold(ByteArray(0)) { bytes, next -> bytes + next }
        return ascii("RIFF") + littleEndian(body.size) + body
    }

    private fun chunk(type: String, payload: ByteArray): ByteArray {
        val padding = if (payload.size and 1 == 1) byteArrayOf(0) else byteArrayOf()
        return ascii(type) + littleEndian(payload.size) + payload + padding
    }

    private fun vp8Payload(width: Int, height: Int, keyFrame: Boolean = true): ByteArray {
        val frameTag = (1 shl 4) or (1 shl 5) or if (keyFrame) 0 else 1
        return byteArrayOf(
            frameTag.toByte(), 0, 0,
            0x9d.toByte(), 0x01, 0x2a,
            width.toByte(), (width ushr 8).toByte(),
            height.toByte(), (height ushr 8).toByte(),
            0
        )
    }

    private fun vp8lPayload(width: Int, height: Int): ByteArray {
        val bits = (width - 1) or ((height - 1) shl 14)
        return byteArrayOf(0x2f) + littleEndian(bits)
    }

    private fun vp8xPayload(width: Int, height: Int): ByteArray =
        byteArrayOf(0, 0, 0, 0) + littleEndian24(width - 1) + littleEndian24(height - 1)

    private fun riffPrefixOnly(): ByteArray = ascii("RIFF") + littleEndian(4) + ascii("WEBP")

    private fun corruptChunkOverrun(): ByteArray =
        ascii("RIFF") + littleEndian(12) + ascii("WEBP") + ascii("VP8L") + littleEndian(100)

    private fun ascii(value: String): ByteArray = value.map { it.code.toByte() }.toByteArray()

    private fun littleEndian(value: Int): ByteArray = byteArrayOf(
        value.toByte(),
        (value ushr 8).toByte(),
        (value ushr 16).toByte(),
        (value ushr 24).toByte()
    )

    private fun littleEndian24(value: Int): ByteArray = byteArrayOf(
        value.toByte(),
        (value ushr 8).toByte(),
        (value ushr 16).toByte()
    )

    companion object {
        private const val DAY_MS = 24L * 60L * 60L * 1_000L
    }
}
