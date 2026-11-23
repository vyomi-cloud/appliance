# v4/iam-onboarding-gate

Owner: IAM work package onboarding-gate (Claude) - Started: 2026-11-23 - Base: origin/v4/iam-faithful (d4b716218) - Status: ready to merge into v4/iam-faithful

## Purpose
Make "every new service/feature extends IAM" automatic (rule 14) and publish the per-service IAM coverage report.

## What is in it
- `core/iam_catalog/service_map.json`: the ONE mapping inventory service id -> catalog slice(s) (aws prefixes, gcp slugs, azure providers + optional action-prefix filters), `catalog: none` + reason for the 4 services with no slice, and a per-service `floor`.
- `scripts/gen_iam_coverage.py` -> `wasm/iam-coverage.json` + `docs/architecture/v4.0/IAM-COVERAGE.md` (`--check`, `--bump-floors`). Coverage: AWS = `map_aws.coverage()` operation round trip; GCP = share of slice permissions emitted by `_methods.json`; Azure = control-plane action round trip (same logic as test_iam_map_azure.py), narrowed by filters.
- `tests/conformance/test_iam_onboarding_gate.py`: fails on a service missing from the map, stale coverage file, coverage below floor, slice listed in `gen_iam_catalog.py` without a committed file, mapped slice not in the generator.
- Wiring: `.github/workflows/service-gate.yml` gets one additive step "IAM onboarding gate (rule 14)" before the stack boot (runs for every `expansion/*` PR); `tests/conformance/expansion/EXPANSION.md` Definition of done item 0; rule 14 in `V4-BRANCH-ARCHITECTURE.md`. expansion-agent.yml and conformance-release.yml are untouched (the agent's PR is gated by service-gate.yml).

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| floors live in service_map.json | floors in the generated file | generated files are overwritten; the map is the reviewed source |
| GCP coverage = permissions emitted by the method table | method-level coverage | per-service numbers need a permission denominator; this is stricter and honest (many permissions are not API-reachable) |
| enforceable threshold 90% | any mapping | design section 10 |

## Open issues
- [ ] GCP: 0/29 enforceable (13-84% permission coverage); needs map_gcp work per service. Floors are set at today's values.
- [ ] Azure not enforceable: storage 89.8, keyvaults 88.6, nsgs 72.7, eventgrid 87.3 (see IAM-COVERAGE.md).
- [ ] Marketplace, Cloud Hub, Binary Authorization (GCP) and Entra (Azure) have no catalog slice.
- [ ] "Floors only go up" is by review (the test cannot see the previous value without git history).
