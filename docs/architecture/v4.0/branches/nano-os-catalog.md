# v4/nano-os-catalog: Nano AWS "AMI not loading" fix + honest image/tool labelling

Base: `origin/v4-on-main` at d3c597582. Two tasks.

## Task 1: "Amazon Machine Image (AMI) is not loading" on EC2 Launch instance (Nano)

Reproduced in headless Chrome 158 (Playwright) against `node consoles/nano_preview.mjs` on the merged trunk, fresh profile each time.

What the user sees: AMI select empty, summary "Software Image (AMI) -", "Launch instance" disabled (screenshot `repro-c-20s.png`). Catalog wire calls (DescribeImages / DescribeInstanceTypes) are answered only when the backend is up.

Measured causes (each on the merged trunk; the pre-merge commit ed15da1d0 behaves the same, so this is NOT a regression of the d3c597582 merge):

1. `wasm/nano-boot.js` (and `wasm/nano-sw.js`) awaited `serviceWorker.register()` / `reg.update()`. On a first visit the update job sat about 60 s (measured with a register/update/ready trace: `update done` at 60.4 s; after the "reload once under the service worker" the second page's `register()` queued behind it for another 60 s). Pyodide only started after that, so the catalog arrived at about 65 s (and up to 150 - 180 s with a slow Pyodide CDN).
2. If the backend is not ready within the service worker's ~60 s hold, the worker answers HTTP 500 `no client to run the in-browser backend` (captured on the wire). The page loads its catalog once, so the AMI list then stayed empty for good.

Fix:
- `wasm/nano-boot.js`, `wasm/nano-sw.js`: register/update are no longer awaited (only `serviceWorker.ready` is); `update()` only when the page was already controlled. Measured: Nano ready in about 4.5 - 5.4 s on repeated fresh profiles (was 65 s+).
- `consoles/src/common/nanoWireRetry.js` (imported by the aws/gcp/azure `main.jsx`): on Nano a `/_wire` call answered with exactly that 500 waits for `backendReady()` and is repeated (max 3). Everything else passes through.
- Test: `consoles/tests/smoke-compute-images.mjs` forces the first catalog calls to answer that 500 on a fresh profile and asserts the AMI list still loads and Launch is enabled; it also prints the time to enabled. The Mesh expectations now allow the disabled Windows rows (the three Mesh FAILs on the merged tree were this test not knowing about disable-windows-images).

Residual: a rare stall remains in this dev environment (Pyodide from the jsdelivr CDN, since `wasm/pyodide-source.json` says local=false in the repo; the portal sync flips it). The retry makes the picker recover.

## Task 2: Nano image catalog (scope changed by the owner)

Requirement: every runnable Nano image must provide Python 3, pip, apk and git. apk is Alpine's package manager, so **Debian 12 i386 was evaluated and dropped** (no apk). Nothing of it is kept in this branch. The spike (research, PoC `oci2initramfs.py`, measurements: 38.5 MB image, boots in 5 - 15 s, no git/python in slim) lives on `origin/v4/spike-nano-vm-images` (`docs/spikes/nano-vm-images.md`).

So Alpine Linux 3.21 i386 stays the only runnable image on all three clouds; everything else stays listed and disabled ("Not available on Nano: runs only in a Mesh", Windows via its flag).

Changes:
- `core/compute_sizes.py`: `NANO_TOOLS`, `NANO_SUMMARY` = `Alpine Linux 3.21, 32-bit x86: Python 3, pip, apk, git`, used as the image description (AWS AMI description, GCP image description, Azure offer description). `core/vpc_core.py` seeds/refreshes the AMI description.
- `consoles/src/common/computeSizes.js`: `IMAGE_SUMMARY`; the per-cloud note and the AWS AMI field state exactly that string.
- `wasm/vm/nano-vm-host.js`: Connect panel text is accurate ("whatever cloud image the record names, the guest is always Alpine Linux 3.21, 32-bit x86 (Python 3, pip, apk, git), not the real Amazon Linux / Ubuntu / Debian / Windows image").
- Tests: `tests/conformance/test_compute_images_core.py` (summary/descriptions, data-driven per cloud); `consoles/tests/smoke-nano-browservm.mjs` discovers every image the catalog flags runnable and, for each, boots it and runs `python3 --version`, a small python run, `pip --version`, `apk --version`, `git --version`, `cat /etc/os-release` in the VM shell, so a future image cannot be enabled without passing.
