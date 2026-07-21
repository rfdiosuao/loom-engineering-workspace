# Task 4 Report: Unified Phone and Matrix Scope Binding

## Status

Completed in `D:\Axiangmu\LOOM-Workspace\worktrees\platform\18-stability-spine\openclaw_new_launcher`.

- Changes are unstaged and uncommitted as requested.
- Only the eight assigned project files and this report were edited.
- Task 2 capability filtering and Task 3 media executors remain green.

## Implementation

- Added `targetScope` metadata to first-party MCP and CLI phone/matrix contracts.
- Added `phone quick-task` to the native Agent CLI allowlist.
- Added bound device forwarding for MCP screenshot, read, and quick-task tools.
- Added bound multi-device/group forwarding for MCP Matrix dispatch.
- Replaced name-based Matrix binding with `AgentOrchestrator._bind_execution_scope(...)` driven by `Capability.target_scope`.
- Capability lookup now happens before scope binding and policy evaluation.
- Single-device writes require exactly one resolved in-scope device.
- Multi-device single-phone calls fail with `phone_single_target_required`; no target is truncated to the first device.
- Read calls cannot declare a device outside the request scope.
- Matrix dispatch replaces model-selected targets with the request's authoritative targets.
- Campaign cancel/retry remains limited to campaign IDs associated with the current run.
- CLI target and campaign options are stripped and rebuilt from authoritative scope values.

## TDD Evidence

RED was observed before production edits:

- MCP: 19/21 passed; failures showed missing `targetScope` and target forwarding.
- CLI: 44/45 passed; failure showed missing `targetScope`.
- Orchestrator: 20/24 passed; failures showed `_bind_execution_scope` was absent.
- Matrix integration: 1/2 passed; the escaping phone call reached the loop limit instead of being rejected.

GREEN verification:

- `test_loom_mcp_contract.py`: 21/21 passed.
- `test_loom_cli_contract.py`: 45/45 passed.
- `test_agent_orchestrator.py`: 24/24 passed.
- `test_agent_matrix_integration.py`: 2/2 passed.
- Directed total: 92/92 passed.

Regression verification:

- `test_agent_capabilities.py`: 15/15 passed.
- `test_agent_service.py`: 23/23 passed.
- `test_agent_builtin_capabilities.py`: 6/6 passed.
- `test_creative_media_contract.py`: 18/18 passed.
- Regression total: 62/62 passed.
- Overall focused total: 154/154 passed.
- Assigned-file `git diff --check`: passed; Git emitted only existing LF-to-CRLF notices.

## Changed Files

- `python/loom_mcp.py`
- `python/loom_cli.py`
- `python/core/agent_capabilities.py`
- `python/core/agent_orchestrator.py`
- `python/tests/test_loom_mcp_contract.py`
- `python/tests/test_loom_cli_contract.py`
- `python/tests/test_agent_orchestrator.py`
- `python/tests/test_agent_matrix_integration.py`

## Concerns

- No functional blocker found in the focused and regression suites.
- Git reports the repository's existing LF-to-CRLF conversion warning for the edited files; no whitespace errors were found.
