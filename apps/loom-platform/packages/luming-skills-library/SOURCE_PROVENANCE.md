# Skill Source Provenance

Status: current
Owner: LOOM Agent Platform
Last verified: 2026-07-21
Applies to: `packages/luming-skills-library/`

## Migration Source

- Original local repository: `D:\Axiangmu\U盘启动器\luming-skills-library`
- Source commit: `9315708522902523b32af500dbd6008e3e0295e8`
- Source commit date: 2026-07-20
- Source remote: none configured
- Imported state: current working tree, including four uncommitted compatibility fixes
- Imported files: 39

The imported working-tree changes affected `README.md`, `manifest.json`,
`scripts/install.ps1`, and `tests/luming-skills-install-contract.ps1`. They are
part of the 2026.07.21 package already bundled by LOOM and therefore belong in
the migrated source of truth.

## Ownership Decision

This directory is now the only maintainable source for the LOOM Skill Library.
The previous standalone repository is retained only as migration evidence and
must not receive new product changes. Packages are generated through
`scripts/build-luming-skills-library.ps1` from the main repository root.

The generated `luming-skills-library-20260721.zip` must reproduce SHA256
`36D03E43FEA6102AA6FEE96E7B91004FABAE45C6E40C5C3FC8D933F30DD03CA7` until the
manifest version or Skill source changes intentionally.
