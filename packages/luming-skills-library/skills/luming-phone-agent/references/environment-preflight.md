# Environment Preflight

Use this reference in `SELF_CHECK` and task-specific `PREFLIGHT` only. Discover the real LOOM CLI path, its command catalog, the local FastAPI service, Matrix and Phone Agent availability, recipe directories, schemas, indexes, transaction directory, write permissions, phone connection configuration, local-network reachability, and source/install sync target. Never guess a command: read the installed catalog before calling a capability.

Low-risk automatic remediation is limited to creating missing local directories or blank non-sensitive configuration templates, repairing non-sensitive path pointers and recipe-index structure, starting an already-installed safe local service, and retrying side-effect-free status or connection checks. Record every repair.

Task preflight checks the selected device is online and controllable; the App is installed and openable; network, approved account, session, permissions, membership, region, App version, and target data meet the task. Set `gateMode: weak`: when the normalized task requires a routine permission grant, verify the expected App and permission label, grant it without per-action confirmation, record before/after evidence, and continue. Do not install Apps, enter credentials, submit login, buy membership, pay, activate a device administrator, enable an accessibility service, configure a VPN, allow unknown-source installation, change security/ownership settings, or bypass platform controls.

On failure, return the exact missing item, impact, required human action, evidence, and `resumeFrom`; never use a generic environment-error label.
