# APKClaw Upstream Snapshot

The LOOM monorepo is the release source of truth. Its phone Agent source was
synchronized from the committed APKClaw upstream snapshot below:

- Repository: `https://github.com/rfdiosuao/lumiapkclaw.git`
- Commit: `a7526e1e1608c9057dfff0946ba6e7bf84e051b3`
- Commit date: `2026-07-20`
- Imported paths: `app/src/**`, `gradle/libs.versions.toml`, and the committed
  `tools/**` pressure-test fixtures required by the Android source contracts

Uncommitted files from the upstream worktree were intentionally excluded.
LOOM-specific OEM build configuration remains owned by this monorepo.

After the snapshot import, LOOM adds the `loom-usb-bind-v3` identity challenge
and releases the phone Agent as `6.62-stability` (`versionCode 931`).

Future upstream synchronization must name an immutable commit, import only
committed files, run the complete Android unit-test suite, and verify that the
release APK has the same signing certificate as the previous production APK.
The trusted production certificate fingerprint is stored in
`release/trusted-signing-cert.sha256`; verify every release artifact with
`tools/verify-release-signature.ps1` before publishing it.
