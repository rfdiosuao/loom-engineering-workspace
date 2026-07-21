# Contributing

## Development Flow

1. Start in `D:\Axiangmu\LOOM-Workspace`, not a legacy or release directory.
2. Create or select a GitHub Issue in the repository that owns the change.
3. Run `scripts/new-feature.ps1` for the owning repository.
4. Make one focused change in the generated worktree.
5. Run repository verification and include the evidence in the PR.
6. Push the feature branch and open one PR linked to the Issue.
7. Remove the local worktree only after the PR is merged and the branch is no longer needed.

Repository governance, product behavior and release artifacts must not be mixed in one PR. Cross-repository features use linked PRs; they do not copy source between repositories.

## Commit Style

Use Conventional Commit prefixes: `feat`, `fix`, `refactor`, `test`, `docs`, `build`, `ci`, `chore`.

## Safety

Never commit credentials, customer data, private chat content, device tokens, signing keys, local databases, generated applications, logs, screenshots, or release artifacts.
