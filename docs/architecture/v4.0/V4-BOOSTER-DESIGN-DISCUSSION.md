# Booster-pack design — discussion notes (2026-11-02, UNDECIDED — resume later)

## Proposal (user)
Drop the Nano / Pro / Max build split. Everything is Nano (UI + in-browser WASM backends) with
tiers free / student / developer / enterprise. A **booster pack** = the offline appliance ("Pro")
minus its UI, installed on a student/developer laptop or an enterprise GitHub Codespace. The Nano UI
auto-detects it and routes backend calls to it. Open question the design hangs on: **how the Nano
tab talks to the booster.**

## Agreed points
- Tiers become portal-signed **entitlement flags** checked by the booster, not separate builds.
  Substrates collapse to two: browser (Nano) and booster (headless offline appliance, same cores,
  so a superset of Nano). Consoles already speak native cloud APIs over `/_wire`; the service worker
  routes `/_wire` to Pyodide today and would route it to the booster when attached.
- **Fallback is required:** if the booster is unreachable (laptop off, licence not renewed, user on
  another machine) the tab falls back to the in-browser Nano resources (free tier).
- **Roaming:** a Cloudflare tunnel in front of the booster lets the user reach it from anywhere
  while the host machine is up.
- Switch a whole **space** to the booster at once (cross-service links break if the two ends live on
  different substrates). Keep periodic browser snapshots of the space; on fallback boot Nano from the
  last snapshot with a banner; on reconnect OFFER keep-browser vs replace-with-host (no auto-merge).

## Connection model
The **tab always dials the booster** (a browser tab cannot accept inbound connections). Handshake:
tab sends version + pairing token; booster returns version range, entitlements, capability list
(the existing capability registry). Then `/_wire` calls go tab -> booster over the socket (or plain
fetch), with the socket kept for heartbeat, push events and later TCP framing. While attached,
local tools (aws-cli etc.) can hit the booster's own port directly — no relay needed.
Transport order: direct 127.0.0.1 -> local vyomi-tunnel -> Cloudflare tunnel / Codespaces URL.

## Verified facts (probe, 2026-11-02, Chromium via Playwright, from https://vyomi.cloud)
- Default: tab -> `http://127.0.0.1` / `localhost` (fetch AND WebSocket) is **blocked**:
  `ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS` ("Permission was denied").
- With Chrome's **"local-network-access" permission granted**, requests reach the local server
  (a normal fetch then needs CORS headers from the server). So direct localhost works only after the
  user clicks Allow on a one-time per-site prompt.
- NOT tested: Firefox, Safari (Playwright has only Chromium installed; Safari is the riskiest), real
  headed Chrome with a human clicking Allow, a real WebSocket server, a real Cloudflare tunnel.
- Public HTTPS targets (Cloudflare URL, Codespaces forwarded URL) avoid the local-network check and
  mixed content. A page served by the booster itself (same-origin local) also avoids it.

## Current `vyomi-tunnel` 1.0.0 (wasm/relay/local-relay.mjs; npm copy in packaging/tunnel/)
Reverse direction only: tab dials `ws://127.0.0.1:8090/register`; local SDK/CLI HTTP requests are
forwarded over the WS to the freshest open tab (id-correlated; 503 no tab, 504 after 15 s; ping/pong
every 10 s; `/health` beacon with CORS + Private-Network-Access headers used for auto-detect;
loopback-only by default). Gaps for the booster: no tab->host request direction, **no auth** (CORS `*`,
any local process/website can register or call), HTTP request/response only (TCP relay for SSH/DAX
planned as 1.1, not in code), and its PNA comment predates Chrome's new permission prompt.

## Risks / open decisions
1. Browser coverage of direct localhost (Safari/Firefox unknown) -> always ship the tunnel/public-URL
   fallback and an "open the console from your booster" local-served option.
2. Booster listening on localhost or a public tunnel needs: bind 127.0.0.1, origin allow-list
   (vyomi.cloud), per-install pairing token, Host-header check (DNS rebinding), session expiry,
   entitlement check; Cloudflare/Codespaces URLs are internet-reachable so the token is mandatory.
3. Cloudflare tunnels carry HTTP + WebSocket only (no inbound raw TCP); quick tunnels are fragile
   (random URL, no SLA, no SSE); named tunnels need an account + domain. SSH/DAX need the browser-side
   TCP relay over WebSocket frames.
4. Large transfers (S3 uploads) over one multiplexed socket need chunking or an HTTP side channel.
5. Version skew between the always-fresh web UI and an old booster -> handshake version range + graceful
   degradation / update prompt.
6. Fallback semantics still to define: which features degrade without a booster; snapshot cadence;
   reconnect conflict UX.
7. Codespaces: public forwarded port + join token vs GitHub-authenticated private port (unanswered).
8. Should a space move to the booster permanently or fall back automatically (user: fallback is
   required; migration direction/UX still open).

## Suggested next steps (not started)
- Spike: booster stub (handshake, CORS, token check) + tab client with fallback; run behind
  `cloudflared` with a short-lived token-protected URL (needs user OK — publishes a test URL).
- Install Playwright Firefox + WebKit and rerun the localhost probe; user to try real Safari/Firefox.
- Write the full design doc once the transport + auth decisions above are settled.
- User still has a "Design 2" to discuss.
