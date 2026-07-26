package com.apk.claw.android.rpa

import android.system.Os
import android.system.OsConstants
import com.apk.claw.android.workflow.TemplateStatus
import com.google.gson.Gson
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.locks.ReentrantLock

enum class VisualAssetRetention { ROUTINE, DIAGNOSTIC }

data class StoredVisualAsset(
    val templateId: String,
    val revision: Int,
    val assetName: String,
    val sha256: String,
    val size: Long
)

data class VisualAssetRevision(
    val templateId: String,
    val revision: Int,
    val status: TemplateStatus,
    val retention: VisualAssetRetention,
    val updatedAt: Long,
    val bytes: Long,
    val isLatestDiagnostic: Boolean = false,
    val quarantined: Boolean = false,
    val quarantineReason: String = ""
)

data class VisualAssetPruneResult(
    val retained: List<VisualAssetRevision>,
    val deleted: List<VisualAssetRevision>,
    val bytesBefore: Long,
    val bytesAfter: Long,
    val capMet: Boolean,
    val reason: String = "",
    val quarantineReasons: Set<String> = emptySet()
)

class VisualAssetStore(
    rootDirectory: File,
    private val rename: (File, File) -> Boolean = { source, destination -> source.renameTo(destination) },
    private val canonicalize: (File) -> File = { file -> file.canonicalFile }
) {
    private val root = canonicalize(rootDirectory).absoluteFile
    private val assetsRoot = canonicalize(File(root, ASSETS_DIRECTORY)).absoluteFile
    private val lockFile = File(root, LOCK_FILE_NAME).absoluteFile
    private val gson = Gson()
    private val processLock = processLockFor(root.path)

    init {
        require(isSameOrDescendant(assetsRoot, root)) { "asset_root_invalid" }
    }

    @JvmOverloads
    fun writeAsset(
        templateId: String,
        revision: Int,
        assetName: String,
        webpBytes: ByteArray,
        status: TemplateStatus,
        retention: VisualAssetRetention = retentionFor(status),
        updatedAt: Long = System.currentTimeMillis()
    ): StoredVisualAsset = withStoreLock {
        validateTemplateId(templateId)
        validateRevision(revision)
        validateAssetName(assetName)
        require(updatedAt >= 0L) { "asset_updated_at_invalid" }
        require(webpBytes.size in MIN_WEBP_BYTES..MAX_ASSET_BYTES) { "asset_size_invalid" }
        require(isStructuredWebp(webpBytes)) { "asset_format_invalid" }
        writeAssetLocked(templateId, revision, assetName, webpBytes, status, retention, updatedAt)
    }

    fun readAsset(templateId: String, revision: Int, assetName: String): ByteArray? = withStoreLock {
        validateTemplateId(templateId)
        validateRevision(revision)
        validateAssetName(assetName)
        val directory = revisionDirectory(templateId, revision, create = false)
        if (!directory.isDirectory) return@withStoreLock null
        val manifest = when (val state = loadManifest(directory, templateId, revision)) {
            is ManifestState.Valid -> state.manifest
            ManifestState.Missing, is ManifestState.Corrupt -> return@withStoreLock null
        }
        val entry = manifest.assets.singleOrNull { it.name == assetName } ?: return@withStoreLock null
        readVerifiedAssetWithRecovery(directory, entry)
    }

    @JvmOverloads
    fun prune(maxBytes: Long = DEFAULT_MAX_BYTES, now: Long = System.currentTimeMillis()): VisualAssetPruneResult =
        withStoreLock {
            require(maxBytes >= 0L) { "asset_cap_invalid" }
            require(now >= 0L) { "asset_prune_time_invalid" }
            pruneLocked(maxBytes, now)
        }

    private fun writeAssetLocked(
        templateId: String,
        revision: Int,
        assetName: String,
        webpBytes: ByteArray,
        status: TemplateStatus,
        retention: VisualAssetRetention,
        updatedAt: Long
    ): StoredVisualAsset {
        val directory = revisionDirectory(templateId, revision, create = true)
        val existing = when (val state = loadManifest(directory, templateId, revision)) {
            is ManifestState.Valid -> state.manifest
            ManifestState.Missing -> null
            is ManifestState.Corrupt -> throw IllegalStateException("asset_manifest_invalid:${state.reason}")
        }
        val checksum = sha256(webpBytes)
        val entries = existing?.assets.orEmpty().associateBy { it.name }.toMutableMap()
        entries[assetName] = AssetEntry(assetName, checksum, webpBytes.size.toLong())
        require(entries.size <= MAX_ASSETS_PER_REVISION) { "too_many_revision_assets" }
        val generation = existing?.generation?.let {
            require(it < Long.MAX_VALUE) { "asset_manifest_generation_exhausted" }
            it + 1L
        } ?: 1L
        val manifest = AssetManifest(
            templateId,
            revision,
            status,
            retention,
            updatedAt,
            generation,
            entries.values.sortedBy { it.name }
        )

        val transactionId = UUID.randomUUID().toString()
        val manifestFile = safeFile(directory, MANIFEST_NAME)
        val manifestTemporary = safeFile(directory, "$MANIFEST_NAME$TEMP_PREFIX$transactionId")
        val manifestBackup = safeFile(directory, "$MANIFEST_NAME$BACKUP_PREFIX$transactionId")
        val assetFile = safeFile(directory, assetName)
        val assetTemporary = safeFile(directory, "$assetName$TEMP_PREFIX$transactionId")
        val assetBackup = safeFile(directory, "$assetName$BACKUP_PREFIX$transactionId")
        writeSynced(assetTemporary, webpBytes, MAX_ASSET_BYTES)
        writeSynced(manifestTemporary, gson.toJson(manifest.toJson()).toByteArray(Charsets.UTF_8), MAX_MANIFEST_BYTES)
        try {
            replaceAssetThenManifest(
                assetFile,
                assetTemporary,
                assetBackup,
                manifestFile,
                manifestTemporary,
                manifestBackup
            )
        } finally {
            deleteIfPresent(assetTemporary)
            deleteIfPresent(manifestTemporary)
        }
        return StoredVisualAsset(templateId, revision, assetName, checksum, webpBytes.size.toLong())
    }

    private fun replaceAssetThenManifest(
        asset: File,
        assetTemporary: File,
        assetBackup: File,
        manifest: File,
        manifestTemporary: File,
        manifestBackup: File
    ) {
        listOf(asset, assetTemporary, assetBackup, manifest, manifestTemporary, manifestBackup)
            .forEach(::validateFileIdentity)
        val hadAsset = asset.exists()
        val hadManifest = manifest.exists()
        if (hadAsset && !moveChecked(asset, assetBackup)) throw IllegalStateException("asset_backup_failed")
        if (!moveChecked(assetTemporary, asset)) {
            rollback(assetBackup, asset, hadAsset)
            throw IllegalStateException("asset_replace_failed")
        }
        if (hadManifest && !moveChecked(manifest, manifestBackup)) {
            rollback(assetBackup, asset, hadAsset)
            throw IllegalStateException("asset_manifest_backup_failed")
        }
        if (!moveChecked(manifestTemporary, manifest)) {
            rollback(manifestBackup, manifest, hadManifest)
            rollback(assetBackup, asset, hadAsset)
            throw IllegalStateException("asset_manifest_replace_failed")
        }
        deleteIfPresent(manifestBackup)
        deleteIfPresent(assetBackup)
    }

    private fun rollback(backup: File, target: File, hadTarget: Boolean) {
        deleteIfPresent(target)
        validateFileIdentity(backup)
        if (hadTarget && backup.exists()) moveChecked(backup, target)
    }

    private fun readVerifiedAssetWithRecovery(directory: File, entry: AssetEntry): ByteArray? {
        val target = safeFile(directory, entry.name)
        readVerifiedAsset(target, entry)?.let { return it }
        val children = when (val result = boundedChildren(directory)) {
            is ChildResult.Valid -> result.children
            ChildResult.HighFanout, ChildResult.Unreadable -> return null
        }
        val backups = children
            .filter { it.name == "${entry.name}.bak" || it.name.startsWith("${entry.name}$BACKUP_PREFIX") }
            .sortedBy { it.name }
        for (backup in backups) {
            val recovered = readVerifiedAsset(backup, entry) ?: continue
            deleteIfPresent(target)
            if (!moveChecked(backup, target)) return null
            return recovered
        }
        return null
    }

    private fun loadManifest(directory: File, templateId: String, revision: Int): ManifestState {
        val children = when (val result = boundedChildren(directory)) {
            is ChildResult.Valid -> result.children
            ChildResult.HighFanout -> return ManifestState.Corrupt("high_fanout")
            ChildResult.Unreadable -> return ManifestState.Corrupt("manifest_unreadable")
        }
        val primary = safeFile(directory, MANIFEST_NAME)
        val backupFiles = children.filter {
            it.name == "$MANIFEST_NAME.bak" || it.name.startsWith("$MANIFEST_NAME$BACKUP_PREFIX")
        }
        if (backupFiles.size > MAX_RECOVERY_MANIFESTS) return ManifestState.Corrupt("high_fanout")
        val primaryManifest = readManifest(primary, templateId, revision)
        if (backupFiles.isEmpty()) {
            return when {
                primaryManifest != null -> ManifestState.Valid(primaryManifest)
                primary.exists() -> ManifestState.Corrupt("manifest_unreadable")
                else -> ManifestState.Missing
            }
        }

        val candidates = ArrayList<Pair<File, AssetManifest>>(backupFiles.size + 1)
        if (primaryManifest != null) candidates += primary to primaryManifest
        backupFiles.forEach { file ->
            readManifest(file, templateId, revision)?.let { manifest -> candidates += file to manifest }
        }
        val selected = candidates
            .filter { (_, manifest) -> manifestAssetsConsistent(directory, children, manifest) }
            .maxWithOrNull(
                compareBy<Pair<File, AssetManifest>> { it.second.generation }
                    .thenBy { it.second.assets.size }
                    .thenBy { sha256(gson.toJson(it.second.toJson()).toByteArray(Charsets.UTF_8)) }
                    .thenBy { it.first.name }
            ) ?: return ManifestState.Corrupt("manifest_assets_inconsistent")

        if (!samePath(selected.first, primary)) {
            deleteIfPresent(primary)
            if (!moveChecked(selected.first, primary)) return ManifestState.Corrupt("manifest_recovery_failed")
        }
        if (!recoverManifestAssets(directory, children, selected.second)) {
            return ManifestState.Corrupt("manifest_assets_inconsistent")
        }
        cleanupSupersededTransactionFiles(children, primary)
        return ManifestState.Valid(selected.second)
    }

    private fun manifestAssetsConsistent(
        directory: File,
        children: List<File>,
        manifest: AssetManifest
    ): Boolean = manifest.assets.all { entry ->
        readVerifiedAsset(safeFile(directory, entry.name), entry) != null ||
            assetBackups(children, entry).any { readVerifiedAsset(it, entry) != null }
    }

    private fun recoverManifestAssets(directory: File, children: List<File>, manifest: AssetManifest): Boolean {
        for (entry in manifest.assets) {
            val target = safeFile(directory, entry.name)
            if (readVerifiedAsset(target, entry) != null) continue
            val backup = assetBackups(children, entry).firstOrNull { readVerifiedAsset(it, entry) != null }
                ?: return false
            deleteIfPresent(target)
            if (!moveChecked(backup, target)) return false
        }
        return true
    }

    private fun assetBackups(children: List<File>, entry: AssetEntry): List<File> = children
        .filter { it.name == "${entry.name}.bak" || it.name.startsWith("${entry.name}$BACKUP_PREFIX") }
        .sortedBy { it.name }

    private fun cleanupSupersededTransactionFiles(children: List<File>, primary: File) {
        children.asSequence()
            .filterNot { samePath(it, primary) }
            .filter { isTransactionArtifact(it.name) }
            .sortedBy { it.name }
            .forEach(::deleteIfPresent)
    }

    private fun isTransactionArtifact(name: String): Boolean =
        name.startsWith("$MANIFEST_NAME$BACKUP_PREFIX") ||
            name.startsWith("$MANIFEST_NAME$TEMP_PREFIX") ||
            name.contains("$WEBP_SUFFIX$BACKUP_PREFIX", ignoreCase = true) ||
            name.contains("$WEBP_SUFFIX$TEMP_PREFIX", ignoreCase = true)

    private fun readManifest(file: File, templateId: String, revision: Int): AssetManifest? {
        val bytes = readBounded(file, MAX_MANIFEST_BYTES) ?: return null
        return runCatching {
            val parsed = JsonParser.parseString(String(bytes, Charsets.UTF_8))
            require(parsed.isJsonObject)
            parseManifest(parsed.asJsonObject, templateId, revision)
        }.getOrNull()
    }

    private fun parseManifest(root: JsonObject, templateId: String, revision: Int): AssetManifest {
        require(root.requiredInt("schemaVersion") == MANIFEST_SCHEMA_VERSION)
        require(root.requiredString("templateId") == templateId)
        require(root.requiredInt("revision") == revision)
        val status = root.requiredEnum<TemplateStatus>("status")
        val retention = root.requiredEnum<VisualAssetRetention>("retention")
        val updatedAt = root.requiredLong("updatedAt")
        require(updatedAt >= 0L)
        val generation = root.optionalLong("generation") ?: 0L
        require(generation >= 0L)
        val array = root.get("assets")
        require(array != null && array.isJsonArray && array.asJsonArray.size() <= MAX_ASSETS_PER_REVISION)
        val entries = array.asJsonArray.map { value ->
            require(value.isJsonObject)
            val item = value.asJsonObject
            val name = item.requiredString("name")
            validateAssetName(name)
            val checksum = item.requiredString("sha256")
            require(SHA256_PATTERN.matches(checksum))
            val size = item.requiredLong("size")
            require(size in MIN_WEBP_BYTES.toLong()..MAX_ASSET_BYTES.toLong())
            AssetEntry(name, checksum, size)
        }
        require(entries.map { it.name }.toSet().size == entries.size)
        return AssetManifest(templateId, revision, status, retention, updatedAt, generation, entries.sortedBy { it.name })
    }

    private fun AssetManifest.toJson(): JsonObject = JsonObject().apply {
        addProperty("schemaVersion", MANIFEST_SCHEMA_VERSION)
        addProperty("templateId", templateId)
        addProperty("revision", revision)
        addProperty("status", status.name)
        addProperty("retention", retention.name)
        addProperty("updatedAt", updatedAt)
        addProperty("generation", generation)
        add("assets", JsonArray().apply {
            assets.sortedBy { it.name }.forEach { entry ->
                add(JsonObject().apply {
                    addProperty("name", entry.name)
                    addProperty("sha256", entry.sha256)
                    addProperty("size", entry.size)
                })
            }
        })
    }

    private fun pruneLocked(maxBytes: Long, now: Long): VisualAssetPruneResult {
        if (!assetsRoot.exists()) return VisualAssetPruneResult(emptyList(), emptyList(), 0L, 0L, true)
        val scan = scanRevisions()
        if (scan is ScanResult.Failure) {
            return VisualAssetPruneResult(emptyList(), emptyList(), 0L, 0L, false, scan.reason)
        }
        scan as ScanResult.Success
        val latestDiagnosticKeys = scan.revisions
            .filter { it.metadata.retention == VisualAssetRetention.DIAGNOSTIC && !it.metadata.quarantined }
            .groupBy { it.metadata.templateId }
            .mapNotNull { (_, revisions) ->
                revisions.maxWithOrNull(
                    compareBy<ScannedRevision> { it.metadata.revision }.thenBy { it.metadata.updatedAt }
                )?.identity
            }
            .toSet()
        val withLatest = scan.revisions.map { revision ->
            revision.copy(
                metadata = revision.metadata.copy(isLatestDiagnostic = revision.identity in latestDiagnosticKeys)
            )
        }
        val protectedCanonicalTargets = withLatest
            .groupBy { it.canonicalIdentity }
            .filterValues { records -> records.any { it.baseProtected } }
            .keys
        val revisions = withLatest.map { revision ->
            revision.copy(protected = revision.canonicalIdentity in protectedCanonicalTargets)
        }
        val quarantineReasons = revisions.mapNotNull { it.metadata.quarantineReason.takeIf(String::isNotBlank) }.toSortedSet()
        val bytesBefore = saturatedSum(revisions.map { it.metadata.bytes })
        val retained = revisions.toMutableList()
        val deleted = mutableListOf<VisualAssetRevision>()
        var deleteFailed = false

        val expired = retained.filter { !it.protected && isExpired(it.metadata, now) }.sortedWith(pruneOrder)
        for (revision in expired) {
            if (deleteRevision(revision, protectedCanonicalTargets)) {
                retained.remove(revision)
                deleted += revision.metadata
            } else {
                deleteFailed = true
            }
        }
        var bytesAfter = saturatedSum(retained.map { it.metadata.bytes })
        if (bytesAfter > maxBytes) {
            val candidates = retained.filterNot { it.protected }.sortedWith(pruneOrder)
            for (revision in candidates) {
                if (bytesAfter <= maxBytes) break
                if (deleteRevision(revision, protectedCanonicalTargets)) {
                    retained.remove(revision)
                    deleted += revision.metadata
                    bytesAfter = saturatedSubtract(bytesAfter, revision.metadata.bytes)
                } else {
                    deleteFailed = true
                }
            }
        }
        bytesAfter = saturatedSum(retained.map { it.metadata.bytes })
        val protectedBytes = saturatedSum(retained.filter { it.protected }.map { it.metadata.bytes })
        val capMet = bytesAfter <= maxBytes
        val reason = when {
            !capMet && protectedBytes > maxBytes -> "protected_assets_exceed_cap"
            !capMet && deleteFailed -> "delete_failed"
            !capMet -> "cap_unmet"
            deleteFailed -> "delete_failed"
            quarantineReasons.isNotEmpty() -> "quarantined_entries"
            else -> ""
        }
        return VisualAssetPruneResult(
            retained.map { it.metadata }.sortedWith(metadataOrder),
            deleted.distinctBy { it.templateId to it.revision }.sortedWith(metadataOrder),
            bytesBefore,
            bytesAfter,
            capMet,
            reason,
            quarantineReasons
        )
    }

    private fun scanRevisions(): ScanResult {
        val templates = when (val result = boundedChildren(assetsRoot)) {
            is ChildResult.Valid -> result.children
            ChildResult.HighFanout -> return ScanResult.Failure("scan_limit_exceeded")
            ChildResult.Unreadable -> return ScanResult.Failure("scan_unreadable")
        }
        if (templates.size > MAX_TEMPLATE_DIRECTORIES) return ScanResult.Failure("scan_limit_exceeded")
        val revisions = mutableListOf<ScannedRevision>()
        var revisionCount = 0
        for (templateEntry in templates.sortedBy { it.name }) {
            if (!TEMPLATE_ID_PATTERN.matches(templateEntry.name)) continue
            val lexicalTemplate = templateEntry.absoluteFile
            val canonicalTemplate = canonicalize(lexicalTemplate).absoluteFile
            if (isLexicalAlias(lexicalTemplate, canonicalTemplate)) return ScanResult.Failure("canonical_alias")
            if (!lexicalTemplate.isDirectory || !isDescendant(lexicalTemplate, assetsRoot)) continue
            val children = when (val result = boundedChildren(lexicalTemplate)) {
                is ChildResult.Valid -> result.children
                ChildResult.HighFanout -> return ScanResult.Failure("scan_limit_exceeded")
                ChildResult.Unreadable -> return ScanResult.Failure("scan_unreadable")
            }
            for (entry in children.sortedBy { it.name }) {
                val match = REVISION_PATTERN.matchEntire(entry.name) ?: continue
                revisionCount++
                if (revisionCount > MAX_REVISION_DIRECTORIES) return ScanResult.Failure("scan_limit_exceeded")
                val revision = match.groupValues[1].toIntOrNull() ?: continue
                val lexicalRevision = entry.absoluteFile
                val canonicalRevision = canonicalize(lexicalRevision).absoluteFile
                if (isLexicalAlias(lexicalRevision, canonicalRevision)) {
                    revisions += quarantinedRevision(
                        lexicalRevision,
                        canonicalRevision,
                        lexicalTemplate.name,
                        revision,
                        "canonical_alias"
                    )
                    continue
                }
                if (!lexicalRevision.isDirectory || !isDescendant(lexicalRevision, assetsRoot)) continue
                when (val tree = collectTreeLexically(lexicalRevision)) {
                    TreeResult.HighFanout -> return ScanResult.Failure("scan_limit_exceeded")
                    TreeResult.Unreadable -> revisions += quarantinedRevision(
                        lexicalRevision,
                        canonicalRevision,
                        lexicalTemplate.name,
                        revision,
                        "entry_unreadable"
                    )
                    is TreeResult.Alias -> revisions += quarantinedRevision(
                        lexicalRevision,
                        canonicalRevision,
                        lexicalTemplate.name,
                        revision,
                        tree.reason
                    )
                    is TreeResult.Valid -> {
                        val manifestState = loadManifest(lexicalRevision, lexicalTemplate.name, revision)
                        val postRecoveryTree = when (val recoveredTree = collectTreeLexically(lexicalRevision)) {
                            TreeResult.HighFanout -> return ScanResult.Failure("scan_limit_exceeded")
                            TreeResult.Unreadable -> return ScanResult.Failure("scan_unreadable")
                            is TreeResult.Alias -> {
                                revisions += quarantinedRevision(
                                    lexicalRevision,
                                    canonicalRevision,
                                    lexicalTemplate.name,
                                    revision,
                                    recoveredTree.reason
                                )
                                continue
                            }
                            is TreeResult.Valid -> recoveredTree
                        }
                        val bytes = when (val accounting = accountTreeBytes(postRecoveryTree, lexicalRevision)) {
                            is TreeAccounting.Valid -> accounting.bytes
                            is TreeAccounting.Alias -> {
                                revisions += quarantinedRevision(
                                    lexicalRevision,
                                    canonicalRevision,
                                    lexicalTemplate.name,
                                    revision,
                                    accounting.reason
                                )
                                continue
                            }
                            TreeAccounting.Unreadable -> return ScanResult.Failure("scan_unreadable")
                        }
                        val metadata = when (manifestState) {
                            is ManifestState.Valid -> VisualAssetRevision(
                                lexicalTemplate.name,
                                revision,
                                manifestState.manifest.status,
                                manifestState.manifest.retention,
                                manifestState.manifest.updatedAt,
                                bytes
                            )
                            ManifestState.Missing -> VisualAssetRevision(
                                lexicalTemplate.name,
                                revision,
                                TemplateStatus.DRAFT,
                                VisualAssetRetention.ROUTINE,
                                postRecoveryTree.files.maxOfOrNull { it.lastModified().coerceAtLeast(0L) } ?: 0L,
                                bytes
                            )
                            is ManifestState.Corrupt -> VisualAssetRevision(
                                lexicalTemplate.name,
                                revision,
                                TemplateStatus.DISABLED,
                                VisualAssetRetention.DIAGNOSTIC,
                                postRecoveryTree.files.maxOfOrNull { it.lastModified().coerceAtLeast(0L) } ?: 0L,
                                bytes,
                                quarantined = true,
                                quarantineReason = manifestState.reason
                            )
                        }
                        revisions += ScannedRevision(
                            lexicalRevision,
                            pathIdentity(canonicalRevision),
                            metadata
                        )
                    }
                }
            }
        }
        return ScanResult.Success(revisions)
    }

    private fun accountTreeBytes(tree: TreeResult.Valid, lexicalRoot: File): TreeAccounting {
        val lengths = ArrayList<Long>(tree.files.size)
        for (entry in tree.files) {
            val lexical = entry.absoluteFile
            val canonical = runCatching { canonicalize(lexical).absoluteFile }.getOrNull()
                ?: return TreeAccounting.Unreadable
            if (isLexicalAlias(lexical, canonical)) return TreeAccounting.Alias("canonical_alias")
            if (!isSameOrDescendant(lexical, lexicalRoot) || !isDescendant(lexical, assetsRoot)) {
                return TreeAccounting.Alias("outside_store_root")
            }
            when {
                lexical.isDirectory -> Unit
                lexical.isFile -> lengths += measuredFileLength(lexical) ?: return TreeAccounting.Unreadable
                else -> return TreeAccounting.Unreadable
            }
        }
        return TreeAccounting.Valid(saturatedSum(lengths))
    }

    private fun measuredFileLength(file: File): Long? = runCatching {
        val lexical = validateFileIdentity(file)
        RandomAccessFile(lexical, "r").use { handle ->
            validateFileIdentity(lexical)
            handle.length().takeIf { it >= 0L }
        }
    }.getOrNull()

    private fun quarantinedRevision(
        lexical: File,
        canonical: File,
        templateId: String,
        revision: Int,
        reason: String
    ): ScannedRevision = ScannedRevision(
        lexical,
        pathIdentity(canonical),
        VisualAssetRevision(
            templateId,
            revision,
            TemplateStatus.DISABLED,
            VisualAssetRetention.DIAGNOSTIC,
            lexical.lastModified().coerceAtLeast(0L),
            0L,
            quarantined = true,
            quarantineReason = reason
        )
    )

    private fun collectTreeLexically(directory: File): TreeResult {
        val lexicalRoot = directory.absoluteFile
        if (isLexicalAlias(lexicalRoot, canonicalize(lexicalRoot).absoluteFile)) return TreeResult.Alias("canonical_alias")
        if (!isDescendant(lexicalRoot, assetsRoot)) return TreeResult.Alias("outside_store_root")
        val collected = mutableListOf<File>()
        val pending = ArrayDeque<Pair<File, Int>>()
        pending.add(lexicalRoot to 0)
        while (pending.isNotEmpty()) {
            val (lexical, depth) = pending.removeLast()
            val absolute = lexical.absoluteFile
            val canonical = canonicalize(absolute).absoluteFile
            if (isLexicalAlias(absolute, canonical)) return TreeResult.Alias("canonical_alias")
            if (!isSameOrDescendant(absolute, lexicalRoot) || !isDescendant(absolute, assetsRoot)) {
                return TreeResult.Alias("outside_store_root")
            }
            collected += absolute
            if (collected.size > MAX_TREE_ENTRIES || depth > MAX_TREE_DEPTH) return TreeResult.HighFanout
            if (absolute.isDirectory) {
                when (val children = boundedChildren(absolute)) {
                    ChildResult.HighFanout -> return TreeResult.HighFanout
                    ChildResult.Unreadable -> return TreeResult.Unreadable
                    is ChildResult.Valid -> children.children
                        .sortedByDescending { it.name }
                        .forEach { pending.add(it.absoluteFile to depth + 1) }
                }
            }
        }
        return TreeResult.Valid(collected)
    }

    private fun deleteRevision(revision: ScannedRevision, protectedCanonicalTargets: Set<String>): Boolean {
        if (revision.protected || revision.canonicalIdentity in protectedCanonicalTargets) return false
        val lexical = revision.directory.absoluteFile
        val canonical = canonicalize(lexical).absoluteFile
        if (isLexicalAlias(lexical, canonical) || pathIdentity(canonical) != revision.canonicalIdentity) return false
        val tree = collectTreeLexically(lexical)
        if (tree !is TreeResult.Valid) return false
        for (entry in tree.files.sortedByDescending { it.path.length }) {
            val absolute = entry.absoluteFile
            if (isLexicalAlias(absolute, canonicalize(absolute).absoluteFile)) return false
            if (!isSameOrDescendant(absolute, lexical) || !isDescendant(absolute, assetsRoot)) return false
            if (absolute.exists() && !absolute.delete()) return false
        }
        return true
    }

    private fun readVerifiedAsset(file: File, entry: AssetEntry): ByteArray? {
        val lexical = validateFileIdentity(file)
        if (!lexical.isFile || lexical.length() != entry.size || entry.size > MAX_ASSET_BYTES) return null
        val bytes = readBounded(lexical, MAX_ASSET_BYTES) ?: return null
        if (bytes.size.toLong() != entry.size || !isStructuredWebp(bytes)) return null
        val actual = sha256(bytes).toByteArray(Charsets.US_ASCII)
        val expected = entry.sha256.toByteArray(Charsets.US_ASCII)
        if (!MessageDigest.isEqual(actual, expected)) return null
        return bytes
    }

    private fun isStructuredWebp(bytes: ByteArray): Boolean {
        if (bytes.size !in MIN_WEBP_BYTES..MAX_ASSET_BYTES) return false
        if (!hasFourCc(bytes, 0, "RIFF") || !hasFourCc(bytes, 8, "WEBP")) return false
        val riffSize = littleEndianUInt32(bytes, 4) ?: return false
        if (riffSize != bytes.size.toLong() - 8L) return false
        var offset = 12
        var chunkCount = 0
        var rasterDimensions: ImageDimensions? = null
        var extendedDimensions: ImageDimensions? = null
        while (offset < bytes.size) {
            if (bytes.size - offset < 8) return false
            val chunkSize = littleEndianUInt32(bytes, offset + 4) ?: return false
            if (chunkSize > MAX_ASSET_BYTES.toLong()) return false
            val dataStart = offset + 8
            val dataEnd = dataStart.toLong() + chunkSize
            val paddedEnd = dataEnd + (chunkSize and 1L)
            if (dataEnd > bytes.size.toLong() || paddedEnd > bytes.size.toLong()) return false
            when {
                hasFourCc(bytes, offset, "VP8L") -> {
                    if (chunkSize < 5L || bytes[dataStart].toInt() and 0xff != 0x2f) return false
                    if (rasterDimensions != null) return false
                    val packed = littleEndianUInt32(bytes, dataStart + 1) ?: return false
                    if ((packed ushr 29) and 0x07L != 0L) return false
                    val dimensions = ImageDimensions(
                        ((packed and 0x3fffL) + 1L).toInt(),
                        (((packed ushr 14) and 0x3fffL) + 1L).toInt()
                    )
                    if (!dimensions.isValid()) return false
                    rasterDimensions = dimensions
                }
                hasFourCc(bytes, offset, "VP8 ") -> {
                    if (chunkSize < 10L || bytes[dataStart + 3].toInt() and 0xff != 0x9d ||
                        bytes[dataStart + 4].toInt() and 0xff != 0x01 ||
                        bytes[dataStart + 5].toInt() and 0xff != 0x2a
                    ) return false
                    if (rasterDimensions != null) return false
                    val frameTag = (bytes[dataStart].toInt() and 0xff) or
                        ((bytes[dataStart + 1].toInt() and 0xff) shl 8) or
                        ((bytes[dataStart + 2].toInt() and 0xff) shl 16)
                    if (frameTag and 0x01 != 0 || (frameTag ushr 1) and 0x07 > 3 || frameTag and 0x10 == 0) {
                        return false
                    }
                    val firstPartitionSize = frameTag ushr 5
                    if (firstPartitionSize <= 0 || firstPartitionSize.toLong() > chunkSize - 10L) return false
                    val width = (littleEndianUInt16(bytes, dataStart + 6) ?: return false) and 0x3fff
                    val height = (littleEndianUInt16(bytes, dataStart + 8) ?: return false) and 0x3fff
                    val dimensions = ImageDimensions(width, height)
                    if (!dimensions.isValid()) return false
                    rasterDimensions = dimensions
                }
                hasFourCc(bytes, offset, "VP8X") -> {
                    if (chunkSize != 10L || extendedDimensions != null || chunkCount != 0) return false
                    val flags = bytes[dataStart].toInt() and 0xff
                    if (flags and 0xc1 != 0 || flags and 0x02 != 0) return false
                    if ((1..3).any { bytes[dataStart + it].toInt() != 0 }) return false
                    val widthMinusOne = littleEndianUInt24(bytes, dataStart + 4) ?: return false
                    val heightMinusOne = littleEndianUInt24(bytes, dataStart + 7) ?: return false
                    val dimensions = ImageDimensions(widthMinusOne + 1, heightMinusOne + 1)
                    if (!dimensions.isValid()) return false
                    extendedDimensions = dimensions
                }
            }
            chunkCount++
            if (chunkCount > MAX_WEBP_CHUNKS) return false
            offset = paddedEnd.toInt()
        }
        val raster = rasterDimensions ?: return false
        return offset == bytes.size && (extendedDimensions == null || extendedDimensions == raster)
    }

    private fun hasFourCc(bytes: ByteArray, offset: Int, value: String): Boolean {
        if (offset < 0 || offset + 4 > bytes.size) return false
        return (0 until 4).all { bytes[offset + it] == value[it].code.toByte() }
    }

    private fun littleEndianUInt32(bytes: ByteArray, offset: Int): Long? {
        if (offset < 0 || offset + 4 > bytes.size) return null
        return (bytes[offset].toLong() and 0xffL) or
            ((bytes[offset + 1].toLong() and 0xffL) shl 8) or
            ((bytes[offset + 2].toLong() and 0xffL) shl 16) or
            ((bytes[offset + 3].toLong() and 0xffL) shl 24)
    }

    private fun littleEndianUInt16(bytes: ByteArray, offset: Int): Int? {
        if (offset < 0 || offset + 2 > bytes.size) return null
        return (bytes[offset].toInt() and 0xff) or ((bytes[offset + 1].toInt() and 0xff) shl 8)
    }

    private fun littleEndianUInt24(bytes: ByteArray, offset: Int): Int? {
        if (offset < 0 || offset + 3 > bytes.size) return null
        return (bytes[offset].toInt() and 0xff) or
            ((bytes[offset + 1].toInt() and 0xff) shl 8) or
            ((bytes[offset + 2].toInt() and 0xff) shl 16)
    }

    private fun isExpired(revision: VisualAssetRevision, now: Long): Boolean {
        val age = (now - revision.updatedAt).coerceAtLeast(0L)
        return when (revision.retention) {
            VisualAssetRetention.ROUTINE -> age >= ROUTINE_RETENTION_MS
            VisualAssetRetention.DIAGNOSTIC -> age >= DIAGNOSTIC_RETENTION_MS
        }
    }

    private fun revisionDirectory(templateId: String, revision: Int, create: Boolean): File {
        if (create) ensureDirectory(assetsRoot)
        val template = safeFile(assetsRoot, templateId)
        if (create) ensureDirectory(template)
        val directory = safeFile(template, "r$revision")
        if (create) ensureDirectory(directory)
        return directory
    }

    private fun ensureDirectory(directory: File) {
        if (!directory.isDirectory && !directory.mkdirs()) throw IllegalStateException("asset_directory_create_failed")
        val canonical = canonicalize(directory).absoluteFile
        require(!isLexicalAlias(directory.absoluteFile, canonical)) { "asset_directory_alias" }
        require(isSameOrDescendant(canonical, assetsRoot) || samePath(canonical, root)) { "asset_directory_outside_root" }
    }

    private fun safeFile(parent: File, name: String): File {
        val lexicalParent = parent.absoluteFile
        val child = File(lexicalParent, name).absoluteFile
        require(isDescendant(child, lexicalParent)) { "asset_path_outside_root" }
        require(isDescendant(child, assetsRoot) || samePath(child, assetsRoot)) { "asset_path_outside_root" }
        return validateFileIdentity(child)
    }

    private fun boundedChildren(directory: File): ChildResult {
        val children = directory.listFiles() ?: return ChildResult.Unreadable
        if (children.size > MAX_DIRECTORY_FANOUT) return ChildResult.HighFanout
        return ChildResult.Valid(children.toList())
    }

    private fun validateTemplateId(templateId: String) {
        require(TEMPLATE_ID_PATTERN.matches(templateId) && templateId != "." && templateId != "..") {
            "template_id_invalid"
        }
    }

    private fun validateRevision(revision: Int) {
        require(revision in 1..MAX_REVISION) { "template_revision_invalid" }
    }

    private fun validateAssetName(assetName: String) {
        require(ASSET_NAME_PATTERN.matches(assetName) && assetName != "." && assetName != "..") {
            "asset_name_invalid"
        }
        require(assetName.endsWith(WEBP_SUFFIX, ignoreCase = true)) { "asset_extension_invalid" }
    }

    private fun writeSynced(file: File, bytes: ByteArray, maxBytes: Int) {
        require(bytes.size <= maxBytes) { "asset_write_too_large" }
        val lexical = validateFileIdentity(file)
        FileOutputStream(lexical).use { output ->
            output.write(bytes)
            output.fd.sync()
        }
    }

    private fun readBounded(file: File, maxBytes: Int): ByteArray? {
        val lexical = validateFileIdentity(file)
        if (!lexical.isFile || lexical.length() < 0L || lexical.length() > maxBytes.toLong()) return null
        return runCatching {
            FileInputStream(validateFileIdentity(lexical)).use { input ->
                val output = ByteArrayOutputStream(minOf(lexical.length().toInt(), 8_192))
                val buffer = ByteArray(8_192)
                var total = 0
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    total += read
                    if (total > maxBytes) return null
                    output.write(buffer, 0, read)
                }
                output.toByteArray()
            }
        }.getOrNull()
    }

    private fun deleteIfPresent(file: File) {
        val lexical = validateFileIdentity(file)
        if (lexical.exists() && !lexical.delete()) throw IllegalStateException("asset_staging_cleanup_failed")
    }

    private fun moveChecked(source: File, destination: File): Boolean {
        val lexicalSource = validateFileIdentity(source)
        val lexicalDestination = validateFileIdentity(destination)
        return rename(lexicalSource, lexicalDestination)
    }

    private fun validateFileIdentity(file: File): File {
        val lexical = file.absoluteFile
        require(isDescendant(lexical, root)) { "asset_path_outside_root" }
        val canonical = canonicalize(lexical).absoluteFile
        require(isDescendant(canonical, root)) { "asset_path_outside_root" }
        require(!isLexicalAlias(lexical, canonical)) { "asset_path_alias" }
        return lexical
    }

    private fun sha256(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        val encoded = CharArray(digest.size * 2)
        for (index in digest.indices) {
            val value = digest[index].toInt() and 0xff
            encoded[index * 2] = HEX[value ushr 4]
            encoded[index * 2 + 1] = HEX[value and 0x0f]
        }
        return String(encoded)
    }

    private fun <T> withStoreLock(block: () -> T): T {
        processLock.lock()
        try {
            if (!root.isDirectory && !root.mkdirs()) throw IllegalStateException("asset_root_create_failed")
            val lexicalLock = validateFileIdentity(lockFile)
            RandomAccessFile(lexicalLock, "rw").channel.use { channel ->
                validateFileIdentity(lexicalLock)
                val fileLock = channel.lock()
                try {
                    return block()
                } finally {
                    fileLock.release()
                }
            }
        } finally {
            processLock.unlock()
        }
    }

    private fun samePath(first: File, second: File): Boolean =
        first.absolutePath.equals(second.absolutePath, ignoreCase = File.separatorChar == '\\')

    private fun isLexicalAlias(lexical: File, canonical: File): Boolean {
        if (!samePath(lexical.absoluteFile, canonical.absoluteFile)) return true
        val androidSymlink = runCatching {
            OsConstants.S_ISLNK(Os.lstat(lexical.absolutePath).st_mode)
        }.getOrDefault(false)
        if (androidSymlink) return true
        return runCatching {
            val pathType = Class.forName("java.nio.file.Path")
            val path = File::class.java.getMethod("toPath").invoke(lexical)
            Class.forName("java.nio.file.Files")
                .getMethod("isSymbolicLink", pathType)
                .invoke(null, path) as Boolean
        }.getOrDefault(false)
    }

    private fun pathIdentity(file: File): String =
        if (File.separatorChar == '\\') file.absolutePath.lowercase() else file.absolutePath

    private fun isSameOrDescendant(file: File, parent: File): Boolean = samePath(file, parent) || isDescendant(file, parent)

    private fun isDescendant(file: File, parent: File): Boolean {
        val prefix = parent.absolutePath.trimEnd(File.separatorChar) + File.separator
        return file.absolutePath.startsWith(prefix, ignoreCase = File.separatorChar == '\\')
    }

    private fun saturatedSum(values: Iterable<Long>): Long {
        var sum = 0L
        for (value in values) {
            if (value < 0L || Long.MAX_VALUE - sum < value) return Long.MAX_VALUE
            sum += value
        }
        return sum
    }

    private fun saturatedSubtract(value: Long, subtraction: Long): Long = if (subtraction >= value) 0L else value - subtraction

    private val ScannedRevision.identity: RevisionIdentity
        get() = RevisionIdentity(metadata.templateId, metadata.revision)

    private val ScannedRevision.baseProtected: Boolean
        get() = metadata.status == TemplateStatus.ACTIVE || metadata.isLatestDiagnostic || metadata.quarantined

    private data class AssetEntry(val name: String, val sha256: String, val size: Long)

    private data class AssetManifest(
        val templateId: String,
        val revision: Int,
        val status: TemplateStatus,
        val retention: VisualAssetRetention,
        val updatedAt: Long,
        val generation: Long,
        val assets: List<AssetEntry>
    )

    private data class ImageDimensions(val width: Int, val height: Int) {
        fun isValid(): Boolean = width > 0 && height > 0 &&
            width.toLong() * height.toLong() <= MAX_DECODED_PIXELS
    }

    private data class RevisionIdentity(val templateId: String, val revision: Int)

    private data class ScannedRevision(
        val directory: File,
        val canonicalIdentity: String,
        val metadata: VisualAssetRevision,
        val protected: Boolean = false
    )

    private sealed interface ManifestState {
        data class Valid(val manifest: AssetManifest) : ManifestState
        data class Corrupt(val reason: String) : ManifestState
        data object Missing : ManifestState
    }

    private sealed interface ChildResult {
        data class Valid(val children: List<File>) : ChildResult
        data object HighFanout : ChildResult
        data object Unreadable : ChildResult
    }

    private sealed interface TreeResult {
        data class Valid(val files: List<File>) : TreeResult
        data class Alias(val reason: String) : TreeResult
        data object HighFanout : TreeResult
        data object Unreadable : TreeResult
    }

    private sealed interface TreeAccounting {
        data class Valid(val bytes: Long) : TreeAccounting
        data class Alias(val reason: String) : TreeAccounting
        data object Unreadable : TreeAccounting
    }

    private sealed interface ScanResult {
        data class Success(val revisions: List<ScannedRevision>) : ScanResult
        data class Failure(val reason: String) : ScanResult
    }

    private val pruneOrder = compareBy<ScannedRevision> { it.metadata.updatedAt }
        .thenBy { it.metadata.retention.ordinal }
        .thenBy { it.metadata.templateId }
        .thenBy { it.metadata.revision }

    private val metadataOrder = compareBy<VisualAssetRevision> { it.templateId }.thenBy { it.revision }

    private fun JsonObject.requiredString(name: String): String {
        val value = get(name)
        require(value != null && value.isJsonPrimitive && value.asJsonPrimitive.isString)
        return value.asString
    }

    private fun JsonObject.requiredInt(name: String): Int {
        val value = get(name)
        require(value != null && value.isJsonPrimitive && value.asJsonPrimitive.isNumber)
        return value.asString.toIntOrNull() ?: throw IllegalArgumentException("invalid_$name")
    }

    private fun JsonObject.requiredLong(name: String): Long {
        val value = get(name)
        require(value != null && value.isJsonPrimitive && value.asJsonPrimitive.isNumber)
        return value.asString.toLongOrNull() ?: throw IllegalArgumentException("invalid_$name")
    }

    private fun JsonObject.optionalLong(name: String): Long? {
        val value = get(name) ?: return null
        require(value.isJsonPrimitive && value.asJsonPrimitive.isNumber)
        return value.asString.toLongOrNull() ?: throw IllegalArgumentException("invalid_$name")
    }

    private inline fun <reified T : Enum<T>> JsonObject.requiredEnum(name: String): T {
        val encoded = requiredString(name)
        return enumValues<T>().firstOrNull { it.name == encoded } ?: throw IllegalArgumentException("invalid_$name")
    }

    companion object {
        const val MAX_ASSET_BYTES = 16 * 1024 * 1024
        const val DEFAULT_MAX_BYTES = 128L * 1024L * 1024L

        private const val ASSETS_DIRECTORY = "assets"
        private const val LOCK_FILE_NAME = ".visual-assets.lock"
        private const val MANIFEST_NAME = "asset-manifest.json"
        private const val MANIFEST_SCHEMA_VERSION = 1
        private const val MAX_MANIFEST_BYTES = 256 * 1024
        private const val MAX_ASSETS_PER_REVISION = 128
        private const val MAX_RECOVERY_MANIFESTS = 8
        private const val MAX_TEMPLATE_DIRECTORIES = 256
        private const val MAX_REVISION_DIRECTORIES = 4_096
        private const val MAX_DIRECTORY_FANOUT = 256
        private const val MAX_TREE_ENTRIES = 1_024
        private const val MAX_TREE_DEPTH = 4
        private const val MAX_REVISION = 1_000_000
        private const val MIN_WEBP_BYTES = 26
        private const val MAX_WEBP_CHUNKS = 128
        private const val MAX_DECODED_PIXELS = 16_777_216L
        private const val WEBP_SUFFIX = ".webp"
        private const val TEMP_PREFIX = ".tmp-"
        private const val BACKUP_PREFIX = ".bak-"
        private const val DAY_MS = 24L * 60L * 60L * 1_000L
        private const val ROUTINE_RETENTION_MS = 7L * DAY_MS
        private const val DIAGNOSTIC_RETENTION_MS = 30L * DAY_MS

        private val TEMPLATE_ID_PATTERN = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
        private val ASSET_NAME_PATTERN = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
        private val REVISION_PATTERN = Regex("^r([1-9][0-9]{0,6})$")
        private val SHA256_PATTERN = Regex("^[0-9a-f]{64}$")
        private val HEX = "0123456789abcdef".toCharArray()
        private val processLocks = HashMap<String, ReentrantLock>()

        private fun retentionFor(status: TemplateStatus): VisualAssetRetention =
            if (status == TemplateStatus.DEGRADED) VisualAssetRetention.DIAGNOSTIC else VisualAssetRetention.ROUTINE

        private fun processLockFor(path: String): ReentrantLock = synchronized(processLocks) {
            processLocks.getOrPut(if (File.separatorChar == '\\') path.lowercase() else path) { ReentrantLock() }
        }
    }
}
