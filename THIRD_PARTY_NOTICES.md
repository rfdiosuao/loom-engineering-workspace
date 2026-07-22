# Third-Party Notices

LOOM includes and integrates third-party software. Those components remain governed by their respective licenses, copyright notices, and attribution requirements. The LOOM dual-license terms do not replace or restrict rights already granted by third-party licensors.

Known repository-level exceptions include:

| Path or component | License | Notes |
| --- | --- | --- |
| `apps/loom-phone-agent` upstream ApkClaw/Agent Phone portions | Apache License 2.0 | The existing [`apps/loom-phone-agent/LICENSE`](apps/loom-phone-agent/LICENSE) and retained notices apply to upstream portions. LOOM-owned modifications and the combined LOOM product are offered under the LOOM dual-license model to the extent the LOOM copyright holder has the right to do so. |
| `apps/loom-phone-agent/skills/*` files that declare `license: MIT` | MIT License | Their file-level metadata remains authoritative. |
| Gradle wrapper files and bundled dependency metadata | Their stated upstream licenses | Existing headers and notices remain intact. |
| npm, Cargo, Gradle, Python, and other external dependencies | Their respective upstream licenses | Dependency declarations do not relicense those projects under AGPL-3.0. |

This list identifies repository-level exceptions and is not a substitute for the license metadata shipped by each dependency. If a file or directory contains a more specific license notice, that specific notice controls for that material.

When adding or upgrading a third-party component, preserve its notices and update this document when the repository-level exception list changes.
