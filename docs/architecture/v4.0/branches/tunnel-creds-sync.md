# v4/tunnel-creds-sync

Owner: Azure session (Sudhir) - Started: 2026-11-14 - Base: origin/v4-on-main (96b140bf7) - Status: in progress (not released)

## Purpose
A tunnel holding a revoked or wrong-account key used to exit at start (launchd crash-loop) and nothing told the user. Tunnel 1.2.2 stays up, reports its key state, can be re-paired from the Vyomi page, and the console shows a credentials-sync strip. It also makes the Mesh link self-healing after a dead ssh link (502 "transport closed").

## Architecture
- `packaging/tunnel/bin/creds-sync.mjs` (new): state machine ok|invalid|revoked|none|unreachable; re-check every 5 min, on credentials file change (5 s stat poll), and POST /reload; POST /reset {code} redeems a portal pairing code at the portal pinned from the existing credentials file and rewrites the file (mode 600, .bak kept).
- `vyomi-tunnel.mjs`: no exit on bad key; /health gains `credentials {state,key_id,portal,checked_at,error}` and feature `creds-sync`; /reload and /reset allowed only from Vyomi origins (vyomi.cloud, localhost, 127.0.0.1) or no Origin, with a loopback Host header.
- `mesh-lazy-hub.mjs` (+ `mesh-ssh.mjs` `closed` getter): a 502 from the simulator stream drops the link and replays the buffered request once on a fresh link; a closed transport is never reused; drop reasons are logged.
- `wasm/mesh-widget.js`: strip `#vy-tc` under the Mesh card on every console home. Compares the tunnel's key id with portal `GET /api/account/tunnel-keys/check` (portal branch portal/tunnel-key-check). Reset button, "Reset automatically" toggle (off by default, at most once per 5 min, stops after 3 failures), "Update tunnel" for a 1.2.1 tunnel.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Reset reuses the existing pairing-code flow | New reset API on the portal | Code is single use, bound to the signed-in account, already hashed/throttled |
| Origin allow-list + loopback Host + pinned portal on /reset | Open CORS * | Relay CORS is *, any site could otherwise repoint the tunnel to an attacker account |
| Replay once on 502 | Keep surfacing 502 | Transparent healing; second 502 still surfaces |

## Open issues
- [ ] Tunnel 1.2.2 NOT published to npm / Homebrew tap (needs owner go); until then the strip shows "Update tunnel" for 1.2.1
- [ ] Portal needs the key-check endpoint deployed (portal/tunnel-key-check) and the Nano bundle re-vendored (wasm/vendor_to_portal.py) for the strip to appear on prod
- [ ] Root cause of the earlier prod 502 is unproven; the retry covers the dead-link case, not other causes
- [ ] Strip not seen in a real browser; installer scripts (mac/linux/win) unchanged and still install `vyomi-tunnel@latest`

## Testing
Run: wasm/relay/test-mesh-lazy-hub.mjs, test-tunnel-creds-sync.mjs (fake portal, real tunnel process, origin/security cases), test-tunnel-credentials.mjs (updated: relay now stays up without a key), test-tunnel-creds-widget.mjs, widget_logic_test; portal tests/test_tunnel_pair.py (11, on a DB copy). NOT run: browser, real portal, Windows.
