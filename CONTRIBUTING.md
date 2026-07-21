# Contributing

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
