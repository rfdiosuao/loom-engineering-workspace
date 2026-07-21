# Matrix Supervision

Use this only for an approved matrix plan. The required loop is:

```text
preflight -> dispatch_once -> watch_events -> poll_health_lightly -> classify_each_device -> diagnose_abnormal_only -> repair_or_retry_target -> summarize
```

Create a campaign ID and deduplicate each dispatch by campaign ID, task fingerprint, and device ID. Dispatch once, watch events first, and poll health lightly. Maintain independent state, job ID, evidence, and retry budget per device. Diagnose abnormal-device-only: one abnormal device must not block healthy devices or trigger redispatch of the full campaign.

Use screenshot or screen-read only for a trigger such as no progress, error, wrong page, permission prompt, ambiguity, or final evidence. Quarantine offline or repeatedly failing devices. Under the weak safety gate, allow automatic outbound plus task-authorized routine permission and routine mutation actions on devices whose outbound preflight passed; retain an independent target scope, duplicate key, audit log, and evidence stream per device. A target mismatch, duplicate, platform-risk prompt, rate limit, unavailable audit log, or security-sensitive prompt pauses only that device while healthy devices continue. Pause as `needs_human` for lock screen, login, captcha, 2FA, payment, purchase/refund/order, candidate rejection, device administrator, accessibility service, VPN, unknown-source installation, security/ownership change, or platform risk bypass.
