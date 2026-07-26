package com.apk.claw.android.workflow

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TemplateEligibilityPolicyTest {
    @Test
    fun input_and_explicit_side_effects_are_agent_only() {
        assertEquals(
            "text_input_agent_only",
            TemplateEligibilityPolicy.evaluate(listOf(action("input_text", TemplateRiskLevel.READ_ONLY))).reason
        )
        assertEquals(
            "declared_risk_agent_only",
            TemplateEligibilityPolicy.evaluate(listOf(action("tap", TemplateRiskLevel.SIDE_EFFECT))).reason
        )
    }

    @Test
    fun gestures_require_an_explicit_read_only_risk_declaration() {
        val absent = TemplateEligibilityPolicy.evaluate(listOf(action("tap")))
        val unknown = TemplateEligibilityPolicy.evaluate(listOf(action("tap", TemplateRiskLevel.UNKNOWN)))
        val dangerous = TemplateEligibilityPolicy.evaluate(listOf(action("tap", TemplateRiskLevel.DANGEROUS)))

        assertFalse(absent.eligible)
        assertEquals(TemplateRiskLevel.UNKNOWN, absent.risk)
        assertEquals("risk_declaration_required", absent.reason)
        assertEquals("risk_declaration_required", unknown.reason)
        assertEquals("declared_risk_agent_only", dangerous.reason)
    }

    @Test
    fun full_semantic_danger_overrides_a_read_only_declaration() {
        val fromLabel = TemplateEligibilityPolicy.evaluate(
            listOf(action("tap", TemplateRiskLevel.READ_ONLY, label = "Network publish"))
        )
        val fromDescription = TemplateEligibilityPolicy.evaluate(
            listOf(action("tap", TemplateRiskLevel.READ_ONLY, label = "Network", description = "publish"))
        )
        val fromSelector = TemplateEligibilityPolicy.evaluate(
            listOf(
                action(
                    "tap",
                    TemplateRiskLevel.READ_ONLY,
                    label = "Network",
                    selector = SemanticSelector(text = "publish")
                )
            )
        )

        assertEquals("side_effect_agent_only", fromLabel.reason)
        assertEquals("side_effect_agent_only", fromDescription.reason)
        assertEquals("side_effect_agent_only", fromSelector.reason)
    }

    @Test
    fun normalized_danger_classifier_covers_agent_only_categories_and_forms() {
        val labels = listOf(
            "enter verification code",
            "authorization",
            "deletion",
            "privacy disclosure",
            "log in",
            "purchase",
            "remove account",
            "link account",
            "post",
            "share contacts",
            "l o g - i n",
            "lo\u200bg in",
            "ｌｏｇ　ｉｎ",
            "\u6388\u6743",
            "\u5220\u9664",
            "\u9690\u79c1\u62ab\u9732",
            "\u767b\u5f55",
            "\u8d2d\u4e70",
            "\u79fb\u9664\u8d26\u6237",
            "\u7ed1\u5b9a\u8d26\u6237",
            "\u53d1\u5e03",
            "\u5171\u4eab\u8054\u7cfb\u4eba"
        )

        labels.forEach { label ->
            assertEquals(
                "side_effect_agent_only",
                TemplateEligibilityPolicy.evaluate(listOf(action("tap", TemplateRiskLevel.READ_ONLY, label = label))).reason
            )
        }
    }

    @Test
    fun semantic_danger_matching_is_token_aware_and_does_not_match_safe_substrings() {
        listOf("enterprise settings", "border style").forEach { label ->
            val decision = TemplateEligibilityPolicy.evaluate(
                listOf(action("tap", TemplateRiskLevel.READ_ONLY, label = label))
            )
            assertTrue(label, decision.eligible)
        }
    }

    @Test
    fun semantic_danger_matching_collapses_obfuscated_single_letter_runs_inside_surrounding_text() {
        listOf(
            "Network l o g - i n settings",
            "Review p a y m e n t options",
            "Profile d e l e t e controls",
            "Account a u t h o r i z a t i o n settings",
            "Draft p u b l i s h controls"
        ).forEach { label ->
            assertEquals(
                label,
                "side_effect_agent_only",
                TemplateEligibilityPolicy.evaluate(listOf(action("tap", TemplateRiskLevel.READ_ONLY, label = label))).reason
            )
        }
    }

    @Test
    fun semantic_danger_matching_uses_compact_forms_after_single_letter_run_collapse() {
        listOf(
            "Network s i g n - i n settings",
            "Account l i n k - a c c o u n t options",
            "Review p l a c e - o r d e r controls",
            "Prompt v e r i f i c a t i o n - c o d e entry",
            "Directory s h a r e - c o n t a c t s controls"
        ).forEach { label ->
            assertEquals(
                label,
                "side_effect_agent_only",
                TemplateEligibilityPolicy.evaluate(listOf(action("tap", TemplateRiskLevel.READ_ONLY, label = label))).reason
            )
        }
    }

    @Test
    fun open_app_requires_explicitly_disabled_launch_dialog_for_template_eligibility() {
        val omitted = TemplateEligibilityPolicy.evaluate(
            listOf(action("open_app", TemplateRiskLevel.READ_ONLY, params = mapOf("package_name" to "com.android.settings")))
        )
        val enabled = TemplateEligibilityPolicy.evaluate(
            listOf(
                action(
                    "open_app", TemplateRiskLevel.READ_ONLY,
                    params = mapOf("package_name" to "com.android.settings", "check_launch_dialog" to true)
                )
            )
        )
        val disabled = TemplateEligibilityPolicy.evaluate(
            listOf(
                action(
                    "open_app", TemplateRiskLevel.READ_ONLY,
                    params = mapOf("package_name" to "com.android.settings", "check_launch_dialog" to false)
                )
            )
        )

        assertEquals("open_app_launch_dialog_agent_only", omitted.reason)
        assertEquals("open_app_launch_dialog_agent_only", enabled.reason)
        assertTrue(disabled.eligible)
    }

    @Test
    fun explicitly_read_only_semantic_navigation_is_eligible() {
        val decision = TemplateEligibilityPolicy.evaluate(
            listOf(
                action(
                    "open_app",
                    TemplateRiskLevel.READ_ONLY,
                    params = mapOf("package_name" to "com.android.settings", "check_launch_dialog" to false)
                ),
                action(
                    "tap",
                    TemplateRiskLevel.READ_ONLY,
                    label = "Network and internet",
                    selector = SemanticSelector(resourceId = "id/network")
                )
            )
        )

        assertTrue(decision.eligible)
        assertEquals(TemplateRiskLevel.READ_ONLY, decision.risk)
    }

    private fun action(
        toolName: String,
        risk: TemplateRiskLevel = TemplateRiskLevel.UNKNOWN,
        label: String = "",
        description: String = "",
        selector: SemanticSelector? = null,
        params: Map<String, Any?> = emptyMap()
    ) = TrajectoryAction(
        toolId = "tool-1",
        toolName = toolName,
        params = params,
        success = true,
        safetyLabel = label,
        riskDeclaration = risk,
        description = description,
        semanticSelector = selector
    )
}
