# Safe Navigation

Use this reference for single-device EXECUTE_VERIFY in two modes. For verified recipe reuse, follow the recipe's evidence/verification steps in order, capture the required evidence, and remain under the same hard stops. Do not infer or extend a verified route; if its App version, entry page, or fingerprint no longer matches, mark it stale and switch to new/stale exploration.

For new/stale exploration, allowed actions are opening an installed App, ordinary navigation taps, tab changes, scrolling, non-sensitive search input, screenshots, screen reading, back navigation, task-authorized automatic outbound, and task-authorized routine mutations. Capture before/after evidence and page fingerprints for each observed route step.

## Weak Safety Gate

Set `gateMode: weak`. Treat a routine permission grant, deletion, archive, block, report, follow, unfollow, add contact, and non-security account or profile mutation named in the normalized task as authorized. Execute without per-action confirmation after verifying the App/account, exact target, selected control, expected result, duplicate state, and audit destination. Capture before/after evidence and stop if the target, action label, account, or expected result differs.

## Automatic Outbound

Treat publish, comment, and private message included in the normalized task as task-level authorization. Set `outboundMode: auto` and execute the named channels without per-action confirmation only after outbound preflight records the approved account/session, recipient or audience scope, content policy, frequency cap, duplicate prevention key, audit log destination, and expected success evidence. Verify the selected account, target, final content, and send control immediately before each action. Capture action ID or timestamp, target reference, content hash, and after-state evidence.

Stop the outbound queue on recipient or audience mismatch, duplicate detection, content-policy failure, platform risk prompt, rate limit, unexpected audience expansion, unavailable audit logging, or changed send/publish controls. Do not bypass risk controls, rotate accounts to evade limits, use scraped private contact data, or send untargeted unsolicited bulk messages.

The following are hard stops: login submission, captcha, 2FA, membership purchase, payment, refund, order placement, candidate rejection, final hiring decision, device administrator activation, accessibility service enablement, VPN installation/configuration, unknown-source installation, security or ownership change, and platform risk bypass. Also stop on any unexpected irreversible action outside the task scope or whose target/audit evidence cannot be verified. A human may complete one named hard-stop action; revalidate the page, account, and task checkpoint before resuming.

Apply exploration budgets only to new/stale exploration: use no more than 40 actions or 15 minutes by default. If three unchanged page fingerprints occur without new controls, stop that branch, preserve the checkpoint, and return exploration_budget_exhausted. Never infer an unobserved route from a similar page.
