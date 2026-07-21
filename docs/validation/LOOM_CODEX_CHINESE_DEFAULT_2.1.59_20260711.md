# LOOM 2.1.59 Codex Chinese Default Validation

Date: 2026-07-11

## Scope

LOOM bundles the official `@openai/codex` CLI. The upstream TUI does not expose
a `language` or `locale` configuration, so terminal labels remain upstream
English. LOOM now makes model responses default to Simplified Chinese through
the officially supported global `$CODEX_HOME/AGENTS.md` instruction file.

## Behavior

- Creates `data/.codex/AGENTS.md` on the first LOOM-managed Codex launch.
- Defaults analysis, plans, result summaries, and error explanations to Chinese.
- Leaves commands, paths, code, configuration keys, and raw logs unchanged.
- Honors an explicit language request from the user.
- Preserves existing `AGENTS.md` and `AGENTS.override.md` files.
- Retains manual confirmation, allowlist, rate-limit, and logging requirements
  for real publishing or outreach actions.

## Candidate

- Installer: `artifacts/nsis-release-2.1.59-offline-complete-candidate-r1/LOOM-2.1.59-setup.exe`
- Size: `382277165` bytes
- SHA256: `fda924d4e0570a267e3283fb83b148bb876f443a1cc481291b63cb07d6a4934e`
- Authenticode: `NotSigned` engineering candidate

## Verification

- Frontend build passed.
- Version consistency passed for `2.1.59`.
- Python suite passed with `575` tests.
- Component installer tests passed with `72` tests.
- Exact NSIS smoke passed in ASCII and Chinese paths.
- Both smoke cases reported packaged Python, FastAPI Bridge, and
  `codexDefaultLanguage: zh-CN`.
- Existing LOOM process, uninstall registration, shortcuts, and test directories
  were restored after smoke validation.

An existing Codex TUI session must be closed and relaunched from LOOM because
Codex reads global `AGENTS.md` once when a session starts.
