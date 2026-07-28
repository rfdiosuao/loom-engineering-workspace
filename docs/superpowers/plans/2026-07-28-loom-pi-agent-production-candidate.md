# LOOM PI-Inspired Agent Production Candidate Plan

**Goal:** 在不重写 LOOM 现有架构、不破坏用户数据和当前安装的前提下，把原生中枢智能体、手机首次配对与全局 UI 收敛成可验证的生产候选。

**Baseline:** `origin/main` at `4ff240e66e76f318b9a42c1ad0a583ff46140b13`.

**Borrow from Pi:** event-driven loop, append-only session tree, provider/model separation, context compaction and explicit harness checkpoints.

**Do not borrow from Pi:** process-internal unrestricted extensions, implicit tool retry, unbounded context replay or a second execution protocol beside LOOM capabilities.

## 1. Frozen Decisions

1. LOOM keeps its native FastAPI Agent service, capability registry, policy engine, repository, SSE event stream and Matrix/phone execution paths.
2. Tool calls are at-most-once by default. Only explicitly idempotent read operations may retry automatically.
3. A run is not complete until the requested business operation reaches a verifiable terminal state.
4. Session history is append-only. Compaction creates derived summaries and never rewrites raw events.
5. Phone users never handle a permanent `apiToken`. A short-lived pairing code exchanges for long-lived random credentials stored by the platform and phone.
6. All modules consume one visual token system. Pages may vary layout and density, not redefine semantic colors.

## 2. Parallel Workstreams

### A. Agent Execution Safety

- Propagate pause, cancel and deadline controls into capability execution.
- Prevent an in-flight side-effecting tool from executing again after pause/resume.
- Add a completion verifier for queued/running Matrix and phone operations.
- Normalize terminal events for succeeded, failed and cancelled child operations.
- Tests must prove no duplicate external side effect and no false completion.

### B. Agent Session Lifecycle

- Eliminate accepted-next-message history races.
- Gracefully stop Agent runs before Bridge shutdown.
- Validate Bridge session identity with PID, port and process identity rather than URL prefix alone.
- Add derived context summaries for long conversations while retaining raw append-only history.
- Align persisted session/run payloads with versioned schemas.
- Extend release smoke and upgrade tests to cover `/api/agent/*` and `data/agent`.

### C. Phone Pairing And Recovery

- The phone creates a short-lived pairing session. USB loopback may use a cryptographically random six-digit manual code; LAN pairing must use a QR/paste payload containing a high-entropy one-time bootstrap secret. Neither mode exposes a permanent credential.
- Pairing proofs are single-use, attempt-limited, nonce-protected, source-rate-limited and bound to the pairing session plus expected device identity.
- The desktop remains the client and claims the session over the existing USB/LAN ConfigServer path. LAN requests send only a keyed proof, never the bootstrap secret, and the phone returns random long-lived phone and launcher credentials in an AES-GCM encrypted response.
- The phone never connects to the loopback-only desktop Bridge, and the Bridge is not exposed on the LAN for pairing.
- Permanent credentials remain protected by DPAPI on Windows and private app storage/keystore on Android.
- Credential rotation is transactional: existing credentials remain valid until the desktop has persisted and verified the new credentials and confirms the pairing. Failed or abandoned pairing cannot disconnect an existing device.
- USB and LAN use the same saved device identity and execution channel.
- Recovery is bounded and observable: reconnect uses backoff plus a finite retry budget, preserves the last verified identity, and reports actionable USB/LAN/authentication error codes instead of a generic “connection failed”.
- Pairing has one user-facing entrypoint: the phone's **与 LOOM 配对** page and the desktop's **手机连接** page. Legacy Skills, prompts and docs must never request a phone URL, port or permanent token.
- Reconnect is per-device and non-blocking. One unreachable phone cannot freeze the Phone, Matrix or Agent UI or delay healthy phones.
- The controlled acceptance target is >= 98% first-pair success, >= 99% restart recovery, P95 recovery <= 15 seconds, and zero false-online states.

State machine:

