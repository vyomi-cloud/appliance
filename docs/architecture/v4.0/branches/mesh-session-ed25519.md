# v4/mesh-session-ed25519

Owner: Rohith (prepared by Claude, 2026-11-21) - Base: origin/v4-on-main (8c8ae09) - Status: ready for review (phase 1 of 4)

## Purpose
Close guardrails finding F2: a Codespace owner holds the per-session HMAC key, so they can mint a Max token with any end time
for their own Mesh. This branch is phase 1 of `../MESH-SESSION-ED25519.md`: the Mesh and the relay accept Ed25519 (v2) tokens
verified with pinned public keys, and still accept v1. **F2 is still open after this merges.** It closes at phase 3.

## Architecture
| Change | Where |
|---|---|
| v2 verify (pinned `TRUSTED_KEYS`, lazy `cryptography` import), `mint_v2` reference, `V1_ACCEPTED` constant, v1/v2 dispatch | `core/mesh_session.py` |
| Same in JS: `verify` handles v2 (`trusted` / `v1Accepted` options for tests only), `mintV2` | `wasm/relay/mesh-session.mjs` |
| A v2 token needs no key at boot (`token_usable`) | `codespace/.devcontainer/mesh/boot-mesh.sh` |
| Key generation for the portal secret; prints, never writes | `scripts/mesh-session-keygen.py` |
| Portal spec, rollout phases, test vector | `docs/architecture/v4.0/MESH-SESSION-ED25519.md` |
| Tests: 13 Python (incl. Python <-> JS cross-signing, constants parity, spec vector) + 10 relay checks | `tests/test_mesh_session_v2.py`, `wasm/relay/test-mesh-session-v2.mjs` |
| CI: relay test in tunnel-mcp-checks; both in the guardrail gate, plus an F2 row that is GAP until phase 3 | `.github/workflows/*.yml`, `tools/guardrails/run.sh` |

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Public keys and `V1_ACCEPTED` are code constants | Env var or file on the Mesh | The Codespace owner controls the Mesh's env and files; either would reopen F2 |
| `kid` inside the signed payload, several keys allowed | One fixed key | Key rotation without a flag day |
| Keep accepting v1 in this branch | Refuse v1 now | The portal still mints v1; refusing it now would stop every Mesh |
| Same constants in Python and JS, checked by a test | One shared JSON file | The relay ships separately from `core/`; a test keeps them equal |
| Lazy `cryptography` import | Top-level import | Nothing else in the module needs it; a missing dependency answers 503 instead of breaking import |

## Open issues
- [ ] Phase 2 (owner + portal): generate the key, pin the public key in both files, set the portal secret, mint v2, stop returning `key`.
- [ ] Phase 3: set `V1_ACCEPTED = False` in both files after 8 h of v2-only minting; release the Mesh image and redeploy the relay.
- [ ] Where the hosted relay runs is not in this repo: it must be redeployed with this `mesh-session.mjs`.
- [ ] `tools/mcp-eval/prerelease-it.sh` mints a v1 token for the local-mesh stage; after phase 3 that stage needs a portal-issued token.
- [ ] Residual: a modified simulator image can pin its own key (MESH-SOFTWARE-PROTECTION layers 4 and 6).
- [ ] `core/*.py` and `wasm/**` are shared paths: claims row (CLAUDE.md rules 2 and 5).

## Testing
- `tests/test_mesh_session_v2.py` 13 passed; `wasm/relay/test-mesh-session-v2.mjs` 10 passed.
- Regression, unchanged results: `test-mesh-link`, `test-mesh-shell`, `test-mesh-ssh`, `test-tunnel-k3s`, `test-mesh-session-derived`;
  conformance `test_mesh_session` (31), `test_mesh_session_tier` (6), `test_mesh_shell`; `tests/test_mcp_guardrails_server.py` (13).
- `tools/guardrails/run.sh` (non-Go rows) green, with the new F2 GAP row.
- Not run: `test-mesh-shell-ui.mjs` (needs Playwright; fails the same way on the trunk here), a real Mesh, the portal.
