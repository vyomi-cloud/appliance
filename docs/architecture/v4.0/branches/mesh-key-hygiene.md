# v4/mesh-key-hygiene

Owner: Claude session (with Rohith) - Started: 2026-11-22 - Base: origin/v4-on-main (0df22d4) - Status: in review

## Purpose
Guards for the three slips in the first production rollout of v2 (Ed25519) Mesh session tokens on 2026-11-22
(docs/architecture/v4.0/MESH-SESSION-ED25519.md section 6): the seed stored under the wrong name, the kid stored with two extra
characters, and the sandbox boot script that still required the v1 key, so every Mesh failed to boot under v2.

## Architecture
| Piece | File | What it does |
|---|---|---|
| Keygen output | `scripts/mesh-session-keygen.py` | Prints NAME / VALUE / Encrypt / Scope blocks shaped like the DigitalOcean form (no `NAME=value` line to paste whole), the public-key pin lines, and the exact startup line the portal logs for that key. Refuses a kid outside `[A-Za-z0-9._-]{1,64}`. |
| Boot-script check | `tools/guardrails/check-boot-mesh.sh` | Runs a boot script's own `token_usable` + `fetch_session` against a stubbed portal: keyless v2 accepted on the first try, v1 needs its key, v1 without key refused, token/key never logged; plus a static check that no log/echo line expands the token or key. |
| Gate rows | `tools/guardrails/run.sh` | The check on `codespace/.devcontainer/mesh/boot-mesh.sh` always; on the sandbox copy when `VYOMI_SANDBOX_DIR` is set (FAIL blocks releases); a GAP row listing every Mesh file where sandbox differs from `codespace/.devcontainer/mesh`. |
| CI | `.github/workflows/guardrails.yml` | Checks out `vyomi-cloud/sandbox@main` (public, no credentials) into `_sandbox` and sets `VYOMI_SANDBOX_DIR`. |
| Back-port | `codespace/.devcontainer/mesh/boot-mesh.sh` | sandbox #7's two fixes: log the fetched token version; the "not a working Mesh" error no longer prints the token. |
| Tests | `tests/test_mesh_session_keygen.py` | Names, paste-only values, Encrypt flags, public key consistent with the seed everywhere it is printed, kid rule, kid rule matches the pinned kids. |

The portal half (startup log of version / kid / public key, kid charset check) is portal PR `portal/mesh-key-log`.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Behaviour check (run the script's functions with a stubbed curl) | Byte-compare sandbox with the appliance copy as the hard gate | Sandbox already lags in 5 files for reasons unrelated to tokens (gate/lockdown, model, Lambda creds); a byte gate would turn the release gate red for drift that is not a security bug. Drift is shown as GAP instead. |
| CI checks sandbox out; `run.sh` never fetches | `run.sh` curls raw.githubusercontent.com | `run.sh` is deterministic and offline by design; the workflow already owns checkouts. Locally the row is SKIP, never a false PASS. |
| Static leak check on log/echo lines in addition to the probe | Probe only | The leaking line (the "not a working Mesh" error) sits on a path that needs Docker; the probe cannot reach it. |
| Keygen refuses odd kids instead of quoting/stripping | Strip quotes silently | A silent fix in one place (keygen) still leaves the portal setting wrong; refusing in both keygen and portal makes the rule the same everywhere. |

## Open issues
- [ ] Sandbox changes do not trigger this gate (it runs on appliance pushes/PRs and before releases). A check in the sandbox repo's own CI, or a daily scheduled run here, would catch a sandbox regression the day it lands. Owner decision (CI minutes). (owner: Rohith)
- [ ] Port the remaining drift to vyomi-cloud/sandbox (Dockerfile gate/lockdown + python3-venv, compose model qwen3-4b + Lambda creds + real-backend profiles, llm-chat-entry.sh, vyomi-agent-demo, vyomi-gate, vyomi-lockdown), or decide which of these sandbox should not get. (owner: Rohith)
- [ ] Go rows of the gate not re-run in this session's workspace (Go 1.26 toolchain download blocked); unchanged by this branch, CI runs them. (owner: CI)
