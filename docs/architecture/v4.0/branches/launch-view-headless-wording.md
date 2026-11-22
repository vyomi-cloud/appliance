# v4/launch-view-headless-wording

Owner: Claude (chat session with Rohith) - Started: 2026-11-23 - Base: origin/v4-on-main (20436c02a) - Status: in review

## Purpose
Fix the `lint` job of `ci.yml` (runs on pull requests to `main`). `tests/launcher/test_launch_view_consistency.py`
has failed since the 4.0.0 headless change (`a8bd88125`, 2026-11-07): the Go launcher's banner (`cmd/vyomi/banner.go`)
says "Pro tier: launch an EC2 instance with the CLI/SDK, then ssh ubuntu@<ip>." because the offline console UI was
removed, while the test and the two shell launchers still said "... in the console ...". CI on `main` has been red
since at least 2026-11-18, and the next `v4-on-main` → `main` promotion would hit it.

## Architecture
Wording only. Three lines:
- `tests/launcher/test_launch_view_consistency.py` (expected line)
- `packaging/docker/vyomi` (docker launcher)
- `scripts/cloud-learn` (Max / Multipass launcher)
`cmd/vyomi/banner.go` (Windows launcher) is already correct and unchanged.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Align everything to "with the CLI/SDK" | Restore "in the console" in banner.go | 4.0.0 is headless: there is no offline console to launch EC2 from |

## Verification
All seven `lint` steps of `ci.yml` run locally and pass: py compile, tier_policy load, `wasm/build_cores.py --check`,
the launch-view test (`[PASS] launch view identical in 3 launchers`), `test_backends_up_to_date.py`,
`gen_mcp_matrix.py --check`, `go vet` + `go test` in `cmd/vyomi`. `bash -n` on both shell launchers.

## Open issues
- None.
