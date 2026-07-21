---
name: luming-phone-agent
description: Use when a user asks LOOM/Luming/麓鸣 to operate one or more phones, discover what phones can do, build a new mobile App task, reuse a previously verified task recipe, supervise a phone matrix, automatically publish, comment, or private-message, screen BOSS直聘 resumes, run acquisition work, or report missing App/account/login/membership/permission prerequisites.
  It also routes scenario Skill creation and update from observed App routes through this unified Skill.
---

# Luming Phone Agent

Use this as the single operational entrypoint for phone work. Do not modify LOOM product code. Resolve real capabilities from the installed command catalog first; never invent CLI commands, routes, device IDs, or successful evidence.

## State Machine

Advance in this exact order. Do not skip a state, except that a blocking result resumes at the named resumeFrom state after its prerequisite is resolved.

SELF_CHECK
-> PHONE_DISCOVERY
-> ASK_TASK
-> RECIPE_MATCH
-> PREFLIGHT
-> REUSE_OR_EXPLORE
-> PLAN
-> EXECUTE_VERIFY
-> SYNC_RECIPE
-> REPORT

Load only the reference needed for the current state. Keep evidence, blockers, selected devices, and recovery checkpoints in the run record.

| State | Required action | Load only this reference |
| --- | --- | --- |
| SELF_CHECK | Check local control-plane, service, recipe storage, bundled ADB, and safe low-risk repairs. | [environment preflight](references/environment-preflight.md), [LOOM capability map](references/loom-capability-map.md) |
| PHONE_DISCOVERY | Read actual healthy, busy, controllable, App, and page state from discovered capabilities. | [phone discovery](references/phone-discovery.md) |
| ASK_TASK | Confirm a normalized goal after discovery; ASK_TASK follows PHONE_DISCOVERY. | [phone discovery](references/phone-discovery.md) |
| RECIPE_MATCH | Match only recipes that pass status == verified, verification.successCount >= 1, and non-empty evidence for every route step; assess App/version/page-fingerprint freshness. | [task compiler](references/task-compiler.md) |
| PREFLIGHT | Check the task-specific App, account, session, entitlement, permission, network, region, version, and data prerequisites. | [environment preflight](references/environment-preflight.md) |
| REUSE_OR_EXPLORE | Reuse a revalidated verified recipe or explore a bounded new/stale route safely. | [safe navigation](references/safe-navigation.md) |
| PLAN | Produce an evidence-linked single-device or matrix plan; load task compiler for every plan and built-in playbooks for BOSS or acquisition. | [task compiler](references/task-compiler.md), [built-in playbooks](references/builtin-playbooks.md) |
| EXECUTE_VERIFY | For single-device execution load safe navigation; for matrix execution load matrix supervision; for BOSS or acquisition execution load built-in playbooks. | [safe navigation](references/safe-navigation.md), [matrix supervision](references/matrix-supervision.md), [built-in playbooks](references/builtin-playbooks.md) |
| SYNC_RECIPE | Re-check status == verified, verification.successCount >= 1, and non-empty evidence for every route step before transactional promotion. | [recipe sync contract](references/recipe-sync-contract.md) |
| REPORT | Report completed work, concrete blockers, evidence, next human action, and resume point. | [built-in playbooks](references/builtin-playbooks.md) |

## Selection And Safety

After discovery, one healthy phone is auto-selected for a task that does not require a matrix. With multiple healthy phones, require a single-device or matrix decision when the task did not already decide it. A user request that explicitly requires multiple devices may proceed to matrix planning without a second selection question.

Set `gateMode: weak`. Under this weak safety gate, treat actions named in the normalized task as task-level authorization and execute without per-action confirmation. Automatic actions include publish, comment, private message, routine permission grant, deletion, archive, block, report, follow, unfollow, and add contact, plus non-security account or profile mutation. Before each action, verify the selected account, exact target, final action/control, scope, duplicate key, and audit destination. Never broaden an action beyond the normalized task.

The automatic outbound policy covers publish, comment, and private message named in the normalized task. Treat that task as task-level authorization for those channels; execute them without per-action confirmation after outbound preflight binds the approved account/session, recipient or audience scope, content policy, frequency cap, duplicate prevention, and audit log. Stop a routine or outbound queue immediately on recipient or audience mismatch, content-policy failure, platform risk prompt, rate limit, unavailable audit logging, or an unexpected irreversible action.

Stop before login submission, captcha, 2FA, membership purchase, payment, refund, order placement, candidate rejection, final hiring decision, device administrator activation, accessibility service enablement, VPN installation/configuration, unknown-source installation, security or ownership change, or platform risk bypass. These remain unconditional hard stops. Record `needs_human` before the action; a human may complete one named hard-stop action, then the Agent must revalidate the checkpoint before resuming.

For exploration, use a default limit of 40 actions or 15 minutes. Stop the branch after three unchanged page fingerprints with no new controls and report exploration_budget_exhausted.

## Recipes And Playbooks

Reuse and synchronize only recipes that pass all three gates: status == verified, verification.successCount >= 1, and non-empty evidence for every route step. A changed App version, entry page, or page fingerprint makes a recipe stale and returns the run to safe exploration. A missing prerequisite blocks this run without changing the recipe's prior verification status.

Keep new BOSS resume-screening and acquisition routes draft until real routes are verified, but allow one evidence-backed first execution to include authorized automatic actions. Publish, comment, private-message, and routine mutations may proceed without per-action confirmation when the task names the action and preflight passes. Keep candidate scoring and recommendations in human review; never automate candidate rejection, final hiring decisions, payment, login, or security/ownership changes.

## Internal modes (not triggerable Skills)

These are internal modes of `luming-phone-agent`, not additional triggerable Skills. They retain the ordinary lifecycle above and only select a specialized contract during PLAN, EXECUTE_VERIFY, or REPORT.

- **Acquisition mode:** For customer acquisition, lead discovery, follow-up drafts, automatic publishing/commenting/private messaging, local lead persistence, or Feishu/Bitable sync, load the [acquisition workflow](references/acquisition-workflow.md). Start with acquisition dry-run dispatch, require `loom.acquisition.agent_result.v1` ingestion, and execute task-authorized outbound under a target scope, frequency cap, duplicate prevention, and audit log.
- **BOSS resume screening mode:** For BOSS candidate review, scoring, screening drafts, automatic neutral candidate messages, or a recruiting review queue, load [BOSS resume screening](references/boss-resume-screening.md). Return `loom.hr.resume_screening.v1`; allow task-authorized neutral greeting or clarification messages without per-message confirmation, while routing recommendations to human review and blocking autonomous rejection, final hiring decisions, interview invitations, and security/ownership actions.
- **Scenario authoring mode:** For scenario Skill creation or update from a customer workflow or observed App route, load [scenario Skill authoring](references/scenario-skill-authoring.md). This mode is not a separate triggerable Skill; it uses the current discovery, preflight, safety, verification, and reporting states before producing a validated artifact report.

## Terminal Summary

Always emit this terminal summary, then add a concise human-readable report when useful:

{
  "schema": "loom.phone-agent.run-result.v1",
  "status": "completed|blocked|needs_human|failed",
  "selfCheck": "ready|blocked",
  "gateMode": "weak",
  "selectedDevices": [],
  "task": {},
  "outbound": {"mode": "none|auto", "status": "not_requested|executed|stopped", "channels": [], "actions": [], "stopReason": null},
  "recipe": {"match": "none|reused|stale|created", "sync": "not_needed|synced|sync_pending"},
  "evidence": [],
  "resumeFrom": null
}
