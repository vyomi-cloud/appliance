# Architecture docs — organised by release version, then topic

Layout: `docs/architecture/<release>/<topic>/` — each doc is filed under the
**release version current when it was authored**, then grouped into a meaningful
**topic** folder. Markdown sources and their converted PDFs live side by side.

## v1.0 — founding design + first GA (created ≤ 2026-06-15)
- `architecture/` — `CLOUDLEARN_FULL_ARCHITECTURE` (md+pdf), `CLOUDLEARN_LLD` (md+pdf)
- `diagrams/` — `component_diagram` (md+pdf), `service_spawn_diagram` (md+pdf)
- `parity/` — `provider_gap_matrix`, `gcp_gap_analysis`, `azure_console_report`, `cross_cloud_console_parity`
- `planning/` — `FIDELITY_PLAN`, `distribution_strategy`, `mvp-backend-stack`
- `deployment/` — `single_vm_appliance_and_terraform`, `PRODUCTION_DEPLOYMENT`
- `process/` — `CONTRIBUTING`
- `release-notes/` — `RELEASE_NOTES_v1.0`

## v2.0 — v2.0.x line (2026-06-17 … 06-20)
- `deployment/` — `MIGRATION-v2`
- `process/` — `RUNBOOK-rc-cycle`
- `status/` — `progressive-startup-STATUS`

## v2.9 — v2.4–v2.9 parity + console series (2026-07-13 … 09-21)
- `parity/` — `PARITY-GAPS`
- `telemetry/` — `install-count-telemetry-issue`
- `planning/` — `ROADMAP-v3`, `COVERAGE-PLAN`, `vyomi_csp_mvp_plan`
- `design/` — `vyomi_csp_design`

## v3.0 — v3.0.x line (2026-09-25 onward)
- `architecture/` — `APPLIANCE-ARCHITECTURE` (md+pdf) — current appliance + Nano architecture
- `design/` — `CONSOLE-UX-REDESIGN`
- `console/` — `console-next-P0-README`
- `marketing/` — `vyomi_landing_page`

---
Notes:
- Release version = the latest git tag on or before each doc's creation date
  (buckets at major.minor; the v1.0 set predates the first tag, `v0.0.1-rc1`
  2026-06-10, and is the design `v1.0.0` was built from).
- Docs are filed by **creation** date, not the version they discuss (e.g.
  `ROADMAP-v3` sits in v2.9 because it was written during that series).
- Per-shipped-version release *notes* live separately in `../releases/`.
