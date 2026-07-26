package com.apk.claw.android.workflow

import java.text.Normalizer
import java.util.Locale

data class EligibilityDecision(
    val eligible: Boolean,
    val risk: TemplateRiskLevel,
    val reason: String = ""
)

enum class SemanticDangerCategory {
    TEXT_OR_VERIFICATION_INPUT,
    PAYMENT_OR_PURCHASE,
    DELETION_OR_ACCOUNT_REMOVAL,
    LOGIN_OR_AUTHORIZATION,
    ACCOUNT_BINDING,
    PRIVACY_OR_DEVICE_SHARING,
    PUBLISH_OR_COMMUNICATION
}

object SemanticDangerClassifier {
    private val latinPhrases = mapOf(
        SemanticDangerCategory.TEXT_OR_VERIFICATION_INPUT to setOf(
            "text input", "input text", "type text", "enter password", "enter verification code", "password",
            "verification code", "one time password", "otp", "captcha"
        ),
        SemanticDangerCategory.PAYMENT_OR_PURCHASE to setOf(
            "payment", "pay", "purchase", "checkout", "place order", "order", "subscription", "subscribe", "buy"
        ),
        SemanticDangerCategory.DELETION_OR_ACCOUNT_REMOVAL to setOf(
            "delete", "deletion", "remove", "erase", "clear", "remove account", "account removal", "close account"
        ),
        SemanticDangerCategory.LOGIN_OR_AUTHORIZATION to setOf(
            "login", "log in", "sign in", "authorize", "authorization", "permission", "consent", "oauth"
        ),
        SemanticDangerCategory.ACCOUNT_BINDING to setOf(
            "bind", "binding", "link account", "account link", "connect account", "account connect"
        ),
        SemanticDangerCategory.PRIVACY_OR_DEVICE_SHARING to setOf(
            "privacy", "disclose", "disclosure", "share contacts", "share location", "contact access", "location access",
            "camera access", "microphone access", "contacts permission", "location permission"
        ),
        SemanticDangerCategory.PUBLISH_OR_COMMUNICATION to setOf(
            "publish", "post", "share", "send", "upload", "submit", "comment", "reply", "forward"
        )
    )

    private val cjkPhrases = mapOf(
        SemanticDangerCategory.TEXT_OR_VERIFICATION_INPUT to setOf(
            "\u8f93\u5165", "\u8f93\u5165\u6587\u672c", "\u8f93\u5165\u5bc6\u7801", "\u5bc6\u7801", "\u9a8c\u8bc1\u7801", "\u9a8c\u8bc1"
        ),
        SemanticDangerCategory.PAYMENT_OR_PURCHASE to setOf(
            "\u652f\u4ed8", "\u4ed8\u6b3e", "\u8d2d\u4e70", "\u4e0b\u5355", "\u8ba2\u9605", "\u7ed3\u8d26"
        ),
        SemanticDangerCategory.DELETION_OR_ACCOUNT_REMOVAL to setOf(
            "\u5220\u9664", "\u79fb\u9664", "\u6e05\u9664", "\u64a4\u9500", "\u6ce8\u9500", "\u79fb\u9664\u8d26\u6237"
        ),
        SemanticDangerCategory.LOGIN_OR_AUTHORIZATION to setOf(
            "\u767b\u5f55", "\u767b\u5165", "\u6388\u6743", "\u6743\u9650", "\u540c\u610f", "\u8ba4\u8bc1"
        ),
        SemanticDangerCategory.ACCOUNT_BINDING to setOf(
            "\u7ed1\u5b9a", "\u5173\u8054", "\u8fde\u63a5\u8d26\u6237", "\u7ed1\u5b9a\u8d26\u6237"
        ),
        SemanticDangerCategory.PRIVACY_OR_DEVICE_SHARING to setOf(
            "\u9690\u79c1", "\u62ab\u9732", "\u5171\u4eab\u8054\u7cfb\u4eba", "\u5171\u4eab\u4f4d\u7f6e", "\u8054\u7cfb\u4eba", "\u901a\u8baf\u5f55", "\u4f4d\u7f6e", "\u76f8\u673a", "\u6444\u50cf\u5934", "\u9ea6\u514b\u98ce"
        ),
        SemanticDangerCategory.PUBLISH_OR_COMMUNICATION to setOf(
            "\u53d1\u5e03", "\u53d1\u5e16", "\u5206\u4eab", "\u53d1\u9001", "\u4e0a\u4f20", "\u63d0\u4ea4", "\u8bc4\u8bba", "\u56de\u590d", "\u8f6c\u53d1"
        )
    )

    fun classify(semantics: String): Set<SemanticDangerCategory> {
        val normalized = normalize(semantics)
        val latinTokens = Regex("[a-z0-9]+")
            .findAll(normalized)
            .map { it.value }
            .toList()
        val collapsedTokens = collapseSingleLetterRuns(latinTokens)
        val tokenStream = collapsedTokens.joinToString(" ")
        return SemanticDangerCategory.entries.filterTo(linkedSetOf()) { category ->
            latinPhrases.getValue(category).any { phrase ->
                matchesLatinPhrase(phrase, collapsedTokens, tokenStream)
            } || cjkPhrases.getValue(category).any(normalized::contains)
        }
    }

