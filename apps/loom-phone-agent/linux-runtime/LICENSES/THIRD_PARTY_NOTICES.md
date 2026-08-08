# Lumi Linux Runtime third-party notices

This module is a separately installed optional companion. It is not merged into the commercial
LumiAgent APK and communicates through a signature-protected, fixed-ID provider contract.

## PRoot 5.1.107.89

- License: GPL-2.0-or-later
- Upstream source: https://github.com/proot-me/proot
- Android build recipe: https://github.com/termux/termux-packages/tree/master/packages/proot
- Binary repository: https://packages.termux.dev/apt/termux-main/
- Packages: `proot_5.1.107.89_{x86_64,aarch64}.deb`
- x86_64 package SHA-256: `0D76DA0515F38DFB2217F647B0D79FCD61B38F80E25CBF2D39237697B02DD016`
- aarch64 package SHA-256: `EC9FE38C50CFD49DD31FE360FFBCC3124A945DC1EA16293A8A769303DD724F46`

The extracted runtime-asset SHA-256 values are recorded in the architecture manifests.

## Alpine minirootfs 3.22.5

- Source and binary repository: https://dl-cdn.alpinelinux.org/alpine/v3.22/releases/
- Archives: `alpine-minirootfs-3.22.5-{x86_64,aarch64}.tar.gz`
- Alpine packages retain their respective licenses under `/usr/share/licenses` where provided.
- x86_64 archive SHA-256: `4B4DAA9FE2FC696C4919C4412A4C3D3E770D8FB70292A004A2C72F5096175282`
- aarch64 archive SHA-256: `3FBC6285032ED46821B511292633D7B2A6306A2E254F590E92BDAFFF56CF2F70`

## libtalloc 2.4.3 and libandroid-shmem 0.7

- Binary/build repository: https://packages.termux.dev/apt/termux-main/
- libtalloc license: LGPL-3.0-or-later
- libandroid-shmem license: BSD-3-Clause
- libtalloc package SHA-256: x86_64
  `7CA2EAAE2E53B28228A01301BC410B62845403D6317C25B8E0A7F40681DE0628`, aarch64
  `AC81AD623D74C209718B9F3ACB2DD702CC8A88C431E820D212229910B4DB29DA`
- libandroid-shmem package SHA-256: x86_64
  `FFA9E4C87467B158B148D0FF92DDA796AA038276C2075AF3269CDCDB06F25797`, aarch64
  `0DA3A24D558B93C92BCF8D611E0826A99FF96E396B148E6CDF33B47C47C57FF6`

Before distributing this companion outside a local test channel, publish the corresponding source
bundle, Termux build scripts and patches, this module source, complete license texts, hashes, SBOM,
and the written source offer required by the applicable licenses.
