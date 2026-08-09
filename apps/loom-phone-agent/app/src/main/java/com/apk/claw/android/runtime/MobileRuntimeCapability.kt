package com.apk.claw.android.runtime

private val SAFE_RUNTIME_ID = Regex("^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

enum class MobileRuntimeRisk {
    READ_ONLY,
    WORKSPACE_MUTATION,
    DEVICE_ACTION
}

/** Closed capability set shared by optional runtimes and the native gateway. */
enum class MobileRuntimeCapability(
    val toolId: String,
    val risk: MobileRuntimeRisk,
    val nativeFastPath: Boolean
) {
    SCREEN_OBSERVE("device.screen.observe", MobileRuntimeRisk.READ_ONLY, true),
    DEVICE_PROFILE_READ("device.profile.read", MobileRuntimeRisk.READ_ONLY, true),
    APP_OPEN("device.app.open", MobileRuntimeRisk.DEVICE_ACTION, true),
    SYSTEM_KEY("device.system.key", MobileRuntimeRisk.DEVICE_ACTION, true),
    WORKSPACE_READ("workspace.file.read", MobileRuntimeRisk.READ_ONLY, true),
    WORKSPACE_WRITE("workspace.file.write", MobileRuntimeRisk.WORKSPACE_MUTATION, true)
}

data class MobileRuntimeScope(
    val accountId: String,
    val customerId: String,
    val workspaceId: String
) {
    init {
        require(SAFE_RUNTIME_ID.matches(accountId)) { "Invalid runtime account id" }
        require(SAFE_RUNTIME_ID.matches(customerId)) { "Invalid runtime customer id" }
        require(SAFE_RUNTIME_ID.matches(workspaceId)) { "Invalid runtime workspace id" }
    }

    internal fun canonical(): String = "$accountId\u0000$customerId\u0000$workspaceId"
}

data class MobileRuntimeGrant(
    val scope: MobileRuntimeScope,
    val allowedCapabilities: Set<MobileRuntimeCapability>,
    val approvalId: String,
    val expiresAtEpochMs: Long,
    val enabled: Boolean = true
) {
    init {
        require(SAFE_RUNTIME_ID.matches(approvalId)) { "Invalid runtime approval id" }
        require(allowedCapabilities.isNotEmpty()) { "A runtime grant needs at least one capability" }
    }
}

enum class MobileRuntimeBackendKind {
    NATIVE,
    OPTIONAL_LINUX
}

enum class MobileRuntimeBackendState {
    AVAILABLE,
    UNAVAILABLE,
    UNAUTHORIZED,
    UNHEALTHY,
    DISABLED
}

data class MobileRuntimeBackendDescriptor(
    val id: String,
    val kind: MobileRuntimeBackendKind,
    val state: MobileRuntimeBackendState,
    val capabilities: Set<MobileRuntimeCapability>,
    val priority: Int
) {
    init {
        require(SAFE_RUNTIME_ID.matches(id)) { "Invalid runtime backend id" }
        require(priority in 0..1_000) { "Invalid runtime backend priority" }
    }
}

data class MobileRuntimeBackendSelection(
    val selectedBackendId: String?,
    val fallbackUsed: Boolean,
    val reasonCode: String
)

object MobileRuntimeBackendSelector {
    fun select(
        capability: MobileRuntimeCapability,
        backends: List<MobileRuntimeBackendDescriptor>,
        preferredBackendId: String? = null
    ): MobileRuntimeBackendSelection {
        val candidates = backends.filter {
            it.state == MobileRuntimeBackendState.AVAILABLE && capability in it.capabilities
        }
        val preferred = preferredBackendId?.let { id -> candidates.firstOrNull { it.id == id } }
        if (preferred != null) {
            return MobileRuntimeBackendSelection(preferred.id, fallbackUsed = false, reasonCode = "preferred_backend_selected")
        }
        val selected = candidates
            .sortedWith(
                compareByDescending<MobileRuntimeBackendDescriptor> { it.kind == MobileRuntimeBackendKind.NATIVE }
                    .thenByDescending { it.priority }
                    .thenBy { it.id }
            )
            .firstOrNull()
        if (selected == null) {
            return MobileRuntimeBackendSelection(null, fallbackUsed = false, reasonCode = "capability_unavailable")
        }
        val fellBack = !preferredBackendId.isNullOrBlank() && selected.id != preferredBackendId
        return MobileRuntimeBackendSelection(
            selectedBackendId = selected.id,
            fallbackUsed = fellBack,
            reasonCode = if (fellBack) "preferred_backend_unavailable" else "native_fast_path_selected"
        )
    }
}

enum class MobileProviderFieldType {
    STRING,
    URL,
    BOOLEAN,
    ENUM,
    SECRET
}

data class MobileProviderFieldSchema(
    val id: String,
    val type: MobileProviderFieldType,
    val required: Boolean = false,
    val sensitive: Boolean = false,
    val writeOnly: Boolean = false,
    val allowedValues: List<String> = emptyList()
) {
    init {
        require(SAFE_RUNTIME_ID.matches(id)) { "Invalid provider field id" }
        require(!sensitive || writeOnly) { "Sensitive provider fields must be write-only" }
        require(type != MobileProviderFieldType.SECRET || sensitive) { "Secret fields must be sensitive" }
        require(type == MobileProviderFieldType.ENUM || allowedValues.isEmpty()) { "Only enum fields accept allowed values" }
        require(type != MobileProviderFieldType.ENUM || allowedValues.isNotEmpty()) { "Enum fields need allowed values" }
    }
}

data class MobileProviderSchema(
    val id: String,
    val protocols: Set<String>,
    val fields: List<MobileProviderFieldSchema>
) {
    init {
        require(SAFE_RUNTIME_ID.matches(id)) { "Invalid provider schema id" }
        require(protocols.isNotEmpty()) { "Provider schema needs a protocol" }
        require(protocols.all(SAFE_RUNTIME_ID::matches)) { "Invalid provider protocol" }
        require(fields.map { it.id }.distinct().size == fields.size) { "Duplicate provider field" }
    }
}

class MobileProviderSchemaRegistry(schemas: List<MobileProviderSchema>) {
    private val discovered = schemas.sortedBy { it.id }.also {
        require(it.map(MobileProviderSchema::id).distinct().size == it.size) { "Duplicate provider schema" }
    }

    /** Returns metadata only. Provider values and credentials are deliberately not represented. */
    fun discover(): List<MobileProviderSchema> = discovered.toList()

    fun schema(id: String): MobileProviderSchema? = discovered.firstOrNull { it.id == id }
}

interface WriteOnlyProviderCredentialVault {
    /** Writes a credential and returns an opaque handle. No read method exists by design. */
    fun write(providerId: String, fieldId: String, value: CharArray): String

    fun delete(handle: String)
}

data class MobileProviderConfiguration(
    val providerId: String,
    val schemaId: String,
    val values: Map<String, Any>,
    val credentialHandles: Map<String, String>
) {
    override fun toString(): String =
        "MobileProviderConfiguration(providerId=$providerId, schemaId=$schemaId, " +
            "fields=${values.keys.sorted()}, credentialFields=${credentialHandles.keys.sorted()})"
}

interface MobileProviderConfigurationStore {
    /** Staging must not replace the current committed pointer. */
    fun stage(configuration: MobileProviderConfiguration): String

    /** Commit atomically switches the current pointer to the staged configuration. */
    fun commit(stageId: String)

    fun rollback(stageId: String)
}

fun interface MobileProviderCompatibilityProbe {
    fun probe(configuration: MobileProviderConfiguration): Boolean
}

data class ProviderConfigurationResult(
    val committed: Boolean,
    val code: String
)

class ProviderConfigurationCoordinator(
    private val schemas: MobileProviderSchemaRegistry,
    private val vault: WriteOnlyProviderCredentialVault,
    private val store: MobileProviderConfigurationStore,
    private val probe: MobileProviderCompatibilityProbe
) {
    fun configure(
        providerId: String,
        schemaId: String,
        values: Map<String, Any>,
        credentials: Map<String, CharArray>
    ): ProviderConfigurationResult {
        val schema = schemas.schema(schemaId)
        val validationCode = validateInput(providerId, schema, values, credentials)
        if (validationCode != null) {
            credentials.values.forEach { it.fill('\u0000') }
            return ProviderConfigurationResult(false, validationCode)
        }

        val handles = linkedMapOf<String, String>()
        var stageId: String? = null
        var failureCode = "provider_config_failed"
        try {
            credentials.toSortedMap().forEach { (fieldId, secret) ->
                val handle = vault.write(providerId, fieldId, secret)
                require(VAULT_HANDLE.matches(handle)) { "Credential vault returned an invalid handle" }
                handles[fieldId] = handle
            }
            val configuration = MobileProviderConfiguration(
                providerId = providerId,
                schemaId = schemaId,
                values = values.toMap(),
                credentialHandles = handles.toMap()
            )
            stageId = store.stage(configuration)
            require(SAFE_RUNTIME_STAGE.matches(stageId)) { "Configuration store returned an invalid stage id" }
            if (!probe.probe(configuration)) {
                failureCode = "provider_probe_failed"
                throw ProviderProbeFailed()
            }
            store.commit(stageId)
            return ProviderConfigurationResult(true, "provider_config_committed")
        } catch (_: Exception) {
            stageId?.let { runCatching { store.rollback(it) } }
            handles.values.toList().asReversed().forEach { handle ->
                runCatching { vault.delete(handle) }
            }
            return ProviderConfigurationResult(false, failureCode)
        } finally {
            credentials.values.forEach { it.fill('\u0000') }
        }
    }

    private fun validateInput(
        providerId: String,
        schema: MobileProviderSchema?,
        values: Map<String, Any>,
        credentials: Map<String, CharArray>
    ): String? {
        if (!SAFE_RUNTIME_ID.matches(providerId) || schema == null) return "provider_config_invalid"
        val fields = schema.fields.associateBy { it.id }
        if ((values.keys + credentials.keys).any { it !in fields }) return "provider_config_invalid"
        if (values.keys.any { fields[it]?.sensitive == true }) return "provider_config_invalid"
        if (credentials.keys.any { fields[it]?.sensitive != true }) return "provider_config_invalid"
        if (schema.fields.any { field ->
                field.required && if (field.sensitive) credentials[field.id]?.isNotEmpty() != true else field.id !in values
            }
        ) return "provider_config_invalid"
        if (credentials.values.any { it.isEmpty() || it.size > 32_768 }) return "provider_config_invalid"
        for ((id, value) in values) {
            val field = fields.getValue(id)
            val valid = when (field.type) {
                MobileProviderFieldType.STRING,
                MobileProviderFieldType.URL -> value is String && value.isNotBlank() && value.length <= 2_048
                MobileProviderFieldType.BOOLEAN -> value is Boolean
                MobileProviderFieldType.ENUM -> value is String && value in field.allowedValues
                MobileProviderFieldType.SECRET -> false
            }
            if (!valid) return "provider_config_invalid"
        }
        return null
    }

    private class ProviderProbeFailed : Exception()
}

data class MobileSkillMetadata(
    val id: String,
    val version: String,
    val summary: String,
    val sourceDigest: String,
    val requiredCapabilities: Set<MobileRuntimeCapability>
) {
    init {
        require(SAFE_RUNTIME_ID.matches(id)) { "Invalid skill id" }
        require(version.isNotBlank() && version.length <= 64) { "Invalid skill version" }
        require(summary.isNotBlank() && summary.length <= 240) { "Invalid skill summary" }
        require(Regex("^sha256:[0-9a-f]{64}$").matches(sourceDigest)) { "Invalid skill source digest" }
    }
}

private val VAULT_HANDLE = Regex("^vault:[A-Za-z0-9_.:-]{8,160}$")
private val SAFE_RUNTIME_STAGE = Regex("^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
