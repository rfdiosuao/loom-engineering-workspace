package com.apk.claw.android.workflow

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class WorkflowTemplateStoreTest {
    private lateinit var tempDir: File

    @Before
    fun setUp() {
        tempDir = Files.createTempDirectory("workflow-template-store").toFile()
    }

    @After
    fun tearDown() {
        tempDir.deleteRecursively()
    }

    @Test
    fun legacy_template_migrates_to_degraded_and_never_matches_active() {
        val store = WorkflowTemplateStore(tempDir)
        File(tempDir, "template_index.json").writeText(legacyJsonWithoutLifecycle)

        val template = store.load().single()

        assertEquals(2, template.schemaVersion)
        assertEquals(TemplateStatus.DEGRADED, template.status)
        assertEquals(0, template.validationState.consecutiveSuccesses)
    }

    @Test
    fun load_recovers_backup_when_target_is_missing() {
        val store = WorkflowTemplateStore(tempDir)
        File(tempDir, "template_index.json.bak").writeText(legacyJsonWithoutLifecycle)

        val templates = store.load()

        assertEquals("legacy-template", templates.single().id)
        assertTrue(File(tempDir, "template_index.json").exists())
        assertFalse(File(tempDir, "template_index.json.bak").exists())
    }

    @Test
    fun v2_validation_target_is_normalized_to_three_on_load() {
        listOf(0, 1, 2, 4).forEach { target ->
            File(tempDir, "template_index.json").writeText(v2Json(validationTarget = target))

            assertEquals(3, WorkflowTemplateStore(tempDir).load().single().validationState.target)
        }
    }

    @Test
    fun malformed_template_fails_the_entire_load_without_dropping_source_data() {
        val source = "[\"not-a-template\", ${v2Json().trim().removePrefix("[").removeSuffix("]")}]"
        val index = File(tempDir, "template_index.json").apply { writeText(source) }

        assertLoadFails(WorkflowTemplateStore(tempDir), "invalid_template")
        assertEquals(source, index.readText())
    }

    @Test
    fun malformed_primary_step_fails_closed_instead_of_preserving_an_active_partial_template() {
        File(tempDir, "template_index.json").writeText(v2Json(steps = """[{"paramsTemplate": {}, "description": "missing tool"}]"""))

        assertLoadFails(WorkflowTemplateStore(tempDir), "invalid_primary_step")
    }

    @Test
    fun malformed_fallback_step_fails_closed_instead_of_preserving_an_active_partial_template() {
        val steps = """
            [{
              "toolName": "tap",
              "paramsTemplate": {},
              "description": "Tap",
              "failureHandling": {
                "fallbackSteps": [{"paramsTemplate": {}, "description": "missing fallback tool"}]
              }
            }]
        """.trimIndent()
        File(tempDir, "template_index.json").writeText(v2Json(steps = steps))

        assertLoadFails(WorkflowTemplateStore(tempDir), "invalid_fallback_step")
    }

    @Test
    fun save_round_trips_v2_template_without_leaving_pending_or_backup_files() {
        val store = WorkflowTemplateStore(tempDir)
        val template = testTemplate("round-trip")

        store.save(listOf(template))

        assertEquals(listOf(template), store.load())
        assertFalse(File(tempDir, "template_index.json.tmp").exists())
        assertFalse(File(tempDir, "template_index.json.bak").exists())
    }

    @Test
    fun schema_v2_coordinate_checkpoint_round_trips_across_process_restart() {
        val fingerprint = "pf2:${"0".repeat(64)}:80:10:0000000000000000"
        val checkpoint = StepCheckpoint(
            expectedPackage = "com.example",
            perceptualHash = fingerprint,
            maximumHammingDistance = 8,
            expectedWindowId = 7,
            expectedDisplayTransform = DisplayTransformCheckpoint(
                displayId = 0,
                widthPx = 1080,
                heightPx = 1920,
                screenshotWidthPx = 1080,
                screenshotHeightPx = 1920,
                rotation = 0,
                densityDpi = 420,
                insetLeft = 0,
                insetTop = 24,
                insetRight = 0,
                insetBottom = 48
            )
        )
        val coordinateStep = WorkflowTemplate.WorkflowStep(
            toolName = "tap_normalized",
            paramsTemplate = mapOf("x" to 0.5, "y" to 0.5),
            description = "Tap coordinate",
            resolverPolicy = ResolverPolicy.TREE_PREFERRED,
            allowedResolvers = setOf(ResolverKind.RESOURCE_ID, ResolverKind.NORMALIZED_COORDINATE),
            validatedResolvers = setOf(ResolverKind.RESOURCE_ID, ResolverKind.NORMALIZED_COORDINATE),
            semanticSelector = SemanticSelector(resourceId = "com.example:id/missing"),
            preCheckpoint = checkpoint
        )
        val template = testTemplate("coordinate-round-trip").copy(steps = listOf(coordinateStep))

        WorkflowTemplateStore(tempDir).save(listOf(template))
        val reloaded = WorkflowTemplateStore(tempDir).load().single()

        assertEquals(template, reloaded)
        assertEquals(fingerprint, reloaded.steps.single().preCheckpoint!!.perceptualHash)
        assertEquals(7, reloaded.steps.single().preCheckpoint!!.expectedWindowId)
        assertEquals(checkpoint.expectedDisplayTransform, reloaded.steps.single().preCheckpoint!!.expectedDisplayTransform)
        assertTrue(ResolverKind.NORMALIZED_COORDINATE in reloaded.steps.single().validatedResolvers)
        assertEquals(TemplateStatus.ACTIVE, reloaded.status)
    }

    @Test
    fun malformed_persisted_coordinate_context_fails_closed_but_missing_context_keeps_legacy_defaults() {
        val validDisplay = """
            {"displayId":0,"widthPx":1080,"heightPx":1920,
             "screenshotWidthPx":1080,"screenshotHeightPx":1920,
             "rotation":0,"densityDpi":420,
             "insetLeft":0,"insetTop":24,"insetRight":0,"insetBottom":48}
        """.trimIndent()
        val malformed = listOf(
            """"expectedWindowId":"7"""",
            """"expectedWindowId":-1""",
            """"expectedWindowId":1000001""",
            """"expectedWindowId":7,"expectedDisplayTransform":"wrong"""",
            """"expectedWindowId":7,"expectedDisplayTransform":{"displayId":0}""",
            """"expectedWindowId":7,"expectedDisplayTransform":${validDisplay.replace("\"rotation\":0", "\"rotation\":4")}""",
            """"expectedWindowId":7,"expectedDisplayTransform":${validDisplay.replace("\"insetLeft\":0", "\"insetLeft\":1080")}"""
        )
        malformed.forEach { context ->
            val steps = """
                [{"toolName":"tap_normalized","paramsTemplate":{},"description":"Tap",
                  "preCheckpoint":{$context}}]
            """.trimIndent()
            File(tempDir, "template_index.json").writeText(v2Json(steps = steps))

            assertLoadFails(WorkflowTemplateStore(tempDir), "invalid_primary_step")
            File(tempDir, "template_index.json").delete()
        }

        File(tempDir, "template_index.json").writeText(
            v2Json(steps = """[{"toolName":"tap","paramsTemplate":{},"description":"Legacy checkpoint","preCheckpoint":{"expectedPackage":"com.example"}}]""")
        )
        val legacyCheckpoint = WorkflowTemplateStore(tempDir).load().single().steps.single().preCheckpoint!!
        assertEquals(null, legacyCheckpoint.expectedWindowId)
        assertEquals(null, legacyCheckpoint.expectedDisplayTransform)
    }

    @Test
    fun corrupt_primary_recovers_valid_backup() {
        val store = WorkflowTemplateStore(tempDir)
        store.save(listOf(testTemplate("backup-template")))
        val target = File(tempDir, "template_index.json")
        target.copyTo(File(tempDir, "template_index.json.bak"))
        target.writeText("{not valid json")

        assertEquals("backup-template", store.load().single().id)
    }

    @Test
    fun future_schema_is_rejected_without_rewriting_it() {
        val source = v2Json(schemaVersion = 3)
        val index = File(tempDir, "template_index.json").apply { writeText(source) }

        assertLoadFails(WorkflowTemplateStore(tempDir), "unsupported_schema_version")
        assertEquals(source, index.readText())
    }

    @Test
    fun store_source_has_no_api26_files_move_dependency() {
        val source = generateSequence(File(System.getProperty("user.dir").orEmpty())) { it.parentFile }
            .map { directory -> File(directory, "app/src/main/java/com/apk/claw/android/workflow/WorkflowTemplateStore.kt") }
            .first { it.isFile }
            .readText()

        assertFalse(source.contains("java.nio.file.Files"))
        assertFalse(source.contains("Files.move"))
    }

    @Test
    fun unknown_step_resolver_policy_fails_closed() {
        val steps = """[{"toolName": "tap", "paramsTemplate": {}, "description": "Tap", "resolverPolicy": "UNKNOWN"}]"""
        File(tempDir, "template_index.json").writeText(v2Json(steps = steps))

        assertLoadFails(WorkflowTemplateStore(tempDir), "invalid_primary_step")
    }

    @Test
    fun unknown_default_resolver_policy_fails_closed() {
        val source = v2Json().replace(
            "\"status\": \"ACTIVE\",",
            "\"status\": \"ACTIVE\", \"defaultResolverPolicy\": \"UNKNOWN\","
        )
        File(tempDir, "template_index.json").writeText(source)

        assertLoadFails(WorkflowTemplateStore(tempDir), "invalid_template")
    }

    @Test
    fun unknown_resolver_kind_fails_closed() {
        val steps = """[{"toolName": "tap", "paramsTemplate": {}, "description": "Tap", "allowedResolvers": ["UNKNOWN"]}]"""
        File(tempDir, "template_index.json").writeText(v2Json(steps = steps))

        assertLoadFails(WorkflowTemplateStore(tempDir), "invalid_primary_step")
    }

    @Test
    fun wrong_type_checkpoint_fails_closed() {
        val steps = """[{"toolName": "tap", "paramsTemplate": {}, "description": "Tap", "preCheckpoint": "not-an-object"}]"""
        File(tempDir, "template_index.json").writeText(v2Json(steps = steps))

        assertLoadFails(WorkflowTemplateStore(tempDir), "invalid_primary_step")
    }

    @Test
    fun wrong_type_semantic_selector_fails_closed() {
        val steps = """[{"toolName": "tap", "paramsTemplate": {}, "description": "Tap", "semanticSelector": []}]"""
        File(tempDir, "template_index.json").writeText(v2Json(steps = steps))

        assertLoadFails(WorkflowTemplateStore(tempDir), "invalid_primary_step")
    }

    @Test
    fun malformed_visual_anchor_and_post_checkpoint_fail_closed() {
        val visualSteps = """
            [{"toolName": "tap", "paramsTemplate": {}, "description": "Tap",
              "visualAnchor": {"assetName": "anchor", "searchRegion": "wrong", "tapOffsetX": 0, "tapOffsetY": 0}}]
        """.trimIndent()
        File(tempDir, "template_index.json").writeText(v2Json(steps = visualSteps))
        assertLoadFails(WorkflowTemplateStore(tempDir), "invalid_primary_step")

        val checkpointSteps = """[{"toolName": "tap", "paramsTemplate": {}, "description": "Tap", "postCheckpoint": []}]"""
        File(tempDir, "template_index.json").writeText(v2Json(steps = checkpointSteps))
        assertLoadFails(WorkflowTemplateStore(tempDir), "invalid_primary_step")
    }

    @Test
    fun recovery_promotes_backup_before_an_interrupted_save() {
        val store = WorkflowTemplateStore(tempDir)
        store.save(listOf(testTemplate("committed-template")))
        val target = File(tempDir, "template_index.json")
        target.copyTo(File(tempDir, "template_index.json.bak"))
        target.writeText("{not valid json")

        assertEquals("committed-template", store.load().single().id)
        assertTrue(File(tempDir, "template_index.json.corrupt").exists())
        assertFalse(File(tempDir, "template_index.json.bak").exists())

        val interruptedStore = WorkflowTemplateStore(tempDir, rename = { source, destination ->
            if (source.name.endsWith(".tmp")) false else source.renameTo(destination)
        })
        try {
            interruptedStore.save(listOf(testTemplate("new-template")))
            fail("Expected simulated target installation interruption")
        } catch (error: IllegalStateException) {
            assertTrue(error.message.orEmpty().contains("template_index_replace_failed"))
        }

        assertEquals("committed-template", store.load().single().id)
    }

    @Test
    fun separate_store_instances_serialize_load_with_atomic_save() {
        WorkflowTemplateStore(tempDir).save(listOf(testTemplate("old-template")))
        val primaryMoved = CountDownLatch(1)
        val allowInstall = CountDownLatch(1)
        val writerFailure = AtomicReference<Throwable?>()
        val readerFailure = AtomicReference<Throwable?>()
        val readerResult = AtomicReference<List<WorkflowTemplate>?>()
        val writer = WorkflowTemplateStore(tempDir, rename = { source, destination ->
            val moved = source.renameTo(destination)
            if (source.name == "template_index.json" && destination.name.endsWith(".bak") && moved) {
                primaryMoved.countDown()
                check(allowInstall.await(5, TimeUnit.SECONDS))
            }
            moved
        })
        val reader = WorkflowTemplateStore(tempDir)

        val writerThread = Thread {
            runCatching { writer.save(listOf(testTemplate("new-template"))) }
                .onFailure(writerFailure::set)
        }
        writerThread.start()
        assertTrue(primaryMoved.await(5, TimeUnit.SECONDS))
        val readerThread = Thread {
            runCatching { reader.load() }
                .onSuccess(readerResult::set)
                .onFailure(readerFailure::set)
        }
        readerThread.start()
        Thread.sleep(100L)
        assertTrue("reader must wait for the in-flight save", readerThread.isAlive)

        allowInstall.countDown()
        writerThread.join(5_000L)
        readerThread.join(5_000L)

        assertFalse(writerThread.isAlive)
        assertFalse(readerThread.isAlive)
        assertEquals(null, writerFailure.get())
        assertEquals(null, readerFailure.get())
        assertEquals("new-template", readerResult.get()!!.single().id)
        assertEquals("new-template", WorkflowTemplateStore(tempDir).load().single().id)
    }

    private fun assertLoadFails(store: WorkflowTemplateStore, expectedCode: String) {
        try {
            store.load()
            fail("Expected store load to fail with $expectedCode")
        } catch (error: IllegalStateException) {
            assertTrue(error.message.orEmpty().contains(expectedCode))
        }
    }

    private fun testTemplate(id: String): WorkflowTemplate = WorkflowTemplate(
        id = id,
        name = id,
        description = "test",
        taskPattern = "open settings",
        keywords = listOf("settings"),
        appName = null,
        steps = listOf(WorkflowTemplate.WorkflowStep("tap", emptyMap(), "Tap")),
        createdAt = 1L,
        lastUsedAt = 2L,
        successCount = 3,
        failCount = 0,
        status = TemplateStatus.ACTIVE,
        validationState = ValidationState(profileId = "emulator", validatedRevision = 1)
    )

    private fun v2Json(
        steps: String = """[{"toolName": "tap", "paramsTemplate": {}, "description": "Tap"}]""",
        validationTarget: Int = 3,
        schemaVersion: Int = 2
    ): String = """
        [
          {
            "id": "v2-template",
            "name": "V2 template",
            "description": "V2 template",
            "taskPattern": "open settings",
            "keywords": ["settings"],
            "steps": $steps,
            "createdAt": 1,
            "lastUsedAt": 2,
            "successCount": 0,
            "failCount": 0,
            "schemaVersion": $schemaVersion,
            "status": "ACTIVE",
            "validationState": {
              "target": $validationTarget,
              "profileId": "emulator",
              "validatedRevision": 1
            },
            "revision": 1
          }
        ]
    """.trimIndent()

    companion object {
        private const val legacyJsonWithoutLifecycle = """
            [
              {
                "id": "legacy-template",
                "name": "Legacy template",
                "description": "Created before lifecycle support",
                "taskPattern": "legacy.*",
                "keywords": ["legacy"],
                "steps": [
                  {
                    "toolName": "tap",
                    "paramsTemplate": { "x": 1, "y": 2 },
                    "description": "Tap",
                    "waitFor": 0,
                    "isVerification": false
                  }
                ],
                "createdAt": 1,
                "lastUsedAt": 2,
                "successCount": 5,
                "failCount": 0
              }
            ]
        """
    }
}
