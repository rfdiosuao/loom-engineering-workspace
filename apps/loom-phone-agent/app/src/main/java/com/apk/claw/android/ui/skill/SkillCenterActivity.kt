package com.apk.claw.android.ui.skill

import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.lifecycle.lifecycleScope
import com.apk.claw.android.R
import com.apk.claw.android.base.BaseActivity
import com.apk.claw.android.runtime.LinuxRuntimeCompanionClient
import com.apk.claw.android.skill.LinuxSkillRuntimeState
import com.apk.claw.android.skill.SkillCardModel
import com.apk.claw.android.skill.SkillCenterCatalog
import com.apk.claw.android.skill.SkillKind
import com.apk.claw.android.skill.SkillUiStatus
import com.apk.claw.android.widget.AlertDialog
import com.apk.claw.android.widget.CommonToolbar
import com.apk.claw.android.workflow.WorkflowTemplateManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class SkillCenterActivity : BaseActivity() {
    private lateinit var runtimeStatus: TextView
    private lateinit var runtimeAction: Button
    private lateinit var summary: TextView
    private lateinit var skillList: LinearLayout
    private var currentRuntimeState = LinuxSkillRuntimeState.MISSING

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_skill_center)
        findViewById<CommonToolbar>(R.id.toolbar).apply {
            setTitle(getString(R.string.skill_center_title))
            showBackButton(true) { finish() }
        }
        runtimeStatus = findViewById(R.id.tvLinuxRuntimeStatus)
        runtimeAction = findViewById(R.id.btnLinuxRuntimeAction)
        summary = findViewById(R.id.tvSkillSummary)
        skillList = findViewById(R.id.skillList)
        runtimeAction.setOnClickListener { installAndVerifyRuntime() }
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        runtimeStatus.text = getString(R.string.skill_runtime_checking)
        runtimeAction.isEnabled = false
        lifecycleScope.launch {
            currentRuntimeState = withContext(Dispatchers.IO) {
                LinuxRuntimeCompanionClient.runtimeState(this@SkillCenterActivity)
            }
            val templates = withContext(Dispatchers.IO) { WorkflowTemplateManager.getAllTemplates() }
            renderRuntime(currentRuntimeState)
            renderSkills(SkillCenterCatalog.build(templates, currentRuntimeState))
        }
    }

    private fun renderRuntime(state: LinuxSkillRuntimeState) {
        runtimeStatus.text = getString(
            when (state) {
                LinuxSkillRuntimeState.READY -> R.string.skill_runtime_ready
                LinuxSkillRuntimeState.INSTALLING -> R.string.skill_runtime_installing
                LinuxSkillRuntimeState.DAMAGED -> R.string.skill_runtime_damaged
                LinuxSkillRuntimeState.DISABLED -> R.string.skill_runtime_disabled
                LinuxSkillRuntimeState.MISSING -> R.string.skill_runtime_missing
            }
        )
        runtimeAction.text = getString(
            if (state == LinuxSkillRuntimeState.READY) {
                R.string.skill_runtime_recheck
            } else {
                R.string.skill_runtime_install
            }
        )
        runtimeAction.isEnabled = true
    }

    private fun renderSkills(cards: List<SkillCardModel>) {
        val ready = cards.count { it.callable }
        summary.text = getString(R.string.skill_center_summary, ready, cards.size)
        skillList.removeAllViews()
        cards.forEach { card -> skillList.addView(createSkillCard(card)) }
    }

    private fun createSkillCard(card: SkillCardModel): View {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(14), dp(16), dp(14))
            background = GradientDrawable().apply {
                cornerRadius = dp(14).toFloat()
                setColor(getColor(R.color.colorContainerBrighten))
                setStroke(dp(1), getColor(R.color.colorBorderBase))
            }
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = dp(12) }
        }
        container.addView(TextView(this).apply {
            text = card.title
            setTextColor(getColor(R.color.colorTextPrimary))
            textSize = 17f
            setTypeface(typeface, Typeface.BOLD)
        })
        container.addView(TextView(this).apply {
            text = statusLabel(card.status)
            setTextColor(
                getColor(if (card.callable) R.color.colorSuccessPrimary else R.color.colorWarningPrimary)
            )
            textSize = 13f
            setPadding(0, dp(5), 0, 0)
        })
        container.addView(TextView(this).apply {
            text = card.description
            setTextColor(getColor(R.color.colorTextSecondary))
            textSize = 14f
            setPadding(0, dp(7), 0, dp(10))
        })
        if (card.kind == SkillKind.LINUX) {
            container.addView(Button(this).apply {
                text = getString(R.string.skill_test_action)
                isEnabled = card.callable
                setOnClickListener { testLinuxSkill(card.id) }
            })
        } else {
            container.addView(Button(this).apply {
                text = if (card.callable) {
                    getString(R.string.skill_agent_callable)
                } else {
                    getString(R.string.skill_delete_action)
                }
                isEnabled = !card.callable
                setOnClickListener { confirmDelete(card.id, card.title) }
            })
        }
        return container
    }

    private fun installAndVerifyRuntime() {
        runtimeAction.isEnabled = false
        runtimeStatus.text = getString(R.string.skill_runtime_installing)
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                LinuxRuntimeCompanionClient.install(this@SkillCenterActivity)
            }
            Toast.makeText(
                this@SkillCenterActivity,
                if (result.success) getString(R.string.skill_runtime_install_success) else getString(
                    R.string.skill_runtime_install_failed,
                    result.code
                ),
                Toast.LENGTH_LONG
            ).show()
            refresh()
        }
    }

    private fun testLinuxSkill(skillId: String) {
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                LinuxRuntimeCompanionClient.execute(
                    skillId = skillId,
                    operation = LinuxRuntimeCompanionClient.defaultOperation(skillId),
                    input = " beta \nalpha\nalpha\n"
                )
            }
            AlertDialog.show(
                this@SkillCenterActivity,
                getString(R.string.skill_test_result_title),
                if (result.success) {
                    getString(
                        R.string.skill_test_result_success,
                        result.runtimeVersion,
                        result.durationMs,
                        result.output
                    )
                } else {
                    getString(R.string.skill_test_result_failed, result.code)
                }
            )
        }
    }

    private fun confirmDelete(skillId: String, title: String) {
        AlertDialog.showWarm(
            context = this,
            title = getString(R.string.skill_delete_title),
            message = getString(R.string.skill_delete_message, title),
            actionTitle = getString(R.string.skill_delete_action),
            onAction = {
                WorkflowTemplateManager.deleteTemplate(skillId)
                refresh()
            }
        )
    }

    private fun statusLabel(status: SkillUiStatus): String = getString(
        when (status) {
            SkillUiStatus.READY -> R.string.skill_status_ready
            SkillUiStatus.NEEDS_VALIDATION -> R.string.skill_status_needs_validation
            SkillUiStatus.DEGRADED -> R.string.skill_status_degraded
            SkillUiStatus.DISABLED -> R.string.skill_status_disabled
            SkillUiStatus.RUNTIME_REQUIRED -> R.string.skill_status_runtime_required
        }
    )

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
