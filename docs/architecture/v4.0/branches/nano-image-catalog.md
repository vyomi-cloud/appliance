# v4/nano-image-catalog

Owner: Claude (session with the owner) - Started: 2026-11-27 - Base: origin/v4-on-main - Status: phase 1 in progress, NOT merged

## Purpose
Enable every guest image the browser can really run on Nano, on all three clouds, with honest labels.
Evidence and numbers: `docs/spikes/nano-vm-images.md` (branch `v4/spike-nano-vm-images`). Effort figures there are estimates, not measurements.

## Rule
Each catalogue entry (AWS AMI / GCP sourceImage / Azure imageReference) resolves to the REAL OS on a Nano image, or stays disabled with a reason.
Never alias one OS onto another (an Ubuntu AMI is not Debian). A 32-bit guest says "(32-bit x86)" in its label.

## Plan
| Phase | Images | Engine | Instance features |
|---|---|---|---|
| 1. Enabled | Alpine 3.21 (shipped), Debian 12 i386, Buildroot 2024.05 (busybox only) | v86, 32-bit x86 | Stop/Start snapshots, exec channel, SSH through vyomi-tunnel |
| 2. Beta, opt-in | Debian x86_64, Python x86_64, then Amazon Linux 2023, Ubuntu 24.04, Rocky/Alma built in CI | container2wasm (Bochs) | Console only: no snapshots, no exec channel, no SSH without a network bridge; ~7x slower; 90-200 MB each |
| 3. Experimental, hidden | riscv64 Debian | container2wasm (TinyEMU) | As phase 2; 136 MB |
| Disabled, reason shown | arm64 (Graviton, T2A, Ampere), Windows, macOS, GPU families, RHEL/SUSE unless built | none | CheerpX and JSLinux excluded by licence; qemu-wasm ~1 min boot, 145 MB |

Not enabled: Tiny Core (VGA console, 12.5 s), FreeDOS, KolibriOS (not cloud images).

## Phase 1 steps
1. Commit loose work, rebase on fresh trunk, rebuild consoles and cores.
2. Build + boot Debian and Buildroot on AWS, GCP, Azure Nano; run the compute and browser-VM suites with a local base URL.
3. Image catalogue in every create flow and picker, "first launch downloads N MB".
4. Licence/source-offer notes for Debian in THIRD-PARTY-NOTICES.md.
5. Hosting for the image files (decision pending), then wire `base_url`.

## Decisions pending (owner)
- Where the Debian (~57 MB) and Buildroot (~10 MB) files are hosted (portal static / GitHub release assets / CDN over a repo / object store).
- Is console-only acceptable for phase 2.
- Legal review of container2wasm and GPL/LGPL compliance before phase 2.

## Phase 1 results (2026-11-28, headless Chromium, local preview server, local image files)
- Core tests: test_compute_images_core, test_compute_sizes_core, test_windows_images_disabled_core all pass.
- Browser-VM smoke (every runnable image boots to a shell and is probed for exactly what it claims): AWS 37/37, GCP 37/37, Azure 38/38.
- Compute-images UI smoke (Nano + Mesh pickers): 44/44 after updating 5 assertions from "only Alpine" to "Alpine + Debian + Buildroot enabled".
- Boot to a shell, measured here: Debian 54-72 s, Buildroot 10-12 s (Azure reported 0 s once, unexplained; its probes still passed). The spike measured Debian in 7.7 s on a lighter setup; not reconciled.
- Debian image is 56.7 MB gzip (git, python3, apt/dpkg), larger than the spike's 38.5 MB PoC.

## Fixed along the way
- GCP guest probe (`nano-vm-host.js`, on trunk) typed `echo VYGA...` into the shell 6 s after boot and collided with whatever the user was typing. It now waits 4 s after the last keystroke and retries.
- Smoke harness: GCP create step did not return to the console home before creating the next image.
- THIRD-PARTY-NOTICES + SBOM: Debian and Buildroot guest images added (wording still marked "counsel to confirm").

## Seen, not caused here
- AWS Buildroot `cat /etc/os-release` timed out once, did not repeat on a rerun (not diagnosed).
- `tests/conformance/test_ai_notices.py` has 17 failures (vendored wheels) that fail identically on untouched trunk.

## Not done / not verified
Not merged or released. Image hosting (`base_url` is still empty) is undecided, so a deployed Nano cannot fetch Debian or Buildroot yet.
Not tested: a real portal-served Nano, other browsers, slow networks, the cold first-launch download.
