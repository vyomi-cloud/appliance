# v4/vyomi-endurance

Owner: appliance session (Claude) - Started: 2026-11-15 - Base: origin/v4-on-main (770a9814a) - Status: Phase 0 in progress

## Purpose
Mission **vyomi-endurance**: one enterprise-grade reference estate ("Vyomi Reference Estate") per cloud that wraps EVERY capability
Vyomi offers (VPC to snapshots, DB to compute, Lambda to AI, plus IAM, KMS, messaging, observability, lifecycle) so a regression in any
existing feature is caught. The estate is exported as a Terraform module and every release must get a green tick on the Terraform run
(init/validate, apply, no-diff re-plan, drift, SDK+CLI+console assertions, destroy, re-apply). The app itself is a thin shell; the
product is 100% capability coverage. The AI plan is owned by another session; the AI layer only plugs into its interface.

## Architecture
- `tests/endurance/build_manifest.py` generates `manifest.json`: one row per capability id in `core/capabilities/<cloud>/*.json`
  (the registry that already claims what each console feature does on Nano and offline/Mesh). 1,443 rows at the start.
- `tests/endurance/estate/coverage-map.json`: every manifest id maps to {stage, terraform resources, verifiers sdk/cli/ui, substrate}
  or carries a written `excuse`. `coverage.py --gate` fails on any uncovered or stale id, with an optional ratchet while it fills in.
- Substrates: Mesh (real appliance, blocking gate, 100% of rows) and Nano (parity, declared limits; blocking once tunnel route proven).
- Each capability is verified three ways (native SDK, real CLI, console via Playwright) and cross-checked: created via one path, seen via the other two.
- Release wiring: required job `terraform-estate` in the release workflow, report as artifact + a line in the release notes.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Ground truth = the capability registry | Hand-written service list | It is already per-feature, tested, and CI-enforced; new features appear as uncovered rows automatically |
| Terraform estate + verification layer | Terraform only | Many capabilities (SSH, data CRUD, restore timing, invoke) are not Terraform resources |
| Mesh blocking, Nano reported | Both blocking now | Nano lives in a browser tab; Terraform reaches it only via the tunnel |
| Registry duplicates kept as one row, recorded | Fail the build | Not this branch's job to fix the registry; visible in manifest.json |

## Open issues
- [ ] Azure: azurerm has weak custom-endpoint support; spike needed (Phase 0).
- [ ] Terraform/OpenTofu binary not installed on the dev machine; CI installs a pinned version.
- [ ] Registry duplicate id `azure.aks.backup` (in aks.json and panels.json).
- [ ] 925 capabilities are `limited`: the estate must verify what each limitation claims, not just that the call returns.
- [ ] Nano headless run needs a test token for the /nano login gate (owner approved).
