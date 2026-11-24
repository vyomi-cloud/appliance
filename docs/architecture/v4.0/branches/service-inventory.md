# v4/service-inventory

Owner: this session - Started: 2026-11-23 - Base: origin/v4-on-main (4a9f89f93) - Status: in progress

## Purpose
One generated catalogue of what Vyomi simulates, so the portal (and docs) never carry a hand-typed service count. Adds rule 13.

## Architecture
- `scripts/gen_service_inventory.py` parses `consoles/src/{aws,gcp,azure}/services/registry.js` (id, title, category, v4 module) and counts capability entries in `core/capabilities/<cloud>/<id>.json`; writes `wasm/service-inventory.json` (deterministic; `--check` for CI).
- `tests/conformance/test_service_inventory.py` fails when the file is stale or a registry entry lacks title/category.
- The file lives in `wasm/`, so the existing Nano bundle vendor sync carries it into the portal (`app/nano/service-inventory.json`); the portal topic `portal/service-inventory` reads it.
- Today: 86 services (AWS 26, GCP 29, Azure 31), 1421 console features.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Source = console registries + capability registry | counting `core/*_core.py` backends; capability file names | backends are not user-visible services; capability file names diverge from console ids |
| Regex-parse registry.js | import it with node | the GCP registry imports MUI icons; parsing keeps the generator dependency-free and runnable in CI |
| Commit the generated JSON, test with --check | generate at portal build time | the portal must work from the vendored bundle alone; a stale file fails the appliance PR, not the deploy |

## Open issues
- [ ] "service" = one registry entry; owner to confirm whether multi-product entries should count separately (the "90" figure).
- [ ] Wire the service-expansion pipeline to run the generator (owner: expansion pipeline).
- [ ] Other hand-typed counts (README, release notes, compare pages) to be switched to the inventory.
