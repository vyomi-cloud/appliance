# Spike: more VM images / OS / architectures on Nano (free, in-browser, no Mesh)

Branch `v4/spike-nano-vm-images` (from freshly fetched `origin/v4-on-main`, 2026-11-26). Research + measured experiments only: no production code path changed,
no `wasm/v4` regeneration. PoC code is under `spikes/nano-vm-images/`.

## 1. Question

Nano boots exactly one guest today: Alpine 3.21 i386 on the v86 emulator (1 vCPU, 32-bit x86, RAM up to 1 GiB, `wasm/vm/`). Which other images / OSes / architectures
can we realistically offer inside the browser, and at what cost? Every number below was measured on this spike unless marked **(unverified)** = read from docs only.

## 2. Method and caveats (read before trusting any number)

- Machine: Apple M1, 8 cores, 16 GiB, macOS; Google Chrome 158.0.8127.88 headless via Playwright. **The Mac was shared with other sessions' Chrome/Node jobs**, so
  boot times drift run to run (Alpine/v86 prompt ranged 5.3 - 9.7 s across sessions of runs). Treat figures as order-of-magnitude with the stated ranges, not as benchmarks.
- "Cold" = a fresh Chrome profile per run (no HTTP/Cache Storage/IndexedDB), assets from a local static server (`spikes/nano-vm-images/serve.py`, COOP/COEP on).
  **Download time over a real network is not included**; sizes are given so it can be computed (see "wire size").
- "To prompt" = time from `page.goto` to a shell prompt visible on the guest console; "cmd" = host-measured round trip of a typed command (`cat /etc/os-release`, `uname -m`).
- CPU probe = `head -c 20000000 /dev/zero | sha256sum` (20 MB through sha256sum) typed into each guest, wall time measured on the host. Same bytes, same digest
  (`9e21c619...`) in every guest. Python probe = `python3 -c "print(sum(range(10**6)))"`. Guest `time` output is NOT used (emulated clocks drift: Bochs reported 27 s for a 19.5 s run).
- Memory = sum of RSS of the Chrome process tree (ps) minus the empty-tab baseline (620 MiB, measured), single sample at the end of a run. Rough.
- Production Alpine numbers use the production engine files (`wasm/vm/engine`, v86 0.5.x) and production kernel + rootfs, but via a spike harness
  (`v86/index.html`, serial console), not via `vm-worker.js` (so no golden-snapshot restore; this is the cold-boot path = first launch in a browser).
- Docker was not running and was not touched. `container2wasm` (`c2w`) conversion needs Docker/BuildKit, so **we did not build any custom c2w image**; the c2w and
  qemu-wasm guests measured are the prebuilt public demo artefacts of ktock/container2wasm-demo and ktock/qemu-wasm-demo. Everything downloaded was handled as untrusted data
  (own directory, only served to the browser, never executed on the host; the registry layer for Debian was converted to cpio in memory, never extracted to disk).
- Total downloaded for the spike: about 1.1 GB, all in the session scratchpad (deleted at the end).

## 3. Results at a glance

All rows were booted in headless Chrome and answered an interactive command. Numbers: median-ish of 3 cold runs (range in brackets) unless noted.

