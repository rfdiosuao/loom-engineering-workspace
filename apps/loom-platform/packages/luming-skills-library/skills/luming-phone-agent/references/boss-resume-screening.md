# BOSS Resume Screening

Use this internal mode as an assisted, evidence-first HR workflow. Read only user-authorized visible BOSS candidate data, compare it with a frozen job scorecard, generate review notes, and optionally send an automatic private message for a neutral greeting or job-related clarification. It is not an automated decision-maker.

## Scorecard And Modes

Freeze a job-related scorecard before reading candidates: role, must-haves, nice-to-haves, job-related deal-breakers, interview questions, salary/location constraints, reviewer, sample size, retention rule, and excluded signals. Each point needs visible evidence.

Modes are `design`, `observe`, `step`, `safe_batch`, `matrix_safe_batch`, and `replay`. Prefer `observe`. Upgrade a batch only after human confirmation of account authorization, candidate source, sample size, and review rules. Matrix queues are bounded and deduplicated; pause or repair only an abnormal device.

Never score gender, marital or fertility status, ethnicity, religion, disability, health, appearance, household registration, birthplace, age without documented lawful necessity, or school prestige as a proxy. Store only minimized job-related fields and masked candidate references. Do not retain phone, email, WeChat, ID, exact birthdate, raw resumes, unnecessary screenshots, or unrelated personal information.

## Classification And Review Queue

Use this vocabulary exactly:

- `priority_review`: strong job-related match; human reviews first.
- `interview_candidate`: likely suitable; draft an invite or questions only.
- `manual_review`: incomplete, ambiguous, or sensitive context; HR decides.
- `lower_priority_review`: important job-related evidence is missing; keep the note, never auto-reject.
- `not_enough_info`: visible data is insufficient.

Never mark a candidate as finally rejected solely through automation. A job-related deal-breaker is evidence for human review, not an autonomous outcome. Allow an automatic private message for a neutral greeting or clarification when the normalized task authorizes it and outbound preflight freezes the account, candidate target rule, approved template/content policy, frequency cap, duplicate prevention, audit log, and evidence. Send without per-message confirmation. Keep reject and interview-invitation actions human-owned, but allow task-authorized archive, block, report, follow, add-contact, routine permission, and non-security profile actions under the weak gate. Login, captcha, SMS/2FA, payment/purchase/refund/order, security/ownership changes, privileged device settings, and bulk export are hard stops.

```json
{
  "schema": "loom.hr.resume_screening.v1",
  "platform": "boss_zhipin",
  "mode": "observe",
  "scorecardVersion": "role_scorecard_2026_07_13",
  "role": "operations specialist",
  "status": "review_queue_ready",
  "candidates": [{
    "candidateRef": "masked_candidate_001",
    "sourceSurface": "recommended candidates",
    "recommendation": "manual_review",
    "matchScore": 72,
    "mustHave": [{"name": "role skill", "status": "met", "evidence": "visible job-related evidence"}],
    "niceToHave": [],
    "gaps": [],
    "sensitiveOrExcludedSignals": [],
      "drafts": [{"type": "clarification_question", "body": "approved neutral clarification", "requiresHumanReview": false}],
      "outboundActions": [{"channel": "private_message", "status": "sent", "contentHash": "sha256:...", "evidenceRef": "shot_after_xxx"}],
    "evidence": [{"type": "screenshot", "ref": "shot_xxx", "summary": "authorized visible page"}],
    "humanReviewRequired": true
  }],
  "blockedActions": ["auto_reject", "auto_interview_invitation", "bulk_export"],
  "privacyNotes": ["stored_minimized_fields_only"]
}
```

Accept a run only when the frozen scorecard predates scoring, every score has visible evidence, excluded signals are ignored or escalated, any automatic message is neutral and covered by outbound preflight, no rejection/final hiring/interview-invitation action ran automatically, output uses masked/minimized fields, and evidence/task IDs support audit.
