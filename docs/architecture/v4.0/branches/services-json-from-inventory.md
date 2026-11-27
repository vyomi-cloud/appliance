# v4/services-json-from-inventory

Why: the portal's "N services" came from `services/registry.json` (v3 expansion registry, 55 released, last changed 2026-10-29) via the release's `services.json`, while the v4 consoles list 89 (`wasm/service-inventory.json`). Rule 13 says portal counts read the inventory.

- `scripts/gen_services_json.py <version> [out]` builds `services.json` (total, per-cloud counts, features, service list) from `wasm/service-inventory.json`; `release.yml` calls it instead of reading the legacy registry.
- `tests/conformance/test_services_json.py`: counts equal the inventory totals, the file passes the portal's `service_catalog._valid`, and `release.yml` no longer reads `services/registry.json`.
- Not in this repo (portal): the hard-coded `data-count="51"` "Real backends" tile in `templates/home.html` must become a generated figure; the portal's bundled default `service_catalog_default.json` (36) is only a fallback. The count shows on vyomi.cloud after the next release publishes the new `services.json`.
- Open: the definition of "real backend" (no field for it in the inventory or the capability registry).