| # | Guest | Engine / arch | Download (raw / gzip) | Cold boot to shell prompt | `cat /etc/os-release` round trip | 20 MB sha256 | Extra RSS | Licence of engine |
|---|---|---|---|---|---|---|---|---|
| 0 | **Alpine 3.21 i386 (today)** | v86 / 32-bit x86 | 35 MB image (7.7 kernel + 27.2 rootfs.cpio.gz) + 2.4 MB engine | 8.3 s (5.3 - 9.7; one session 6.3 - 6.8) | 0.21 - 0.25 s | 2.7 - 4.1 s | ~685 MiB (512 MiB guest) | BSD-2-Clause |
| 1 | **Debian 12 (bookworm) i386, built by us (PoC)** | v86 / 32-bit x86 | 38.5 MB (same 7.7 kernel + 30.8 MB initramfs, 81 MB unpacked) | 7.7 s (7.2 - 7.9 quiet; 11.0 - 15.4 under load; 5.3 - 5.7 later) | 0.40 - 0.47 s | 2.5 - 2.8 s | ~660 MiB (512 MiB guest) | BSD-2-Clause |
| 2 | Buildroot 2024.05.2, kernel 6.8.12 (v86 project prebuilt) | v86 / 32-bit x86 | 10.1 MB single bzImage | 3.8 s (3.1 - 3.9) | busybox shell | 5.6 - 8.1 s (busybox sha256) | n/m | BSD-2 (v86); Buildroot GPL-2.0 |
| 3 | Tiny Core 16 (kernel 6.12.11) | v86 / 32-bit x86 | 18.9 MB (5.8 kernel + 13.1 core.gz) | 12.5 s (12.3 - 14.1; one run 10.6); VGA console | 0.11 s | n/m | n/m | BSD-2 / GPL-2.0 |
| 4 | FreeDOS 1.x (v86 floppy) | v86 / 16-bit DOS | 0.74 MB | 0.7 s | n/a (DOS) | n/a | n/m | GPL-2.0 (curiosity) |
| 5 | KolibriOS floppy | v86 | 1.47 MB | **not timed** (downloaded, not driven) | n/a | n/a | n/m | GPL (curiosity) |
| 6 | **Debian sid-slim x86_64 (64-bit!)** | container2wasm / Bochs in WASI | 200 MB raw, 85 MB gzip -6 (5 chunks) | **1.7 s** (1.69 - 1.92) | 0.64 s | **19.5 s** (~7x slower than v86) | ~745 MiB | c2w Apache-2.0; Bochs LGPL-2.1 |
| 7 | Debian sid-slim riscv64 | container2wasm / TinyEMU | 136 MB raw, 67 MB gzip | 1.1 s (0.90 - 1.35) | 0.23 - 0.27 s | 17.9 s | ~470 MiB | c2w Apache-2.0; TinyEMU MIT |
| 8 | Python 3.11.5 image x86_64 | c2w / Bochs | 146 MB raw, 54 MB gzip | 1.9 s (1.7 - 2.6) | python probe 6.5 s | n/m | ~565 MiB | as row 6 |
| 9 | Python 3.11.5 image riscv64 | c2w / TinyEMU | 90 MB raw, 39 MB gzip | 1.2 s (0.7 - 1.6) | python probe 11.6 s (earlier simpler cmd 6.6 s) | n/m | n/m | as row 7 |
| 10 | Alpine 3.21 x86_64 (qemu-wasm demo, with python3/vim) | qemu-wasm: QEMU TCG to wasm, multi-threaded | 145 MB raw (41 wasm + 83 rootfs + 12 kernel + 9.7 initramfs); wasm 14 MB gz, rootfs 65 MB gz | **56 - 74 s** to login prompt (56.1, 73.8, 56.4; an earlier run 42.5) | 0.23 - 0.44 s | python+sha probe 61 s total (not split) | ~1360 MiB | QEMU GPL-2.0 |
| - | Alpine python probe on v86 (for comparison) | v86 | - | - | python probe 4.75 s | - | - | - |

Reading the table honestly:

- **Startup**: c2w's 1 - 2 s is real and is explained by its design: the kernel is pre-booted at build time with wizer for the WASI output (stated in the c2w README;
  the README says this is WASI only, which is the variant measured). The price is a 136 - 200 MB download and **no snapshot/restore API** to the host.
- **Speed**: v86 (JIT to wasm) is the fastest CPU here by a wide margin on the sha256 probe (7x vs Bochs/x86_64 and TinyEMU/riscv64). On the Python probe the gap is
  small (4.8 s v86, 6.5 s Bochs, 11.6 s TinyEMU), so single numbers mislead: expect 1x - 7x, workload dependent. Not measured: compiles, git, pip.
- **qemu-wasm** is the only way found to get aarch64 (its Raspberry Pi demo) but its x86_64 Alpine takes about a minute to boot and 1.3 GiB of tab memory.
  We did not test the aarch64 demo (unmeasured; treated as unusable until proven).
- Every multi-run invocation where one Chrome process booted a qemu-wasm guest several times in a row stalled twice for reasons not diagnosed (separate
  one-run processes were fine); the three qemu-wasm numbers come from separate runs.

## 4. Per candidate

### 4.1 More 32-bit Linux in the existing v86 engine (candidate 1) - WORKS, cheapest, recommended first

