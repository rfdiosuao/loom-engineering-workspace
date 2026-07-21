# Task Compiler

Normalize every task into a goal, App, device scope, expected result, prerequisites, entry page, evidence requirements, human checkpoints, recovery point, retry budget, and execution mode. The resulting plan schema is loom.phone-agent.task-plan.v1 and must state whether it is matrix work and whether it requires human confirmation.

Compile `gateMode: weak`. Add every task-named publish, comment, private message, routine permission grant, deletion, archive, block, report, follow, unfollow, add-contact, and non-security account/profile mutation to `automaticActions`. Require a `mutationPolicy` with task authorization, exact target scope, duplicate/state checks, audit log, evidence, and stop conditions. Execute these actions without per-action confirmation. Do not add actions inferred only from nearby controls.

When the task includes publish, comment, or private message, compile `outboundMode: auto`; the named channels are task-level authorization and do not require per-action confirmation. Require `outboundChannels` plus an `outboundPolicy` containing `taskAuthorized: true`, approved account/session, target scope, content policy, frequency cap, duplicate prevention, audit log, expected evidence, and stop conditions. Never infer a new channel or broader audience from a nearby control. A generic read, screen, research, or draft task has no outbound authorization.

Match recipes by App identity and version range, normalized goal and aliases, entry page, expected result, mode, saved fingerprints, and key controls. A recipe is reusable only when all three gates pass: status == verified, verification.successCount >= 1, and non-empty evidence for every route step. Every route step must also have verification == verified. Fast revalidate the environment, entry page, and key fingerprints before reuse. A mismatch is stale; missing prerequisites block the run but do not downgrade the prior recipe verification.

During recipe candidate creation, validation, and privacy scan, reject raw resumes and unrelated personal data. Candidate records may contain only minimized task evidence needed for route verification. Reject credentials, tokens, verification codes, contact data, raw resumes, and unrelated personal data; a rejected candidate is not reusable and is not written to the recipe index.

New or stale routes remain draft until one complete execution has evidence for every step and visible verification. Never promote inferred, blocked, sensitive, or partially synchronized recipes to reusable status.

Compile recipe candidates against `schemas/recipe.schema.json`. Represent each route action in `steps` with a stable `stepId`, a JSON Boolean `requiresConfirmation`, `verification: verified|unknown`, and minimized evidence objects. Each evidence object contains only a named `type` (`screenshot`, `page-fingerprint`, `control-state`, or `visible-assertion`), a bounded non-secret `reference`, and a closed assertion object. The assertion requires an allowlisted `predicate` (`visible`, `present`, `selected`, `enabled`, `checked`, or `matches`), a bounded identifier-like `subject`, and a Boolean `expected`; free-form evidence narrative is prohibited. A verified candidate must use `verification: verified` and meaningful non-placeholder evidence on every step, while built-in or unexplored routes stay draft with `verification.successCount: 0`. The recipe index is only a lookup projection; `scripts/sync_recipe.py` is the sole writer for promotion to source and installed roots.

Minimized evidence applies to every free-string field, not only `steps[*].evidence`. Do not compile credentials, tokens, OTPs, contact details, identity values, raw-resume sections, or unrelated personal attributes into names, aliases, App metadata, goals, prerequisites, actions, safety text, fingerprints, or source metadata.

## Acceptance Table

| Scenario | State | Result status | Resume behavior | Prohibited action |
| --- | --- | --- | --- | --- |
| low-risk first launch repair | SELF_CHECK | completed | none | no App installation |
| no connected phone | PHONE_DISCOVERY | blocked | PHONE_DISCOVERY | no invented device command |
| one healthy phone | ASK_TASK | completed | none | no matrix dispatch |
| multiple healthy phones | ASK_TASK | needs_human | ASK_TASK | no automatic device selection |
| verified recipe reuse | RECIPE_MATCH | completed | none | no reuse before all three gates |
| changed page or App version | REUSE_OR_EXPLORE | completed | REUSE_OR_EXPLORE | no stale reuse |
| new task exploration | EXECUTE_VERIFY | completed | SYNC_RECIPE | no promotion without evidence |
| missing prerequisite | PREFLIGHT | blocked | PREFLIGHT | no prerequisite bypass |
| authorized automatic outbound | EXECUTE_VERIFY | completed | none | no send without outbound preflight |
| authorized routine mutation | EXECUTE_VERIFY | completed | none | no mutation outside task scope |
| hard-stop action | EXECUTE_VERIFY | needs_human | EXECUTE_VERIFY | no action submission |
| three unchanged fingerprints | REUSE_OR_EXPLORE | blocked | REUSE_OR_EXPLORE | no continued exploration |
| concurrent recipe sync | SYNC_RECIPE | blocked | SYNC_RECIPE | no unlocked write |
| sensitive recipe content | SYNC_RECIPE | blocked | PLAN | no candidate write |
| source-install-ZIP parity | REPORT | completed | later packaging task | no parity claim |
| legacy Skill transition | REPORT | completed | later migration task | no legacy removal |
