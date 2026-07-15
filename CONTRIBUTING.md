# Contributing

## Development Flow

1. Create or select a GitHub Issue.
2. Run `scripts/new-feature.ps1` for the owning repository.
3. Make one focused change in the generated worktree.
4. Run repository verification and include the evidence in the PR.
5. Push the feature branch and open one PR linked to the Issue.
6. Remove the local worktree only after the PR is merged and the branch is no longer needed.

## Commit Style

Use Conventional Commit prefixes: `feat`, `fix`, `refactor`, `test`, `docs`, `build`, `ci`, `chore`.

## Safety

Never commit credentials, customer data, private chat content, device tokens, signing keys, local databases, generated applications, logs, screenshots, or release artifacts.