- **Debian 12 i386 (PoC, measured)**: the official `i386/debian:bookworm-slim` OCI image (one 29 MB layer) turned into an initramfs by
  `tools/oci2initramfs.py` (pure Python, no Docker, no root, no extraction to disk; whiteouts handled), booted with the **production Alpine kernel** plus its
  `lib/modules` (so virtio-net etc. are available). 38.5 MB total, boots to `root@vyomi-debian:/#` in 5 - 15 s depending on host load, `cat /etc/os-release` ->
  `Debian GNU/Linux 12 (bookworm)`, `uname -mr` -> `6.12.115-0-virt i686`, `dpkg`/`apt` present. Same engine, so snapshot save/restore, 256 - 1024 MiB sizes, ttyS1 agent,
  dropbear/SSH-over-tunnel, and the SW/offline model all carry over unchanged once the boot script (`/init`, agent) is ported.
- **Not done in the PoC**: networking (no iproute2/kmod/dropbear in slim; the Alpine boot.sh assumed them), the ttyS1 agent, git/python packages. They are `apt-get install`
  at image-build time (git, python3, openssh-server or dropbear, iproute2, kmod); estimates: python3 + git add roughly 60 - 90 MB unpacked **(unverified, from typical bookworm sizes)**.
  Debian slim has no `git`/`python3` today (`which git python3` -> not found, measured).
- **Which distros exist as 32-bit userland** (Docker Hub manifests queried 2026-11-26): `debian` (386 in bookworm and trixie), `alpine` (386), `i386/ubuntu` (**only up to 20.04 - the 22.04/24.04 tags are 404**).
  `amazonlinux:2023` = amd64+arm64 only; `rockylinux:9`, `fedora:41` = amd64, arm64, ppc64le, s390x (no 386); `archlinux` = amd64 only (Arch32 is a separate community project, not evaluated).
  **So "Amazon Linux / Rocky / RHEL / Ubuntu 24.04" cannot run on v86 at all**; Ubuntu 20.04 i386 could (same tool, unmeasured) but is end-of-standard-support.
- **Buildroot** (v86-project prebuilt, 10 MB, 3 - 4 s boot, busybox, 256 MiB is plenty): great as a "tiny" image (also `uname` 6.8.12), but no package manager/git/python.
  Provenance of the prebuilt kernel is the v86 maintainer's server (i.copy.sh): we would have to rebuild it ourselves for redistribution (Buildroot is GPL-2.0; source offer needed).
- **Tiny Core 16**: 19 MB, 12 - 14 s to prompt (slower than Alpine/Debian because it unpacks a 13 MB core.gz and then boots a desktop-less userland), only a VGA console (no getty on ttyS0 by default),
  `tce` packages need network. Not worth offering: nothing it provides that Alpine/Debian do not. The ISO was fetched over plain HTTP and the md5 file 404'd, so its integrity is unverified.
