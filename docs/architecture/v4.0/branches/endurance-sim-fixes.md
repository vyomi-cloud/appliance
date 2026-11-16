# v4/endurance-sim-fixes

Owner: <session / person> - Started: 2026-11-15 - Base: origin/v4-on-main (770a9814a) - Status: in progress

## Purpose
Simulator defects found by the vyomi-endurance harness (real Terraform providers against the simulator). Each fix has a regression in tests/conformance/test_endurance_f1_f2_f4_core.py. Findings log: tests/endurance/FINDINGS.md on v4/vyomi-endurance.

## Architecture
F1 VPC attributes, F2 SQS SSE default, F4 GCP network enforcement order, F6 EC2 DescribeNetworkAcls filters, F7 managed prefix list entries/modify. Nano copies rebuilt with wasm/build_cores.py.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| <what was chosen> | <what was not> | <reason> |

## Open issues
- [ ] <unfinished, unverified or deferred item> (owner: <who>)

## Testing
<what was run, where (Nano on :8099 / headless Docker), and the result; what was NOT run>
