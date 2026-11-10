# Branch v4/backends-ui

Base: `origin/v4-on-main`. Owner request: in every v4 console (AWS, GCP, Azure) the info/help
side panel explains, per service and per substrate, HOW Vyomi runs that service.

## What it adds

- `consoles/src/common/BackendsPanel.jsx`: the "How Vyomi runs this service" section (summary,
  Offline|Nano toggle defaulting to the running substrate, kind badge, tech chips, notes,
  "Works unchanged with", fidelity bar, "Differs from the real cloud", "Out of scope", collapsed
  "Sources"). Cloud-neutral markup (inherited font/colour, `currentColor` borders, one accent
  per cloud) so it fits Cloudscape, Fluent and MUI and works in light/dark and on narrow screens.
- `consoles/src/common/backends.js`: kind labels, `backendInfo`, `fidelity` (counts of
  full / limited = Dev Simplified / config_only / not_simulated from the registry, per substrate).
- Loader: `import BACKENDS from "vyomi-backends:<cloud>"` in each `kit/Capability.jsx`, resolved by
  an esbuild plugin in `consoles/build.mjs` to `core/capabilities/backends/<cloud>.json`
  (`{}` if the file is absent), so it is bundled like the capability registry: offline and Nano,
  no fetch. Each Capability.jsx also gained `BY_SERVICE` (service id == registry file name, incl.
  files the combined REGISTRY does not spread) and exports `BACKENDS_DATA`, `registryFileFor`.
- Placement: AWS = Cloudscape `HelpPanel` (top-bar help icon, `toolsOpen`); Azure = the `vy-drawer`
  "Help + support" pane (now stays open while navigating between pages; 100vw on phones); GCP had
  no panel, so a top-bar info icon + right-hand aside was added (open state remembered).
- Test `tests/conformance/test_backends_registry.py` (+ `BACKENDS_DIR` override), schema doc
  `BACKENDS-SCHEMA.md`.

## Decisions

- Missing entry -> "Backend details for this service are not documented yet." Never invented text.
- Fidelity is derived, never stored in the data files.
- GCP product id -> file: `security/secret-manager`, `security/kms`, `security/scc` (securitycenter),
  `cloud-hub` (hub). `datastore`, `marketplace`, `binauthz` have no registry/data and say so.

## Open issues

- Data files (v4/backends-aws|gcp|azure) not merged yet; the panel shows the "not documented" line
  everywhere until they land, and the test skips each cloud.
- AWS services without a registry file (imagebuilder, networkmanager, backup) and Azure
  frontdoor / networkmanagers / recoveryservices have no fidelity bar.
- Watch mode does not pick up a data file created after start.
- Duplicate feature-key warnings between azure vms.json/other files predate this branch.
