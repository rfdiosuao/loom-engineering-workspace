---
name: verify
summary: Verify phone connection changes through the fleet CLI runtime surface.
---

# Phone connection verification

Run from `openclaw_new_launcher`.

1. Use the bundled Python runtime to decrypt the installed `data/.openclaw/launcher/phone-agents.json` token.
2. Pass the decrypted in-memory store through `LOOM_PHONE_RUNTIME_CONFIG_JSON` and run:
   `node scripts/openclaw-phone-fleet.mjs status --target <device-id> --json`
3. Confirm a real connected device returns top-level `ok: true`, row `ok: true`, and `status.online: true`.
4. Probe an unreachable endpoint (for example `http://127.0.0.1:1`) and confirm the result preserves `errorCode`, actionable Chinese `message`, and `remediation`.
5. Remove `LOOM_PHONE_RUNTIME_CONFIG_JSON` after each command. Never print or persist its token.
