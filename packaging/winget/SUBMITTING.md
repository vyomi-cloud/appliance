# Publishing Vyomi to winget

`winget install Vyomi.Vyomi` only works once the manifest is merged into
[microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs). Getting
there is **two distinct phases** — the automation in `release.yml`
(`winget-submit` job, `vedantmgoyal2009/winget-releaser`) handles phase 2 but
**cannot do phase 1**, because winget-releaser only publishes *updates to
packages that already exist*.

## Current state
- Manifests in this dir are current: **PackageVersion 2.1.0.1**, real
  `InstallerSha256` (`3EFA…7116`), correct `InstallerUrl`.
- `Vyomi.Vyomi` is **not yet in winget-pkgs** → `winget install` returns
  "No package found".
- Repo secret **`WINGET_TOKEN` is NOT set** → the `winget-submit` job is
  skipped on every release.

## Phase 1 — first-ever submission (one-time, MANUAL)
A brand-new package's first version must be submitted by hand. Easiest path is
`wingetcreate` on a Windows machine:

```powershell
winget install Microsoft.WingetCreate
# Generates all 3 manifests, auto-computing SHA256 + ProductCode from the MSI:
wingetcreate new https://github.com/vyomi-cloud/appliance/releases/download/v2.1.0.1/cloud-learn-2.1.0.1-x64.msi
# When prompted, use identifier Vyomi.Vyomi and the metadata from the yaml here
# (Publisher "Vyomi Cloud", License BUSL-1.1, Moniker vyomi, tags, etc.).
# Then submit (opens the PR to microsoft/winget-pkgs):
wingetcreate submit --token <GITHUB_PAT_with_public_repo>
```

The PAT is a **classic token with `public_repo` scope**; `wingetcreate` forks
winget-pkgs for you. After submit, Microsoft's automated validation pipeline +
a moderator review must pass before merge (typically hours, sometimes a day).
Once merged, `winget install Vyomi.Vyomi` works.

> Alternative to wingetcreate: open the PR manually by copying these three
> yaml files into `manifests/v/Vyomi/Vyomi/2.1.0.1/` on a fork of winget-pkgs.
> wingetcreate is preferred because it fills ProductCode automatically.

## Phase 2 — every release after (AUTOMATED)
1. Add repo secret **`WINGET_TOKEN`** = the same classic PAT (`public_repo`).
2. Nothing else — the `winget-submit` job runs on each tag and
   winget-releaser opens the version-bump PR automatically (it auto-computes
   SHA256 + ProductCode from the release MSI).

## Checklist
- [ ] Create classic PAT (`public_repo` scope)
- [ ] Phase 1: `wingetcreate new … && wingetcreate submit` → PR merged
- [ ] Phase 2: set `WINGET_TOKEN` repo secret → future releases auto-update