- **FreeDOS / KolibriOS**: boot in under 1 s / 1 floppy; curiosities, no relevance to EC2/GCE/Azure VM semantics. Keep out of the product.
- **Alpine variants** (virt vs lts vs edge): same engine and musl userland, differences are kernel config/size only. Nothing measured; would add catalogue rows without adding recognisability.
- **Licences**: v86 BSD-2-Clause (read `wasm/vm/engine/LICENSE.v86` and the repo licence via GitHub API); Debian, Alpine, Buildroot, Tiny Core userlands are free software (mostly GPL/MIT/BSD): redistributing the binaries means shipping/offering the corresponding source and licence texts (compliance work, same as today's Alpine image).

### 4.2 CheerpX / WebVM - NOT USABLE for us (licence), not measured

- Read the CheerpX licensing page (cheerpx.io/docs/licensing) and the WebVM README on 2026-11-26. WebVM itself (the demo app) is Apache-2.0; the **CheerpX engine is proprietary**.
  Community licence = individuals, one-person companies, FOSS projects, technical evaluations. A company using it for a **customer-facing application (paid or free) needs a commercial licence**.
  The free runtime is only served from `cxrtnc.leaningtech.com`; **"Self hosting CheerpX requires a Commercial License"** and "Downloading a CheerpX build for the purpose of hosting it elsewhere is not permitted without a commercial licence".
- Consequence: it cannot run from our own static bundle (breaks the offline/SW Nano model and the no-external-CDN requirement) unless we buy a commercial licence. We therefore did
  **not** download or run it (no measurement, to respect the terms). Known from docs only **(unverified)**: x86 (32-bit) Debian userland, faster than v86, ext2 disk images streamed over HTTP, networking via Tailscale.
- Decision: keep disabled; revisit only if the business wants to buy a licence (contact sales@leaningtech.com).

### 4.3 container2wasm (c2w) - WORKS, best path to 64-bit x86 and RISC-V, with real costs

- Licence: c2w itself **Apache-2.0** (GitHub licence API; LICENSE text read). Emulators it embeds: Bochs (x86_64, **LGPL-2.1**, COPYING read), TinyEMU (riscv64, **MIT**, read on bellard.org/tinyemu), QEMU (only for `--to-js`/other arches, GPL-2.0).
  The output wasm bundles a Linux kernel (GPL-2.0) and the container's userland, so shipping it carries GPL/LGPL source-offer duties (relink/source for Bochs LGPL). Legal review needed before shipping.
- It runs from static files: we vendored xterm.js + xterm-pty (both MIT, licence files included) and browser_wasi_shim (taken as-is from the c2w demo repo; its licence was NOT independently checked, spike-only) into `spikes/nano-vm-images/c2w/libs/` and booted with **no CDN** and no network at all.
  The WASI module runs in a plain Worker (no SharedArrayBuffer needed for the no-network mode that we tested).
- Measured: x86_64 Debian boots to a bash prompt in 1.7 s, `cat /etc/os-release` -> `Debian GNU/Linux trixie/sid`, `uname -m` -> `x86_64` (a genuine 64-bit guest, which v86 can never be). riscv64 in ~1 s.
  Python 3.11.5 images work (x86_64 and riscv64). Debian image has `curl` and `apt` but no `git`/`python3` (`which`, measured) - that is the container's Dockerfile, not a limit of c2w.
- Costs: download 136 - 200 MB per image (85 / 67 MB gzipped), 470 - 745 MiB tab memory, 1 vCPU, and **CPU about 1x - 7x slower than v86** depending on workload. Memory and disk are fixed at conversion time **(unverified; c2w build args)**.
- **No snapshot/restore and no exec side-channel**: Stop would mean losing guest state unless we add a persistent 9p/virtfs mount or tar-over-tty. No ttyS1 agent: the host would type into the tty (fragile) or we would add our own channel in the image.
- **Networking**: c2w supports a browser-fetch HTTP(S) proxy (guest `http_proxy`) and a WebSocket-based netstack; neither gives inbound SSH. Our `vyomi-tunnel` /vm TCP bridge was built around v86's NIC. Reaching `ssh` from the laptop would need a netstack with port-forward (`c2w-net-proxy.wasm`, 21.6 MB) **(unverified: not tested here)**.
- **Building our own image (Ubuntu 24.04, Amazon Linux 2023, Rocky 9 as recognisable userlands)**: `ubuntu:24.04` has amd64 + riscv64 (+arm64); `amazonlinux:2023` and `rockylinux:9` have amd64 + arm64 (no riscv64). `c2w <image> out.wasm` needs Docker + BuildKit
  (README requirements), which is not available on this Mac, so it is **unverified here** and belongs in a GitHub Actions job. Sizes of such images are unknown until built (Debian slim + curl = 200 MB wasm; a bigger userland is bigger).
- Release lag/maintenance: c2w v0.8.5 published 2026-11-04, repo pushed 2026-11-24 (active). README calls it experimental.

### 4.4 QEMU-wasm and JSLinux - qemu-wasm works but is too heavy; JSLinux is a licence no-go

- **qemu-wasm** (ktock/qemu-wasm; licence shown as NOASSERTION by GitHub because it is the QEMU tree: GPL-2.0, LICENSE file read: "QEMU distribution includes both the emulator and various firmware files").
  Measured on its public Alpine x86_64 demo, networking removed (`spikes/nano-vm-images/qemu-wasm/`): 145 MB, login prompt after 56 - 74 s, 1.36 GiB extra tab memory, needs `crossOriginIsolated` (SharedArrayBuffer + threads; our SW can set COOP/COEP but
  it also constrains every embedded cross-origin thing on the page). Works from a static bundle. Offers aarch64 (Raspberry Pi 3 busybox demo, **not run**) and x86_64.
  Too slow/heavy for a default; at most an "experimental architecture" lab.
- **JSLinux (bellard.org/jslinux)**: x86_64/x86 Alpine, Windows 2000, FreeDOS, RISC-V Buildroot/Fedora 33. Terms checked on bellard.org: the technical notes say only **the RISC-V source is published (TinyEMU, MIT)**; the x86 emulator (which also runs Windows NT/2000) has no published source and no licence grant for
  its binaries/images was found (jslinux/tos.html and the FAQ do not exist or are silent). We treated it as **not redistributable**: not downloaded, not measured. If someone wants Bellard's x86 emulator they must ask him. TinyEMU (MIT) itself is free to use, and c2w already ships it.

### 4.5 RISC-V and Arm as an "architecture" option

- **riscv64**: runs today via c2w/TinyEMU (rows 7 and 9): ~1 s to a prompt, 90 - 136 MB download, ~470 MiB. CPU about as slow as Bochs on the sha probe (17.9 s) and slower than Bochs on the Python probe (11.6 vs 6.5 s). Userlands available: Debian, Ubuntu 24.04, Alpine (riscv64 manifests exist; Fedora riscv64 via JSLinux is out for licence reasons).
  No cloud sells RISC-V instances, so it is an educational "architecture" toggle, not something an EC2/GCE/Azure user would map to.
- **aarch64 (Graviton / t4g / Tau T2A / Azure Ampere)**: the only route found is QEMU (qemu-wasm demo or c2w with QEMU emulation, which c2w itself calls "slow") - not measured, expected worse than the 56 - 74 s x86_64 qemu-wasm boot. **Do not offer.** (v86 and Bochs/TinyEMU do not emulate Arm.)

## 5. What runs where (decision matrix)

| Need | v86 (current engine) | c2w (Bochs / TinyEMU) | qemu-wasm | CheerpX | JSLinux |
|---|---|---|---|---|---|
| Free to redistribute from our bundle | yes | yes (with GPL/LGPL compliance) | yes (GPL compliance) | **no (commercial licence)** | **no (no grant found)** |
| No external CDN / offline in our SW | yes | yes (measured, no CDN) | yes (measured) | no | n/a |
| Boot (cold, local) | 5 - 15 s | 1 - 2 s | 56 - 74 s | not measured | not measured |
| Download | 35 - 39 MB | 90 - 200 MB per image | 145 MB | n/a | n/a |
| Snapshot Stop/Start (today's flow) | yes | **no** | no | n/a | n/a |
| ttyS1 agent / exec API | yes | would need new channel | would need new channel | n/a | n/a |
| SSH from laptop via vyomi-tunnel | yes (built) | **not without a netstack bridge** | not tested | n/a | n/a |
| 64-bit x86 | no | **yes** | yes | no | n/a |
| riscv64 | no | **yes** | possible | no | n/a |
| aarch64 | no | via QEMU only | yes (unmeasured) | no | n/a |
| Recognisable AL2023 / Rocky / Ubuntu 24.04 userland | no (no 32-bit builds) | **yes if we build in CI (needs Docker)** | possible but heavy | n/a | n/a |
| git + python in image | yes (Alpine; Debian after apt step) | only if in the Dockerfile | python3 in demo | n/a | n/a |

## 6. Recommended path

1. **Phase 1 - an image catalogue on v86 (Debian 12 i386 + Alpine, optional Buildroot "tiny").** Low risk, reuses everything (worker, snapshot, agent, tunnel, SW lazy loading, golden-snapshot key per image). Debian is the genuinely valuable second option: apt, glibc, a recognisable name on all three clouds.
2. **Phase 2 (only after Phase 1 and a licensing review) - "x86_64 (emulated, beta)" through c2w**, images built in CI with Docker (Debian 12, Ubuntu 24.04, Amazon Linux 2023), downloaded on explicit user opt-in, no snapshot, console-first, networking later.
3. **Do not pursue** CheerpX (licence), JSLinux (licence), qemu-wasm as a default (boot ~1 min, 1.4 GiB RAM), aarch64, Tiny Core, FreeDOS/Kolibri.

### Phase 1 implementation plan (estimates are mine, not measured)

| Step | Work | Est. |
|---|---|---|
| a. Image catalogue | `wasm/vm/images.json` (id, label, arch, kernel/initrd URLs, min/max RAM, golden key, SSH user, default packages); `vm-worker.js` reads image id from the launch message instead of the `IMAGE_VERSION` constant; per-image golden snapshot key already exists in the pattern (`golden:${IMAGE_VERSION}:${mem}`) | 1 d |
| b. Debian image build | CI script (`build-image-debian.sh`, Docker `i386/debian` like `build-image.sh` does for Alpine, or extend `oci2initramfs.py` with .deb unpacking) installing dropbear, iproute2, kmod, git, python3, python3-pip, sudo, curl; port `/init`, `boot.sh` (modprobe + eth0 192.168.86.100/24), `agent.sh` (dash/glibc: needs `base64`, which coreutils provides), apt sources pointing to the allow-listed `/egress` (plain HTTP), `pip.conf`/`gitconfig` as in Alpine | 3 d |
| c. Image trimming | measure the unpacked size with git+python (est. 150 - 200 MB); strip docs/locales/apt lists; compare with Alpine's 27 MB gz; decide if Debian ships as "Standard" with lazy download only on selection | 1 d |
| d. API honesty | RunInstances/`instances.insert`/VM PUT: honour `ImageId`/source image if it is in the catalogue, else keep the Alpine fallback with the existing disclaimer; DescribeImages / images.list / VM image offers expose the catalogue with `Architecture: i386` and a "runs as" annotation | 2 d |
| e. UI | picker in NanoVmPanel / launch wizards (see 7) with size and "first launch downloads N MB" | 2 d |
| f. Tests | parametrise the existing `nano-post-create-{aws-ec2,gcp-gce,azure-vm}-ssh` suites over image id; add os-release assertion per image; golden-snapshot + restore timing | 2 d |
| g. Compliance | licence/source-offer page for the shipped distro bundles (SBOM from `dpkg -l`) | 1 d |

Total about 12 working days for Phase 1 including review/QA slack. Phase 2 (c2w) is a separate project: ~3 - 4 weeks (CI pipeline, host with xterm-pty/SharedWorker, no-snapshot lifecycle, networking and SSH bridge, legal) and should not start before Phase 1 ships.

### Risks

- **Honesty of the cloud mapping**: 32-bit i386 guests are not what Amazon Linux 2023 / Ubuntu 24.04 / Rocky run; the UI must say "Debian 12 (32-bit) runs this AMI" rather than imply the real AMI. EC2 does allow `Architecture: i386` (legacy); GCE and Azure have no 32-bit images, so show a Nano note there.
- **Snapshot size/time**: Debian's 81 MB rootfs in RAM raises the golden snapshot (Alpine was 35 MB zstd according to the earlier spike); a 256 MiB guest may be too tight for Debian + python + git; likely minimum 512 MiB.
- **Boot variance**: our numbers moved 2x with host load; first-launch (cold boot) cost is paid once per browser per image/RAM combination, then restores.
- **Licences/redistribution**: Debian userland is a pile of GPL packages; compliance work required (source or written offer). c2w adds LGPL (Bochs) relink considerations.
- **i386 end-of-life**: Debian 13 reportedly dropped i386 kernels/installer **(unverified)** but the Docker `debian:trixie-slim` manifest still lists a `386` build (measured); Ubuntu i386 stops at 20.04 (EOL for standard support). Plan on bookworm now, revisit at Debian 12 EOL (2026-2028 range, **unverified date**).
- **c2w specifics**: experimental per its README; no snapshot; large downloads; memory 0.5 - 0.75 GiB per tab; GPL/LGPL; networking/SSH unproven.

## 7. What the UI / API could expose (per cloud) and what stays disabled

Proposal (nothing was built in product code):

| | AWS (EC2 RunInstances `ImageId`, `Architecture`) | GCP (instances.insert `sourceImage`) | Azure (VM `imageReference`) |
|---|---|---|---|
| **Enabled, v86 (Phase 1)** | Debian 12 (32-bit) AMI, Alpine 3.21 (32-bit) AMI; `Architecture = i386`; optional Buildroot "tiny" | `debian-12` (32-bit userland note), Alpine as custom image | `Debian:debian-12` offer (32-bit note), Alpine custom image |
| **Behind a "beta / emulated x86_64" flag (Phase 2)** | Amazon Linux 2023 / Ubuntu 24.04 / Debian 12 as 64-bit, 90 - 200 MB opt-in download, console only | same list | same list |
| **Experimental, hidden by default** | riscv64 Debian/Ubuntu ("educational architecture") | same | same |
| **Disabled (keep refusing, with a clear error)** | arm64 (Graviton `t4g`, `T2A`, Azure Ampere), Windows/macOS AMIs, GPU/`p`/`g` families, Rocky/RHEL/AL2023 as native 32-bit (do not exist), CheerpX-based images, JSLinux images, FreeDOS/Kolibri/Tiny Core | arm64, Windows, GPU | arm64, Windows, GPU |

Sizes: unchanged tiers for v86 (256 - 1024 MiB guest RAM per `compute_sizes`; Debian would likely floor at 512 MiB), c2w images fixed at conversion time **(unverified)**.
Existing note in `nano-vm-host.js` ("The cloud's image is not booted: the OS is Alpine...") becomes per-image text driven by the catalogue.

## 8. PoC evidence

- `spikes/nano-vm-images/tools/oci2initramfs.py`: Docker-free, root-free OCI -> newc cpio.gz converter (registry pull, whiteouts, hardlinks, merges the production kernel modules).
- `spikes/nano-vm-images/v86/index.html` + `run-v86.mjs`: boots alpine | debian | buildroot | tinycore | freedos | kolibri on the production v86 engine; `run-v86.mjs debian 3 512 "cat /etc/os-release | head -3; uname -mr"` drives the serial console and times the round trip.
- `spikes/nano-vm-images/c2w/` + `run-c2w.mjs`: vendored c2w browser runner (no CDN), `?img=amd64-debian-wasi-container&chunks=5&net=none`; `qemu-wasm/` for the qemu-wasm demo.
- `spikes/nano-vm-images/evidence/` console transcripts of the round trips and the run timings (verbatim).
- `fetch-images.sh` re-downloads all third-party artefacts (about 1.1 GB, scratch only, untrusted).

Debian 12 i386 round trip (v86, headless Chrome, serial console), verbatim:

```
root@vyomi-debian:/# cat /etc/os-release | head -3; uname -mr; ls /usr/bin | wc -l; which git python3 apt dpkg; echo DONE_$((6*7))
PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"
NAME="Debian GNU/Linux"
VERSION_ID="12"
6.12.115-0-virt i686
274
/usr/bin/apt
/usr/bin/dpkg
DONE_42
```

Debian x86_64 via container2wasm (Bochs), verbatim:

```
root@localhost:/# cat /etc/os-release; uname -m; echo DONE_$((6*7))
PRETTY_NAME="Debian GNU/Linux trixie/sid"
NAME="Debian GNU/Linux"
VERSION_CODENAME=trixie
x86_64
DONE_42
```

## 9. Open questions

1. Does the product want to buy a CheerpX commercial licence? (Only then does "Debian userland, faster, self-hosted" become possible; unquantified.)
2. How much of the 32-bit mismatch is acceptable for AWS/GCP/Azure labelling (see Risks)?
3. Is a 150 - 200 MB opt-in download acceptable for the c2w "x86_64 beta"? Wire size gzip: 85 MB (Debian x86_64), 67 MB (riscv64), 54 MB (Python x86_64).
4. Can `vyomi-tunnel`'s `/vm` bridge be fronted by c2w's netstack (inbound SSH)? Needs a follow-up spike.
5. Legal: GPL/LGPL source-offer wording for bundled distro userlands and Bochs.
6. c2w images (AL2023, Ubuntu 24.04) were not built (no Docker here): sizes and boot times are unknown until a CI spike runs.
7. Memory per guest in c2w is fixed at build time **(unverified)**: confirm the build arg.
8. Why do consecutive qemu-wasm boots in one Chrome process stall (twice observed)? Not diagnosed.
