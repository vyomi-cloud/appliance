# v4/disable-windows-images

Owner: appliance session - Started: 2026-11-26 - Base: origin/v4-on-main (ed15da1d0) - Status: ready to review

## Purpose
Owner decision 2026-11-26: "Windows for now just disable it. Don't remove." Windows VM images cannot run on Mesh (Linux Docker containers, no verified KVM) nor on Nano (v86 Alpine only). They stay visible in the consoles/wizards but cannot be selected or launched.

## The flag
- Python (backend + wizards): `WINDOWS_IMAGES_ENABLED` / `WINDOWS_IMAGES_REASON` and `windows_blocked()` / `windows_rejection()` in `core/compute_sizes.py` (already in the Nano core bundle, no new core file).
- Consoles: `WINDOWS_IMAGES_ENABLED` / `WINDOWS_IMAGES_REASON` / `windowsDisabled()` in `consoles/src/common/windowsImages.js`.

## What it does (flag False)
- AWS: `RunInstances` with a Windows AMI -> 400 `UnsupportedOperation` (core/vpc_core.py `_launch_one`; covers the quickstart AMI and the marketplace `vyomi-ami-win-iis`). EC2 Launch instance: Windows Quick Start radio and Windows AMI options disabled with the reason; Launch button disabled if a Windows AMI is preselected; AMI Catalog Select button disabled; Launch Templates AMI list options disabled. Describe output of existing images/instances unchanged.
- Azure: PUT of a NEW VM with a Windows image reference / windowsConfiguration -> 400 `OperationNotAllowed` (core/azure_compute_disks_vm.py `reject_windows`, wired in core/azure_arm_core.py; existing VMs still update). Create VM Image select: Windows option disabled with a title.
- GCP: `instances.insert` with a `windows-cloud` / `windows-*` sourceImage -> 400 `INVALID_ARGUMENT`. The v4 console never offered a Windows image (api.OS_IMAGES is Linux-only), nothing to disable there.
- Offline legacy API (server.py `/api/ec2/instances` and the GCP legacy create) refuse Windows profiles the same way; the AMI_CATALOG Windows profiles stay in the data.
- Wizard definitions (core/aws_wizards.py `windows2022`, core/azure_wizards.py `windows-2022`) keep the option with `disabled: true` + `disabled_reason`.

## How to re-enable
Set `WINDOWS_IMAGES_ENABLED = True` in `core/compute_sizes.py` and in `consoles/src/common/windowsImages.js`, then `cd consoles && node build.mjs` and `python wasm/build_cores.py`. Nothing was deleted; an actual Windows runtime still has to exist before flipping it.

## Tests
`PYTHONPATH=. python3 tests/conformance/test_windows_images_disabled_core.py` (backend rejection per cloud, Linux unchanged, wizards disabled).

## Likely merge conflicts
`v4/nano-compute-options` touches consoles/src/aws/services/ec2/{LaunchInstance,LaunchTemplates,AmiCatalog}.jsx, the GCP compute pages and azure vms/CreateVirtualMachine.jsx. My edits there are one import line plus single-line changes at: LaunchInstance.jsx (Quick Start `items`, AMI Select `options`, Launch button `disabled`, one Alert line), AmiCatalog.jsx (Select cell), LaunchTemplates.jsx (AMI options map), CreateVirtualMachine.jsx (Windows `<option>`). `core/compute_sizes.py` gets an appended block before `__main__`.

## Open issues
- [ ] Legacy wizard renderers that ignore `disabled` still rely on the backend 400.
