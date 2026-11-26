# v4/nano-compute-options: Nano compute create flows offer only what the in-browser VM can run (images / OS / architecture)

Base: `origin/v4-on-main` (fresh fetch). Follows `compute-sizes.md` (which already limited sizes); this branch does the same for image / OS / architecture.
One source: `core/compute_sizes.py` (`NANO_GUEST`, `NANO_IMAGES`, `images_restricted()`), vendored unchanged to `wasm/core/` by `wasm/build_cores.py`.

## What a Nano VM really is (from the code)

| Fact | Source |
|---|---|
| Engine v86 (`wasm/vm/engine/libv86.js`, `v86.wasm`), 1 emulated CPU, 32-bit x86 guest | `wasm/vm/vm-worker.js`, `wasm/vm/nano-vm-host.js` (`arch: "i686"`) |
| ONE guest image whatever the cloud record says: Alpine Linux 3.21 (`linux-virt` i386 kernel `vmlinuz` + `rootfs.cpio.gz`), with git, Python 3, pip, apk, dropbear | `wasm/vm/build-image.sh`, `wasm/vm/image/` |
| Guest RAM = `memory_size: mem_mb` MiB (largest tier 1024); the rootfs lives in that RAM | `wasm/vm/vm-worker.js`, `core/compute_sizes.py` (sizes) |
| The cloud's own image is "not booted: the OS is Alpine" | `wasm/vm/nano-vm-host.js` Connect panel text |

## What each flow shows on Nano (Mesh / offline unchanged)

Owner rule: on Nano the FULL catalog stays visible; everything the in-browser VM cannot run is DISABLED (greyed, not selectable) with the reason
"Not available on Nano: runs only in a Mesh", and the Alpine / i386 entry plus the Nano-runnable sizes are enabled and preselected.
Mesh keeps its own behaviour (its size lists are still filtered to what Mesh can run, nothing disabled); offline is unrestricted.

| Cloud | Flow | Nano |
|---|---|---|
| AWS | Launch instance | Quick Start: Alpine Linux (enabled, selected) + the 7 usual tiles disabled with the reason; AMI list: full catalog, only `Alpine Linux 3.21 (i386) - Vyomi Nano` enabled/preselected; Architecture: `32-bit (x86)` enabled/selected, `64-bit (x86)` / `64-bit (Arm)` disabled; Instance type: every type listed, only the 6 Nano sizes enabled |
| AWS | Launch template, AMI Catalog | AMI and Instance type pickers: same disabled options; AMI Catalog "Select" disabled for non-runnable AMIs; note in the header |
| GCP | Create instance, Instance template | OS: Alpine Linux first/selected (Version `Alpine Linux 3.21 (32-bit x86)`), Debian/Ubuntu/Rocky/COS disabled; machine types: all listed, only f1-micro / e2-micro enabled (a machine family with no runnable type is disabled) |
| Azure | Create a virtual machine, VM size blade | Image: Alpine first/selected, Ubuntu/Windows/Debian disabled; VM architecture: Arm64 disabled, x64 selected; Size: all listed, only B1ls / B1s enabled; the size blade's radio is disabled for the rest |

Nano is detected from what the core answered (`vyomiSubstrate` on sizes/images); `vyomiRunnable: false` marks a row the VM cannot run (`runnableRow()` in `consoles/src/common/computeSizes.js`).

## Server side

- Listing: on Nano (`compute_sizes.lists_all()`) EC2 `DescribeInstanceTypes` / `DescribeImages`, GCE `machineTypes.list|get` / `images.list`, Azure `vmSizes` return the whole catalog and add `vyomiRunnable` per row; the runnable types also advertise `i386`. Mesh still lists only what it can run.
- Enforcement is unchanged and still native: EC2 `RunInstances` non-i386 AMI or non-runnable size -> `Unsupported` 400; GCE insert / template insert of another public image -> 404 `NOT_FOUND`, other machine type -> 400 `INVALID_ARGUMENT`; Azure VM PUT -> 400 `PlatformImageNotFound` (image) / 409 `SkuNotAvailable` (size). No `ImageId` defaults to Alpine; an instance inherits `architecture: i386`.
- Not enforced: AWS launch-template ImageId, GCP `disks.insert` sourceImage, Azure VM update paths.

## Fix found on the way

`compute_sizes.py` (added by compute-sizes) was vendored but missing from the three Nano loader lists (`wasm/nano-boot.js`, `wasm/relay/relay-shared-worker.js`, `wasm/relay/nano-endpoint.html`), so `/_wire` EC2 answered `ImportError: cannot import name 'compute_sizes'` in the real Nano bundle. Added to all three (they stay in step with `build_cores.py`; `--check` green).

## Tests

- `tests/conformance/test_compute_images_core.py` (AWS / GCP / Azure on nano, mesh, offline).
- `consoles/tests/smoke-compute-images.mjs` (real Nano preview + a Mesh-substrate dev server): entries present AND disabled (not absent), preselection, notes, launch payloads, native rejections, Mesh unchanged. `smoke-compute-sizes.mjs` now counts enabled options only on Nano.
- `consoles/tests/smoke-nano-browservm.mjs` updated to create its VMs with the Alpine image / a Nano size, and boots each cloud's VM to a shell prompt.
- Generated: `wasm/v4/{aws,gcp,azure}` rebuilt with `cd consoles && node build.mjs`; `wasm/core/*` with `python3 wasm/build_cores.py`.
