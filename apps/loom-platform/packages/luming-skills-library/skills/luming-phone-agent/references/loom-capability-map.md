# LOOM Capability Map

Resolve the installed command surface before acting. Run:

```text
"<doctor.data.paths.pythonExe>" -B "<doctor.data.paths.cliPath>" doctor --json
"<doctor.data.paths.pythonExe>" -B "<doctor.data.paths.cliPath>" commands --json
```

Use `doctor.data.paths.npmRoot` as the working directory for npm helpers. Use
`doctor.data.paths.adbPath` as the absolute ADB executable; if bare `adb` is not
available, set `LOOM_ADB` for child commands and prepend its directory to the
current process `PATH`. Do not require a global Android SDK install.

## Capability Surfaces

- Read-only control: `phone status`, `phone screenshot`, `phone read`,
  `matrix status`, `matrix watch`, `logs ledger`, and signed `events`.
- Phone Agent: `phone:agent` for bounded work and async submit/status/cancel.
- Deterministic vision: `phone:vision`; prefer a fresh observation and
  `click_ref` before text, node, coordinate, or model-driven fallback.
- Recording: `phone:video` or `loom:phone:video`. An Android screen-capture consent prompt is an OS-owned hard stop and must not be reported as bypassed.
- Media transfer and editing: `phone:image`, `phone:image:edit`.
- Multi-device execution: `phone:fleet`, or Matrix dispatch/watch for long,
  retry-heavy, independently supervised work.
- Canvas/game fallback: `phone:game`.
- Publishing transport: `phone:publish`, only within the normalized task and
  after account, target, content, frequency, duplicate, and audit preflight.
- Creative generation: LOOM CLI/MCP `media image` and `media video`; transfer
  results through the signed phone/media path and verify every target device.

Use CLI/MCP when Computer Use, Node REPL, Browser, Chrome, or desktop control is
unavailable. Never invent a command that is absent from `commands --json`.
