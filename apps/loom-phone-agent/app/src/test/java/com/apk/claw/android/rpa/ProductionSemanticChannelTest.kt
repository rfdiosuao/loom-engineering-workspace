package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.ResolverPolicy
import com.apk.claw.android.workflow.SemanticSelector
import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ProductionSemanticChannelTest {
    @Test
    fun unique_generation_tagged_compact_node_becomes_bounded_runtime_payload() {
        val identity = Any()
        val evidence = evidence(identity = identity)
        val result = ProductionSemanticChannel(clock = ticks(10L, 14L)).resolve(
            ResolverKind.RESOURCE_ID,
            semanticStep(),
            evidence
        ) as Resolution.Ready

        val payload = result.payload as SemanticDispatchPayload
        assertEquals(ResolverKind.RESOURCE_ID, result.resolverUsed)
        assertEquals(IntRect(10, 20, 110, 70), payload.bounds)
        assertEquals(ResolverKind.RESOURCE_ID, payload.resolutionForDispatch(evidence)?.matchedBy)
        assertTrue(payload.sameServiceIdentity(evidence))
        assertFalse(payload.sameServiceIdentity(evidence(identity = Any())))
        assertEquals(evidence.packageName, result.evidence.packageName)
        assertEquals(evidence.windowId, result.evidence.windowId)
        assertTrue(result.evidence.matches(evidence))
        assertFalse(result.evidence.matches(evidence(identity = Any())))
        assertFalse(result.evidence.matches(evidence(windowId = evidence.windowId + 1, identity = identity)))
        assertFalse(result.evidence.matches(evidence(evidencePackage = "other.app", identity = identity)))
        assertEquals(1, result.metrics.nodesVisited)
        assertEquals(4L, result.metrics.treeLookupMs)
    }

    @Test
    fun malformed_ambiguous_and_stale_compact_evidence_never_becomes_coordinates() {
        val channel = ProductionSemanticChannel()
        val malformed = evidence(treeJson = "{}")
        val ambiguous = evidence(nodeCount = 2)
        val stale = evidence(treeGeneration = 6L)

        assertEquals(
            ProductionSemanticChannel.ERROR_COMPACT_TREE_INVALID,
            (channel.resolve(ResolverKind.RESOURCE_ID, semanticStep(), malformed) as Resolution.Handoff).errorCode
        )
        assertTrue(channel.resolve(ResolverKind.RESOURCE_ID, semanticStep(), ambiguous) is Resolution.Ambiguous)
        assertEquals(
            ProductionSemanticChannel.ERROR_COMPACT_TREE_INVALID,
            (channel.resolve(ResolverKind.RESOURCE_ID, semanticStep(), stale) as Resolution.Handoff).errorCode
        )
    }

    @Test
    fun description_and_text_class_resolvers_are_resolved_independently() {
        val channel = ProductionSemanticChannel()
        val descriptionStep = semanticStep().copy(
            allowedResolvers = setOf(ResolverKind.CONTENT_DESCRIPTION),
            validatedResolvers = setOf(ResolverKind.CONTENT_DESCRIPTION),
            semanticSelector = SemanticSelector(contentDescription = "Target", packageName = "demo.app")
        )
        val textStep = semanticStep().copy(
            allowedResolvers = setOf(ResolverKind.TEXT_CLASS),
            validatedResolvers = setOf(ResolverKind.TEXT_CLASS),
            semanticSelector = SemanticSelector(
                text = "Target",
                className = "android.widget.Button",
                packageName = "demo.app"
            )
        )

        assertEquals(
            ResolverKind.CONTENT_DESCRIPTION,
            (channel.resolve(ResolverKind.CONTENT_DESCRIPTION, descriptionStep, evidence()) as Resolution.Ready).resolverUsed
        )
        assertEquals(
            ResolverKind.TEXT_CLASS,
            (channel.resolve(ResolverKind.TEXT_CLASS, textStep, evidence()) as Resolution.Ready).resolverUsed
        )
    }

    @Test
    fun package_window_identity_and_target_bounds_must_be_valid() {
        val channel = ProductionSemanticChannel()
        val packageMismatch = evidence(treePackage = "other.app")
        val missingIdentity = evidence(identity = null)
        val missingWindow = evidence(windowId = -1)
        val outOfBounds = evidence(bounds = IntRect(10, 20, 210, 70))

        listOf(packageMismatch, missingIdentity, missingWindow).forEach { invalid ->
            assertEquals(
                ProductionSemanticChannel.ERROR_COMPACT_TREE_INVALID,
                (channel.resolve(ResolverKind.RESOURCE_ID, semanticStep(), invalid) as Resolution.Handoff).errorCode
            )
        }
        assertEquals(
            ProductionSemanticChannel.ERROR_SEMANTIC_BOUNDS_INVALID,
            (channel.resolve(ResolverKind.RESOURCE_ID, semanticStep(), outOfBounds) as Resolution.Handoff).errorCode
        )
    }

    @Test
    fun structural_and_nonsemantic_actions_are_explicit_handoffs() {
        val channel = ProductionSemanticChannel()
        val structural = semanticStep().copy(
            semanticSelector = SemanticSelector(structuralPath = listOf(0, 1)),
            allowedResolvers = setOf(ResolverKind.STRUCTURAL),
            validatedResolvers = setOf(ResolverKind.STRUCTURAL)
        )

        assertEquals(
            ProductionSemanticChannel.ERROR_STRUCTURAL_PATH_UNVERIFIABLE,
            (channel.resolve(ResolverKind.STRUCTURAL, structural, evidence()) as Resolution.Handoff).errorCode
        )
        assertEquals(
            ProductionSemanticChannel.ERROR_ACTION_ADAPTER_UNAVAILABLE,
            (
                channel.resolve(
                    ResolverKind.RESOURCE_ID,
                    semanticStep().copy(action = "assert_semantic"),
                    evidence()
                ) as Resolution.Handoff
                ).errorCode
        )
    }

    private fun semanticStep() = RpaStep(
        id = "step-1",
        action = "tap_semantic",
        resolverPolicy = ResolverPolicy.TREE_PREFERRED,
        allowedResolvers = setOf(ResolverKind.RESOURCE_ID),
        validatedResolvers = setOf(ResolverKind.RESOURCE_ID),
        semanticSelector = SemanticSelector(resourceId = "demo:id/target", packageName = "demo.app")
    )

    private fun evidence(
        identity: Any? = Any(),
        treeJson: String? = null,
        nodeCount: Int = 1,
        treeGeneration: Long = 7L,
        treePackage: String = "demo.app",
        evidencePackage: String = "demo.app",
        windowId: Int = 3,
        bounds: IntRect = IntRect(10, 20, 110, 70)
    ): UiEvidence {
        val nodes = (0 until nodeCount).joinToString(",") { index ->
            """{
              "ref":"node-$index","resourceId":"demo:id/target","description":"Target","text":"Target",
              "className":"android.widget.Button","packageName":"demo.app","visible":true,
              "enabled":true,"clickable":true,"bounds":{"left":${bounds.left},"top":${bounds.top},"right":${bounds.right},"bottom":${bounds.bottom}}
            }"""
        }
        val tree = treeJson ?: """{
          "currentPackage":"$treePackage",
          "metrics":{"uiGeneration":$treeGeneration,"serviceGeneration":"service-1"},
          "keyNodes":[$nodes]
        }"""
        return UiEvidence(
            uiGeneration = 7L,
            serviceGeneration = "service-1",
            packageName = evidencePackage,
            windowId = windowId,
            capturedAt = 1_000L,
            transform = DisplayTransform(0, 200, 300, 200, 300, 0, 420, 0, 0, 0, 0),
            compactTree = JsonParser.parseString(tree).asJsonObject,
            runtimeServiceIdentity = identity
        )
    }

    private fun ticks(vararg values: Long): () -> Long {
        val iterator = values.iterator()
        return { if (iterator.hasNext()) iterator.next() else values.last() }
    }
}
