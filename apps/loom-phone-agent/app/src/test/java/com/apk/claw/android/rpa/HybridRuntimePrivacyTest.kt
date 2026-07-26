package com.apk.claw.android.rpa

import com.google.gson.Gson
import com.google.gson.JsonParser
import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.SemanticSelector
import com.apk.claw.android.workflow.StepCheckpoint
import java.lang.reflect.Modifier
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class HybridRuntimePrivacyTest {
    @Test
    fun runtime_pixels_tree_and_service_identity_are_transient_to_gson() {
        val tree = JsonParser.parseString(
            """{"secretTree":"private-selector-value"}"""
        ).asJsonObject
        val evidence = UiEvidence(
            1L,
            "service-1",
            "demo.app",
            2,
            100L,
            DisplayTransform(0, 2, 2, 2, 2, 0, 320, 0, 0, 0, 0),
            tree,
            lumaPlane = LumaPlane(2, 2, intArrayOf(11, 22, 33, 44)),
            runtimeServiceIdentity = SecretIdentity("private-service-identity")
        )

        val json = Gson().toJson(evidence)

        listOf(
            "secretTree",
            "private-selector-value",
            "lumaPlane",
            "private-service-identity",
            "11",
            "44"
        ).forEach { forbidden -> assertFalse(json.contains(forbidden)) }
    }

    @Test
    fun ui_evidence_has_no_generated_copy_components_or_sensitive_public_getters() {
        assertNoDataClassSurface(UiEvidence::class.java)
        assertNoPublicMethods(
            UiEvidence::class.java,
            "getCompactTree",
            "getLumaPlane",
            "getRuntimeServiceIdentity"
        )
        assertPrivateTransientField(UiEvidence::class.java, "compactTree")
        assertPrivateTransientField(UiEvidence::class.java, "lumaPlane")
        assertPrivateTransientField(UiEvidence::class.java, "runtimeServiceIdentity")
    }

    @Test
    fun runtime_payloads_have_no_generated_copy_components_or_sensitive_public_getters() {
        listOf(
            SemanticDispatchPayload::class.java,
            VisualDispatchPayload::class.java,
            DirectPayload::class.java
        ).forEach {
            assertNoDataClassSurface(it)
            assertNoPublicMethods(
                it,
                "getExpectedServiceIdentity",
                "getPreCheckpoint",
                "getPostCheckpoint"
            )
            assertPrivateTransientField(it, "expectedServiceIdentity")
            assertPrivateTransientField(it, "preCheckpoint")
            assertPrivateTransientField(it, "postCheckpoint")
        }
        assertNoPublicMethods(
            SemanticDispatchPayload::class.java,
            "getResolution",
            "getExpectedServiceIdentity"
        )
        assertPrivateTransientField(SemanticDispatchPayload::class.java, "resolution")
    }

    @Test
    fun resolution_evidence_exposes_safe_context_without_identity_or_data_class_surface() {
        val evidence = UiEvidence(
            1L,
            "service-1",
            "demo.app",
            2,
            100L,
            DisplayTransform(0, 2, 2, 2, 2, 0, 320, 0, 0, 0, 0),
            null,
            runtimeServiceIdentity = SecretIdentity("private-service-identity")
        )
        val type = ResolutionEvidence::class.java

        assertNoDataClassSurface(type)
        assertNoPublicMethods(type, "getExpectedServiceIdentity", "getRuntimeServiceIdentity")
        assertPrivateTransientField(type, "expectedServiceIdentity")

        val json = Gson().toJson(ResolutionEvidence.from(evidence))
        assertTrue(json.contains("demo.app"))
        assertTrue(json.contains("\"windowId\":2"))
        assertFalse(json.contains("private-service-identity"))
    }

    @Test
    fun detach_failure_closes_frame_exactly_once_without_a_detached_source() {
        val frame = OwnedFrame(OwnedSource(3))
        val ownership = DetachedFrameOwnership<OwnedFrame, OwnedSource, Int>(
            detach = { throw IllegalStateException("detach failed") },
            convert = { it.value },
            dispose = OwnedSource::dispose
        )

        assertThrows(IllegalStateException::class.java) {
            ownership.capture(frame) { it }
        }

        assertEquals(1, frame.closeCount)
        assertEquals(0, frame.source.disposeCount)
    }

    @Test
    fun conversion_failure_disposes_source_and_frame_exactly_once() {
        val frame = OwnedFrame(OwnedSource(5))
        val ownership = DetachedFrameOwnership<OwnedFrame, OwnedSource, Int>(
            detach = OwnedFrame::detach,
            convert = { throw IllegalArgumentException("conversion failed") },
            dispose = OwnedSource::dispose
        )

        assertThrows(IllegalArgumentException::class.java) {
            ownership.capture(frame) { it }
        }

        assertEquals(1, frame.detachCount)
        assertEquals(1, frame.source.disposeCount)
        assertEquals(1, frame.closeCount)
    }

    @Test
    fun generation_retry_closes_each_frame_and_success_releases_each_source_once() {
        val tracker = UiGenerationTracker("service-1")
        val frames = mutableListOf<OwnedFrame>()
        val ownership = DetachedFrameOwnership<OwnedFrame, OwnedSource, Int>(
            detach = OwnedFrame::detach,
            convert = OwnedSource::value,
            dispose = OwnedSource::dispose
        )
        var attempts = 0
        val capture = GenerationBracketedCapture(
            maxAttempts = 2,
            snapshot = tracker::snapshot
        ) {
            attempts += 1
            val frame = OwnedFrame(OwnedSource(attempts)).also(frames::add)
            ownership.capture(frame) { converted ->
                if (attempts == 1) tracker.markUiChanged()
                converted ?: error("source was not converted")
            }
        }

        assertEquals(2, capture.capture())
        assertEquals(2, frames.size)
        frames.forEach { frame ->
            assertEquals(1, frame.detachCount)
            assertEquals(1, frame.source.disposeCount)
            assertEquals(1, frame.closeCount)
        }
    }

    @Test
    fun semantic_payload_does_not_serialize_selector_bearing_resolution() {
        val node = CompactNode(
            ref = "private-ref",
            resourceId = "private:id/selector",
            text = "private text",
            className = "android.widget.Button",
            packageName = "demo.app",
            bounds = IntRect(1, 2, 3, 4)
        )
        val payload = SemanticDispatchPayload(
            SemanticResolution.Unique(node, ResolverKind.RESOURCE_ID, 1L, "service-1"),
            node.bounds,
            UiEvidence(
                1L,
                "service-1",
                "demo.app",
                2,
                100L,
                DisplayTransform(0, 4, 4, 4, 4, 0, 320, 0, 0, 0, 0),
                null,
                runtimeServiceIdentity = SecretIdentity("private-service-identity")
            )
        )

        val json = Gson().toJson(payload)

        listOf("private-ref", "private:id/selector", "private text", "private-service-identity")
            .forEach { forbidden -> assertFalse(json.contains(forbidden)) }
    }

    @Test
    fun runtime_payload_checkpoints_and_exact_identity_do_not_serialize() {
        val identity = SecretIdentity("private-service-identity")
        val evidence = UiEvidence(
            1L,
            "service-1",
            "demo.app",
            2,
            100L,
            DisplayTransform(0, 4, 4, 4, 4, 0, 320, 0, 0, 0, 0),
            null,
            runtimeServiceIdentity = identity
        )
        val checkpoint = StepCheckpoint(
            requiredSelector = SemanticSelector(text = "private-checkpoint-selector")
        )
        val payloads = listOf<DispatchPayload>(
            VisualDispatchPayload(
                IntRect(0, 0, 2, 2),
                0.5f,
                0.5f,
                VisualPlatformAction.TAP,
                100L,
                evidence,
                checkpoint,
                checkpoint
            ),
            DirectPayload(
                DirectAction.OPEN_APP,
                packageName = "demo.app",
                evidence = evidence,
                preCheckpoint = checkpoint,
                postCheckpoint = checkpoint
            )
        )

        payloads.forEach { payload ->
            val json = Gson().toJson(payload)
            assertFalse(json.contains("private-service-identity"))
            assertFalse(json.contains("private-checkpoint-selector"))
        }
    }

    @Test
    fun android_decoder_bounds_first_and_recycles_decoded_bitmap() {
        val source = source("rpa/ProductionVisualChannel.kt")

        assertTrue(source.contains("inJustDecodeBounds = true"))
        assertTrue(source.indexOf("inJustDecodeBounds = true") < source.indexOf("inPreferredConfig"))
        assertTrue(source.contains("BitmapLumaAdapter.fromBitmap(bitmap)"))
        assertTrue(source.contains("if (!bitmap.isRecycled) bitmap.recycle()"))
    }

    private fun source(relative: String): String {
        val direct = java.io.File("src/main/java/com/apk/claw/android/$relative")
        return (if (direct.exists()) direct else java.io.File("app/src/main/java/com/apk/claw/android/$relative"))
            .readText()
    }

    private fun assertNoDataClassSurface(type: Class<*>) {
        val names = type.methods.map { it.name }
        assertFalse(names.any { it == "copy" || it.startsWith("copy\$") })
        assertFalse(names.any { it.matches(Regex("component[0-9]+")) })
    }

    private fun assertNoPublicMethods(type: Class<*>, vararg forbidden: String) {
        val names = type.methods.map { it.name }.toSet()
        forbidden.forEach { assertFalse("${type.simpleName} exposes $it", it in names) }
    }

    private fun assertPrivateTransientField(type: Class<*>, name: String) {
        val modifiers = type.getDeclaredField(name).modifiers
        assertTrue("$name must be private", Modifier.isPrivate(modifiers))
        assertTrue("$name must be transient", Modifier.isTransient(modifiers))
    }

    private class OwnedFrame(val source: OwnedSource) : AutoCloseable {
        var detachCount = 0
            private set
        var closeCount = 0
            private set

        fun detach(): OwnedSource {
            detachCount += 1
            return source
        }

        override fun close() {
            closeCount += 1
        }
    }

    private class OwnedSource(val value: Int) {
        var disposeCount = 0
            private set

        fun dispose() {
            disposeCount += 1
        }
    }

    private data class SecretIdentity(val value: String)
}
