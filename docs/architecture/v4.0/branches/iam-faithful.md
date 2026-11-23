# v4/iam-faithful

Owner: this session - Started: 2026-11-23 - Base: origin/v4-on-main (4a9f89f93) - Status: in progress (Phase 0)

## Purpose
Faithful IAM (AWS IAM, GCP IAM, Azure RBAC) for every in-scope service, with per-resource enforcement on/off, on Mesh and Nano. Full design: `docs/architecture/v4.0/IAM-FAITHFUL-DESIGN.md`.

## Architecture
- Phase 0 so far: `scripts/gen_iam_catalog.py aws` writes `core/iam_catalog/aws/<prefix>.json` from the official AWS Service Reference (37 prefixes, 4,463 actions, verbatim IDs, access level, data-plane flag, resource types, condition keys, API-operation -> action map).
- `tests/conformance/test_iam_catalog.py` checks the committed slices offline.
- Next: GCP and Azure catalog parsers, request->permission contract, shared engine `core/iam_engine/` (pure Python), middleware + nano-sw hooks.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Verbatim vendor permission IDs, Vyomi metadata beside them | `vyomi:`-prefixed or cross-cloud canonical IDs | real SDKs, Terraform and pasted policies use the real strings |
| Generate catalogs from vendor data, commit them | hand-typed permissions; fetch at runtime | reviewable diffs; Nano/offline need no network |
| Ship only the in-scope slice | whole-cloud catalogs (~45-50k IDs) | size; refreshed per service by the onboarding gate |

## Open issues
- [ ] Owner decisions assumed (design doc section 4/7/8): full-vs-in-scope catalog, Entra out of scope, Nano same release, default `off`.
- [ ] GCP and Azure catalog parsers (owner: this branch).
- [ ] Engine, hooks, UI, proof (phases 1-5).
