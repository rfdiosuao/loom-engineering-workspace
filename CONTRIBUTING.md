# Contributing

## 许可证与贡献权利

LOOM 自有代码以 `AGPL-3.0-only` 和单独商业许可双重提供。提交代码、文档或其他可版权化内容前，贡献者必须确认自己有权提交，并同意维护者可以在 AGPL-3.0-only 以及 LOOM 商业许可证下使用、修改和再许可该贡献。

在正式的贡献者许可协议（CLA）流程上线前，未经维护者明确记录许可确认的外部代码 PR 不得合并。仅报告问题、提出建议或不包含可版权化实现的讨论不受此限制。

第三方代码必须保留原始许可证和版权声明，并在需要时更新根目录的 `THIRD_PARTY_NOTICES.md`。

## Development Flow

1. Start from `D:\Axiangmu\LOOM-Workspace` or a worktree created by this repository.
2. Create or select one GitHub Issue for the change.
3. Run `scripts/new-feature.ps1` from the repository root.
4. Work in the generated worktree only.
5. Keep the PR focused on one product or engineering outcome.
6. Run the relevant verification command before opening the PR.
7. Push the branch and open one PR against `main`.
8. Remove the local worktree only after the PR is merged and no longer needed.

Platform, phone, contracts, skills and docs now live in one repository. Cross-component features should use one branch and one PR, with the changed areas listed in the PR body.

## Commit Style

Use Conventional Commit prefixes: `feat`, `fix`, `refactor`, `test`, `docs`, `build`, `ci`, `chore`.

## Safety

Never commit credentials, customer data, private chat content, device tokens, signing keys, local databases, generated applications, logs, screenshots, release artifacts, authorization-code spreadsheets, or local configuration.

Generated output belongs in ignored local paths such as `artifacts/`, build folders, or release distribution channels.
