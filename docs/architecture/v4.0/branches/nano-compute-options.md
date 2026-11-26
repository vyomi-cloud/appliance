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

## What each flow shows on Nano (Mesh / offline unchanged: full catalog)

| Cloud | Flow | Nano |
|---|---|---|
| AWS | EC2 Launch instance, Launch template, AMI Catalog | Quick Start: only "Alpine Linux"; AMI: only `Alpine Linux 3.21 (i386) - Vyomi Nano`; Architecture: only `32-bit (x86)` (a real EC2 option); inline note (Launch instance) / header description (AMI Catalog) / field description (Launch template) |
| GCP | Create instance, Instance template | Operating system: only `Alpine Linux`, version `Alpine Linux 3.21 (32-bit x86)`, image `projects/vyomi-nano-cloud/global/images/family/alpine-3-21-i386`; note under "Boot disk" |
| Azure | Create a virtual machine | Image: only `Alpine Linux 3.21 (32-bit x86) - Vyomi Nano` (imageReference `vyomi:alpine-nano:3.21-i386`); VM architecture: only x64 (Arm64 hidden); note under Image |

The note is one line: "Nano runs VMs inside your browser: only the image below is available (Alpine Linux 3.21, 32-bit x86). Launch a Mesh for the full catalog."
Nano is detected from what the core answered (`vyomiSubstrate: "nano"` on sizes / images); before that loads the Nano page meta decides (`onNano()` in `consoles/src/common/computeSizes.js`).

## Server side (cheap and consistent, so done)

- EC2: `DescribeImages` lists only i386 AMIs (the Alpine quick-start; a named `ImageId` still describes, so existing instances keep their AMI name); `DescribeInstanceTypes` adds `i386` to the supported architectures; `RunInstances` with an AMI that is not i386 -> `Unsupported` 400; no `ImageId` defaults to the Alpine AMI; an instance inherits `architecture: i386`.
- GCE: `images.list/get` on `vyomi-nano-cloud` serves the Alpine image, public projects (debian-cloud, ubuntu-os-cloud ...) are hidden; `instances.insert` / `instanceTemplates.insert` with another public image -> 404 `NOT_FOUND` ("The resource 'projects/.../global/images/...' was not found"); project-local images (made from a Nano disk) are accepted.
- Azure: `virtualMachines` PUT with a marketplace `imageReference` other than the Alpine one -> 400 `PlatformImageNotFound`; a custom image `id` or no reference is accepted.
- Not enforced server side: AWS launch-template ImageId, GCP `disks.insert` sourceImage (the console never sends it: CreateDisk makes a blank disk), Azure VM-update paths.

## Fix found on the way

`compute_sizes.py` (added by compute-sizes) was vendored but missing from the three Nano loader lists (`wasm/nano-boot.js`, `wasm/relay/relay-shared-worker.js`, `wasm/relay/nano-endpoint.html`), so `/_wire` EC2 answered `ImportError: cannot import name 'compute_sizes'` in the real Nano bundle. Added to all three (they stay in step with `build_cores.py`; `--check` green).

## Tests

- `tests/conformance/test_compute_images_core.py` (AWS / GCP / Azure on nano, mesh, offline).
- `consoles/tests/smoke-compute-images.mjs` (real Nano preview + a Mesh-substrate dev server): lists, notes, launch payloads, native rejections, Mesh unchanged.
- `consoles/tests/smoke-nano-browservm.mjs` updated to create its VMs with the Alpine image / a Nano size, and boots each cloud's VM to a shell prompt.
- Generated: `wasm/v4/{aws,gcp,azure}` rebuilt with `cd consoles && node build.mjs`; `wasm/core/*` with `python3 wasm/build_cores.py`.
