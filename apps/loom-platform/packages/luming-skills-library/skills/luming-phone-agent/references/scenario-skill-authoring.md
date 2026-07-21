# Scenario Skill Authoring

Use this internal mode for scenario Skill creation or update. It is not a separate triggerable Skill and does not authorize LOOM product-code changes. Treat backend paths, CLI routes, and source references as architecture anchors unless implementation is explicitly requested.

## Authoring Inputs And Modes

Classify the scenario as acquisition, content operations, customer service, testing, delivery, internal operations, or supervisor/debugging. Collect only details that materially change it: platform, target customer, workflow entrance, expected output, allowed actions, forbidden actions, and acceptance evidence.

Choose an authoring mode: `design`, `observe`, `step`, `safe`, `matrix`, or `replay`. Real route creation remains `safe_navigation`: run normal discovery and preflight, record selected-device before/after evidence and page fingerprints, cap exploration at 40 actions or 15 minutes, and stop after three unchanged fingerprints. A missing App, account, login/session, permission, membership, network, region, version, data, or unsafe action is `blocked_by_prerequisite` with evidence, required human action, and `resumeFrom`; revalidate the checkpoint before resuming.

## Ten-Part Skill Contract

Every authored scenario Skill includes:

1. **Trigger description** with concrete user phrases, platform, LOOM/Luming intent, and scenario keywords.
2. **Scenario identity** for the role, target user, platform, and repeatable delegated job.
3. **Inputs** for platform, entry point, keyword/filter, target customer, device, account, output format, and confirmation boundary.
4. **Operating mode** chosen from the bounded modes above.
5. **Execution loop** covering status check, screenshot/read, task dispatch, watch/log review, normalization, human review, and template suggestion.
6. **Safety boundary** using `gateMode: weak`: mark task-authorized publish, comment, private message, routine permissions, delete/archive/block/report/follow/contact actions, and non-security profile changes as automatic with target, duplicate, audit, evidence, and stop policies; keep payment/purchase/refund/order, login, captcha/2FA, security/ownership, privileged device settings, and unscoped bulk outreach as hard stops.
7. **Evidence** requiring screenshots, event logs, task IDs, visible public evidence summaries, result JSON, and failure classifications.
8. **Output schema** defining both human-readable output and structured JSON fields.
9. **Verification** with concrete commands, UI checks, or acceptance criteria.
10. **Template memory** stating when stable, evidence-complete, rollback-known success can become reusable.

Execute weak-gate automatic actions when the normalized task names them and preflight passes; do not request per-action confirmation. Never bypass login, captcha/2FA, payment controls, privileged device settings, platform controls, or risk controls; never store tokens, passwords, verification codes, or unnecessary private data; never expand beyond the authorized account, target scope, content policy, or frequency cap.

## Compile, Validate, Report

Compile a route only when every step is observed with attributable evidence, `verification: verified`, and `requiresConfirmation: false`. Do not generate, register, or imply a runnable Skill for a blocked/unverified route; keep that draft outside `skills/` and `manifest.json`.

For an eligible artifact, run `quick_validate.py`, parse every JSON example with a structured parser, re-check blocking gaps, route verification, and confirmation gates. The report is an artifact report containing the Skill name and location, trigger intent, scenario family, safety gates, references/examples, validation result, evidence, and unresolved gaps. Template memory is recommended only after repeated stable success with no safety violation.