```text
unpaired
  -> code_generated
  -> phone_claimed
  -> desktop_persisted
  -> verified
  -> connected
  -> reconnecting
  -> connected | needs_repair
```

Required error codes:

- `phone_pairing_code_expired`
- `phone_pairing_code_invalid`
- `phone_pairing_code_replayed`
- `phone_pairing_rate_limited`
- `phone_pairing_device_mismatch`
- `phone_usb_unauthorized`
- `phone_lan_unreachable`
- `phone_credential_invalid`

### D. Unified Visual Language

LOOM is an operational productivity workbench, not a marketing landing page. Use a dense, calm, trust-oriented system:

- Neutral canvas and white/near-black surfaces.
- Deep LOOM green for primary action, selection and brand identity.
- Blue for information and links.
- Green for success only.
- Amber for waiting, degraded and warning.
- Red for failure, destructive and stopped.
- Neutral gray for disabled, archived and unknown.

UI rules:

- No raw business hex values in React components.
- No module-specific primary palettes.
- Major modules use `app-bg` for the canvas, `surface` for headers/work areas and `surface-alt` for secondary panels. Dark surfaces are reserved for actual device screens, terminals and the branded splash.
- Status always includes text or an icon, never color only.
- Actions taking over 300ms show immediate progress.
- Error regions use `role="alert"` or `aria-live`.
- Focus rings remain visible.
- Motion is 150-300ms and respects `prefers-reduced-motion`.
- Cards are not nested; operational sections remain unframed where possible.

## 3. Worktree Ownership

| Worktree | Exclusive ownership |
| --- | --- |
| `codex/pi-agent-kernel-20260728` | Agent orchestrator, capability cancellation, completion verifier and focused tests |
| `codex/pi-agent-lifecycle-20260728` | Agent service/repository lifecycle, Bridge identity/shutdown, schemas and smoke/upgrade tests |
| `codex/phone-pairing-20260728` | Phone routes/API/UI, Android pairing UI/security, phone tests and pairing docs |
| `codex/ui-color-system-20260728` | Theme tokens, component color migration, motion/accessibility and visual tests |

Workers are not allowed to edit another workstream's owned files without controller approval.

## 4. Integration Order

1. Cherry-pick Agent kernel and lifecycle into the controller branch.
2. Run focused Agent tests and resolve contract changes.
3. Cherry-pick phone pairing, then run platform phone plus Android tests.
4. Cherry-pick the UI color system last so it consumes the final component states.
5. Run full platform, phone, workspace, Rust, build, package and non-destructive desktop smoke.

## 5. Release Gates

Automated:

- Python platform suite passes.
- Node contracts pass.
- Frontend contracts pass.
- Android default and Android 7 suites pass.
- Workspace governance passes.
- `cargo check --locked` passes.
- `npm audit` reports zero known vulnerabilities.
- Vite production build passes.
- No secret appears in API snapshots, logs, process arguments or diagnostics.

Current-computer validation:

- Start an isolated Bridge on alternate ports.
- Create, expire, replay and successfully claim pairing codes.
- Verify existing protected phone config migration without touching the installed LOOM data.
- Verify USB/LAN first-pair, restart recovery, USB unplug/replug, LAN address drift and one unreachable phone alongside one healthy phone.
- Complete an Agent read-only run, an internal write run and a cancelled tool run.
- Restart the isolated app and verify session continuity and phone recovery state.
- Capture Playwright screenshots at 960x640, 1200x800 and 1440x900 for all major modules.

External validation that cannot be fabricated:

- One and multiple physical phones pairing over real LAN and USB.
- Ten-device two-hour Matrix soak.
- Real provider chat, image, video and platform publishing.
- Commercially trusted Windows signing and production updater keys.

## 6. Definition Of Done

This candidate is done only when:

- pause/cancel cannot duplicate a side effect;
- Agent completion reflects terminal business truth;
- accepted messages see the latest committed history;
- shutdown preserves Agent data;
- phone setup no longer exposes or asks for a permanent token;
- pairing and reconnect failures are actionable;
- all major modules share the same color semantics and accessible interaction feedback;
- the PR passes required gates and produces traceable artifacts from the merged source tree.
