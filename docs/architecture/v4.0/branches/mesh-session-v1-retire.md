# v4/mesh-session-v1-retire

Owner: Claude session (with Rohith) - Started: 2026-11-22 - Base: origin/v4-on-main (37c5661) - Status: in review

## Purpose
Phase 3 of docs/architecture/v4.0/MESH-SESSION-ED25519.md: close MCP-GUARDRAILS finding F2. The portal has minted only Ed25519
(v2) session tokens since 2026-11-22 12:02 IST (first v2 Mesh joined), so every live session is v2 and v1 (HMAC) tokens, which a
Codespace owner could mint with the key the portal used to send, are now refused by the Mesh and the relay.

## Architecture
| Piece | Files | What |
|---|---|---|
| The switch | `core/mesh_session.py`, `wasm/relay/mesh-session.mjs` | `V1_ACCEPTED = False` (code constants; nothing in env/files can turn v1 back on). v1 tokens are refused with `MeshSessionV1Retired`. The v1 code stays until phase 4. |
| Shared v2 signer | `core/mesh_session.py` `sign_v2()` | `mint_v2` and `core/mesh_llm.py` node tokens both use it. `mesh_llm.mint_node_token` / `mint_mesh_session` take `private_key` + `kid` (v1 stays the default only for the v1-path tests). |
| Test key, Python | `tests/mesh_testkey.py` | Signs v2 with the PUBLIC test vector (seed 0x00..0x1f, kid `test-vector`, MESH-SESSION-ED25519.md section 7); tests add its public key to `TRUSTED_KEYS` in their own process (`trust(ms)` / `monkeypatch`). `forged()` signs with another key under the same kid. |
| Test key, Node | `wasm/relay/test-fixtures/{mesh-testkey.mjs,trust-test-key.mjs,trust-test-key-hooks.mjs}` | `testToken()` for in-process use; relay processes a test starts run `node --import trust-test-key.mjs`, a loader hook that adds the test key to `mesh-session.mjs` `TRUSTED_KEYS` (also when mounted at `/opt/relay` in a container). |
| Test key, container | `tools/mcp-eval/it-trust-test-key/sitecustomize.py` | `prerelease-it.sh` local-Mesh stage: mounted with `PYTHONPATH=/opt/vyomi-it`, adds the test key to `core.mesh_session.TRUSTED_KEYS` right after import. |
| Migrated tests | `tests/test_mcp_guardrails_server.py`, `tests/conformance/test_mesh_{session,session_tier,shell,remote_llm,runner_pool,llm}.py`, `wasm/relay/test-{mesh-session-derived,mesh-link,mesh-shell,mesh-shell-ui,mesh-ssh,tunnel-k3s}.mjs`, `wasm/relay/test-fixtures/fake_mesh_sim.py` | Sign v2 with the test key; new checks that a self-minted v1 token (with the right key) is refused on the Mesh API, by `effective_tier()`, at the relay's runner dial-in and for mesh-node joins. `test-mesh-session-derived.mjs` keeps the v1 derivation checks with an explicit `{ v1Accepted: true }` and asserts the default refuses. |
| Docs | `MESH-SESSION-ED25519.md` (phases 2-3), `MCP-GUARDRAILS-INCIDENT-DESIGN.md` (item 5, F2) | Status. |

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Tests trust the public test-vector key only in processes they start (monkeypatch / `--import` hook / mounted `sitecustomize`) | Pin the test key in `TRUSTED_KEYS`; an env var listing extra keys; keep v1 on for tests | A pinned public seed or an env key list lets anyone mint trusted tokens (reopens F2). Keeping v1 on leaves F2 open. The hooks need control of how the process starts, which already means control of the process. |
| Ship nothing test-related in the image | Include fixtures for convenience | The image copies named files only; `.dockerignore` excludes `tests/`; `tools/` and `wasm/relay/test-fixtures/` are never copied. |
| Keep the v1 code until phase 4 | Delete it now | Smaller, reversible change; the derivation tests keep the v1 code honest until it goes. |
| Don't touch the phase-1 row of MESH-SESSION-ED25519.md | Mark it done here | appliance #701 rewrites that row; avoids a merge conflict. |

## Open issues
- [ ] Before merging: confirm the portal still has `MESH_SESSION_TOKEN_VERSION=v2` (DigitalOcean connector was 401 at 20:05 IST, so not re-checked). Turning v1 off while the portal mints v1 would break every Mesh. (owner: Rohith)
- [ ] After merging: publish the Mesh image (`docker-publish.yml` on `v4-on-main`, tag `v4-preview`). F2 is closed for Meshes on that image. (owner: Rohith)
- [ ] Docker-based tests not run here (no Docker in this workspace; Docker Desktop on the Mac was unresponsive): `test_mesh_llm.py` part 2, `test_mesh_llm_rpc.py`, the `prerelease-it.sh` local-Mesh stage. CI / a local Docker run covers them. (owner: CI)
- [ ] `wasm/relay/test-mesh-shell-ui.mjs` times out in this workspace with v1 ON as well (page never loads); not in CI. (owner: unrelated)
- [ ] Go rows of the gate not run here (Go 1.26 toolchain download blocked); no Go code touches session tokens. (owner: CI)
- [ ] Phase 4: remove the v1 code paths, the portal's v1 branch and `MESH_SESSION_KEY`. (owner: next PR)

## Testing
Run in this workspace with `V1_ACCEPTED = False` (`PYTHONPATH=.`, `WS_PKG` set):
- pytest: `tests/test_mesh_session_v2.py` 13, `tests/test_mcp_guardrails_server.py` 13 passed.
- conformance: `test_mesh_session.py` 35/0, `test_mesh_session_tier.py` 7/0, `test_mesh_shell.py` all PASS, `test_mesh_remote_llm.py` 42/0, `test_mesh_runner_pool.py` 56/0, `test_mesh_llm.py` 16/0 (part 2 skipped: no Docker).
- relay: `test-mesh-session-v2`, `test-mesh-session-derived`, `test-mesh-link`, `test-mesh-ssh`, `test-mesh-ssh-transport`, `test-tunnel-k3s` all passed; `test-mesh-shell` passed with `PY` set to a venv that has `websockets` (same as on the trunk).
- `sitecustomize.py`: the real app (`uvicorn server:app`, `VYOMI_ROLE=mesh`) with a test-key token serves `/mesh/status` 200 `mesh:true tier:max` with the hook and refuses the token (`MeshSessionUnknownKey`) without it.
- Guardrail gate (`tools/guardrails/run.sh`): the F2 row turned **PASS** ("v1 (HMAC) session tokens retired; portal key pinned"); every item-5/7/1/8 row passes; Go rows fail here only because the toolchain cannot be downloaded.
- Production checks (read-only): every portal token (session + runner) goes through `_sign_token`, v2 when configured; no appliance code mints tokens; sandbox `main` `.devcontainer/mesh` and `mesh-admin` boot through the fixed `boot-mesh.sh`; the sandbox `booster` folder calls a portal route that no longer exists.
