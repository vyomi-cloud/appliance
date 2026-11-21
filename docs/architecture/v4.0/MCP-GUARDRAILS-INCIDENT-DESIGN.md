# Guardrails: block, incident, TTL suspension (design, revision 2)

Status: revision 2, 2026-11-21. Replaces the 2026-11-17/18 draft. The release gate and two server-side fixes are built on
branch `v4/mcp-guardrails-gate` (see §6). Incidents and suspension are not built.

## 1. What changed from the first draft

The first draft put a deny-by-default gateway "at the MCP boundary inside the core container". That boundary does not exist:

- `vyomi-tunnel mcp` is a stdio process on the user's laptop. It calls the same native cloud APIs and `/api/*` endpoints that
  boto3, the CLIs and curl call. The simulator cannot tell an MCP request from any other request, so a gate keyed on "MCP"
  stops nobody: anyone who wants to try items 1-8 skips the MCP.
- On a local or Codespace Mesh the user is root (or in the docker group) on the host until `vyomi-lockdown` is enabled.
  `docker exec`, `docker inspect` and `gh codespace ssh` never touch the MCP or the tunnel.
- On Nano the simulator runs in Pyodide in the user's own tab. The code is on their machine; nothing in the tab can be trusted.

So enforcement lives where every caller passes: the Mesh host (`vyomi-gate`, lockdown), the tunnel, the simulator's own
request handling, the network, and the portal. The MCP is treated as one more untrusted client.

## 2. Two threats, two tracks