    private fun collapseSingleLetterRuns(tokens: List<String>): List<String> {
        val collapsed = mutableListOf<String>()
        var index = 0
        while (index < tokens.size) {
            if (tokens[index].length != 1 || tokens[index].single() !in 'a'..'z') {
                collapsed += tokens[index++]
                continue
            }
            val run = StringBuilder()
            while (index < tokens.size && tokens[index].length == 1 && tokens[index].single() in 'a'..'z') {
                run.append(tokens[index++])
            }
            collapsed += run.toString()
        }
        return collapsed
    }

    private fun matchesLatinPhrase(
        phrase: String,
        tokens: List<String>,
        tokenStream: String
    ): Boolean {
        val phraseTokens = phrase.split(' ')
        val compactPhrase = phrase.replace(" ", "")
        if (compactPhrase in tokens) return true
        if (phraseTokens.size == 1 && phraseTokens.single() in tokens) return true
        return phrase in tokenStream.split(' ').windowed(phraseTokens.size).map { it.joinToString(" ") }
    }

    private fun normalize(value: String): String {
        val nfkc = Normalizer.normalize(value, Normalizer.Form.NFKC).lowercase(Locale.ROOT)
        return buildString(nfkc.length) {
            nfkc.forEach { character ->
                when (Character.getType(character)) {
                    Character.FORMAT.toInt(), Character.NON_SPACING_MARK.toInt(),
                    Character.COMBINING_SPACING_MARK.toInt(), Character.ENCLOSING_MARK.toInt() -> Unit
                    else -> append(character)
                }
            }
        }
    }
}

object TemplateEligibilityPolicy {
    private val textTools = setOf("input_text", "clipboard")
    private val recorderReadOnlyTools = setOf("wait", "take_screenshot", "get_screen_info", "finish")
    private val safeTools = setOf(
        "open_app", "tap", "swipe", "drag", "long_press", "system_key", "wait",
        "take_screenshot", "get_screen_info", "finish"
    )

    fun evaluate(actions: List<TrajectoryAction>): EligibilityDecision {
        if (actions.any { it.toolName in textTools }) {
            return EligibilityDecision(false, TemplateRiskLevel.SIDE_EFFECT, "text_input_agent_only")
        }
        if (actions.any { it.toolName !in safeTools }) {
            return EligibilityDecision(false, TemplateRiskLevel.UNKNOWN, "unsupported_or_unknown_tool")
        }
        if (actions.any { SemanticDangerClassifier.classify(actionSemantics(it)).isNotEmpty() }) {
            return EligibilityDecision(false, TemplateRiskLevel.SIDE_EFFECT, "side_effect_agent_only")
        }
        if (actions.any { !it.success }) {
            return EligibilityDecision(false, TemplateRiskLevel.UNKNOWN, "trajectory_contains_failed_action")
        }
        if (actions.any { it.toolName == "open_app" && it.params["check_launch_dialog"] != false }) {
            return EligibilityDecision(false, TemplateRiskLevel.UNKNOWN, "open_app_launch_dialog_agent_only")
        }
        val nonReadOnly = actions.firstOrNull { it.riskDeclaration != TemplateRiskLevel.READ_ONLY }
        if (nonReadOnly != null) {
            val reason = if (nonReadOnly.riskDeclaration == TemplateRiskLevel.UNKNOWN) {
                "risk_declaration_required"
            } else {
                "declared_risk_agent_only"
            }
            return EligibilityDecision(false, nonReadOnly.riskDeclaration, reason)
        }
        return EligibilityDecision(true, TemplateRiskLevel.READ_ONLY)
    }

    internal fun classifyRecordedRisk(
        toolName: String,
        params: Map<String, Any?>,
        declaredRisk: TemplateRiskLevel?,
        safetyLabel: String,
        description: String,
        selector: SemanticSelector?
    ): TemplateRiskLevel {
        if (SemanticDangerClassifier.classify(actionSemantics(safetyLabel, description, selector)).isNotEmpty()) {
            return TemplateRiskLevel.SIDE_EFFECT
        }
        if (declaredRisk != null) return declaredRisk
        return when {
            toolName == "open_app" && params["check_launch_dialog"] == false -> TemplateRiskLevel.READ_ONLY
            toolName in recorderReadOnlyTools -> TemplateRiskLevel.READ_ONLY
            else -> TemplateRiskLevel.UNKNOWN
        }
    }

    private fun actionSemantics(action: TrajectoryAction): String =
        actionSemantics(action.safetyLabel, action.description, action.semanticSelector)

    private fun actionSemantics(
        safetyLabel: String,
        description: String,
        selector: SemanticSelector?
    ): String = buildList {
        add(safetyLabel)
        add(description)
        selector?.let {
            add(it.resourceId.orEmpty())
            add(it.contentDescription.orEmpty())
            add(it.text.orEmpty())
            add(it.className.orEmpty())
            add(it.packageName.orEmpty())
        }
    }.joinToString("\n")
}