| | Threat A: an agent misuses the MCP | Threat B: a customer tampers with the licensed core |
|---|---|---|
| Who | A prompt-injected or over-eager coding agent | The person who owns the machine |
| Control | Narrow tool surface: 7 read-only tools + `vyomi_write_env` (refuses paths outside the project and names other than `.env.vyomi*`); the raw licence block never reaches the model | Server-side checks, host lockdown, integrity checks reported to the portal |
| Can it be prevented? | Yes | Partly. On hardware the user owns, much of it can only be detected |
| State | Done (tool surface pinned, #676) | In progress (§3) |

## 3. Premise items: where each is enforced

| # | The MCP server (and any other client) must never be able to | Enforcement point | State | Automated check |
|---|---|---|---|---|
| 1 | access the core containers | `vyomi-gate` (root-owned, fixed verbs); tunnel resolves only `vyomi-i-*` / `vyomi-k3s-*`; `vyomi-lockdown` removes the user's docker group | gate + tunnel built; **lockdown not wired into boot** | `test-mesh-gate.mjs`, `test-mesh-ssh-transport.mjs` |
| 2 | tamper with the licence fingerprint | Portal integrity check (image digest, devcontainer hash); Ed25519 session tokens | not built | GAP |
| 3 | make the core reach outside the tunnel | Network policy on the Mesh (compose internal network / k3s NetworkPolicy), not the MCP process | not built | GAP |
| 4 | change core behaviour or inject code/instructions | Compiled image; lockdown. Needs a definition first: Lambda, `lambda.microvms` and user containers run user code by design | not defined | GAP |
| 5 | change behaviour after limits are enforced upstream | Portal-signed session token (`core/mesh_session.py`): fails closed, Pro locked to one cloud, monotonic expiry, runner tokens refused | built; **bypass open, see F2** | `tests/test_mcp_guardrails_server.py` |
| 6 | instrument agents at runtime | Undefined. Does it mean Bedrock AgentCore emulation, or hooks into the MCP host? | not defined | GAP |
| 7 | toggle internal controls | `require_admin_key` on admin routes, now enforced on a Mesh (F1); budget toggle refused on a Mesh | **fixed on this branch** | `tests/test_mcp_guardrails_server.py` |
| 8 | intercept call flows in/out of the core | Tunnel: `forward api` reaches only the simulator's 9000/9443; `llm*` and core names refused; lockdown for host-level capture | tunnel built; host capture open until lockdown | `test-mesh-ssh-transport.mjs` |

## 4. Findings from the 2026-11-21 review

| ID | Finding | Item | Severity | State |
|---|---|---|---|---|
| F1 | The Mesh compose sets `CLOUDLEARN_DISTRIBUTION_MODE: developer`, and `require_admin_key` returned early outside appliance mode. Every admin route was open on a Mesh: `/api/runtime/budget/disable` (bypasses the host-clamp gate), `/api/shared/*`, `/api/tenants`, `/api/security/audit-*`, and the legacy HMAC branch of `/api/license/activate` | 7 | High | **Fixed**: `admin_checks_apply()` = appliance mode **or** `VYOMI_ROLE=mesh`; the budget toggles refuse on a Mesh even with the key |
| F2 | The portal hands the Codespace the session HMAC key (`boot-mesh.sh` `fetch_session`), and the user can read it (`docker inspect`, or the same portal call) until lockdown is on. With it they can mint a Max token with any `session_end` for their own Mesh | 5 | High | Open. Fix = Ed25519: the portal signs, the Mesh holds only the public key (MESH-SOFTWARE-PROTECTION layer 5) |
| F3 | On a Mesh, `/api/*` runs with CORS `*` and the session token is ambient (read from the environment when the request has none). A web page open in the user's browser can call the forwarded API on `127.0.0.1:<port>` and read the answers | 8 | Medium | Open. Needs a decision: Nano tabs homed on a Mesh may depend on cross-origin access. Option: the loopback-plus-`*.vyomi.cloud` origin list that `/mesh/*` already uses |
| F4 | `vyomi-lockdown` is built but not wired into boot, so items 1, 2 and 8 rest on the user not using their own docker access | 1, 2, 8 | High | Open (needs a root boot helper and a real-Codespace test; MESH-SOFTWARE-PROTECTION §5) |

## 5. Nano

Nano cannot be protected like a Mesh: the simulator is client-side code. Decide what Nano may expose, keep anything secret
(model keys, licence logic) behind the relay or the portal, and enforce there. Nano is not part of the release gate's
premise checks.

## 6. Release gate (built)

- `tools/guardrails/run.sh` runs one deterministic check per item (no network, no Docker) and prints PASS / FAIL / GAP.
  GAP rows keep the summary honest about what the gate does not cover.
- `.github/workflows/guardrails.yml` runs it on pushes that touch the guarded paths, on every PR into `v4-on-main`, and as a
  reusable workflow.
- Hard gate: `release.yml` (build), `release-candidate.yml` (build), `docker-publish.yml` (the Mesh image) and
  `tunnel-release.yml` (publish) all `need` it. Red blocks the artifacts.
- Notification: when red outside a PR, an issue labelled `release-gate` is opened, or commented on if one is already open.
  Add a chat webhook once a channel is chosen.
- Endurance estate cycles are **not** in this gate: long, flaky runs would push people to skip it. Keep them as a
  notifying (non-blocking) job.

## 7. Incidents and suspension (not built)

1. **Event**: on a block, the simulator emits a signed event (simulator id, account, rule id, timestamp, request digest; no
   payloads or secrets) to the portal. The core holds no GitHub token.
2. **Record**: the portal database is the system of record. GitHub issues are filed only for a new rule type, an aggregate
   ("rule 7 hit 50 times across 12 accounts this week"), or a suspected false positive. Customer account ids do not go into
   GitHub, and a scripted probe must not be able to flood it.
3. **Strikes**: severity tiers. Hard tamper signals (image digest or devcontainer hash mismatch, a forged or replayed
   token) count as a strike. Policy hits (items 4, 6, 7) are probes: logged and reviewed, not counted.
4. **Suspension**: first version flags for manual review only. Auto-suspend (TTL ~72 h, cancelled by a clear) only on hard
   tamper signals. The portal owner clears; enterprise admins clear their own accounts (enterprise-access approval flow).
5. **Reporter silence** is not a strike: offline use is the product. Treat a missing heartbeat as stale attestation and
   degrade Pro/Max features after a grace period.

## 8. Open decisions

| Decision | Recommended default |
|---|---|
| Auto-suspend vs review-first | Review-first; auto only on hard tamper signals |
| Core vs user-workload boundary (item 4) | "Core" = the `simulator` and `llm*` containers, their images and config; anything the user deploys through a cloud API is a workload |
| Meaning of item 6 | Decide, or drop it |
| CORS on a Mesh (F3) | Loopback + `*.vyomi.cloud` origins, as on `/mesh/*`, after checking Nano-on-Mesh |
| Notification channel | The `release-gate` issue now; add chat once chosen |
| Dedupe | One record per (simulator, rule, 24 h) with a counter |
