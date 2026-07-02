# Reaching Vyomi-Nano from your SDK/CLI — the tunnel

Vyomi-Nano runs the cloud simulator **entirely in your browser tab** (Pyodide +
the conformance cores). To let a local app — `aws`/`boto3`, `azure-cli`, a native
SDK, Terraform — talk to that in-browser sim, Nano uses a small **reverse
tunnel**: the tab opens an outbound WebSocket to a relay; requests you send to
the relay are forwarded to the tab and answered by the in-browser handlers.

```
  your app  ──HTTP──▶  relay  ──WebSocket──▶  Nano tab (Pyodide + cores)  ──▶  response
```

There are **two relays**, and the Nano tab uses whichever is available —
preferring local, falling back to cloud, automatically.

| | **Local tunnel** | **Cloud tunnel** |
|---|---|---|
| Install | `brew install vyomi-cloud/tap/vyomi-tunnel` | none (default) |
| Endpoint | `http://127.0.0.1:8090` | `https://relay.vyomi.cloud/<session>` |
| Runs | on your machine | Cloudflare edge (Durable Object) |
| Best for | fast, private, offline, no size caps | zero-install, reachable from anywhere |

## Recommended: install the local tunnel (one command)

```bash
brew install vyomi-cloud/tap/vyomi-tunnel
vyomi-tunnel
```

Open (or refresh) the Nano tab. The frozen footer flips to
**“Relay tunnel: connected · local (fast · private)”** and shows the endpoint.
Point your tools at it:

```bash
aws --endpoint-url http://127.0.0.1:8090 s3 mb s3://demo
aws --endpoint-url http://127.0.0.1:8090 s3 ls
```

```python
import boto3
s3 = boto3.client("s3", endpoint_url="http://127.0.0.1:8090")
s3.create_bucket(Bucket="demo")
```

## If you skip the install: the cloud tunnel just works

Don't want to install anything? Do nothing. When no local tunnel is detected,
Nano connects to the hosted Cloudflare relay and the footer shows
**“connected · cloud (Cloudflare)”** with a `https://relay.vyomi.cloud/<session>`
endpoint to point your tools at.

## Install (or stop) the local tunnel any time — it switches live

Detection is **dynamic and two-way**, with no reload:

- Run `vyomi-tunnel` later, mid-session → Nano **switches to local** within ~15s.
- Quit it → Nano **falls back to cloud** within ~30s.

So the local install is genuinely optional and reversible: start on cloud today,
`brew install` next week, and everything keeps working — the tab just moves to the
faster local path when it appears.

> **How detection works:** the local tunnel serves `GET /health` with CORS +
> Private-Network-Access headers. The Nano tab probes `http://127.0.0.1:8090/health`
> every 15s (loopback is exempt from mixed-content, so an `https://` tab may reach
> it). A hit → prefer local; two consecutive misses → fall back to cloud.

## Options & overrides

Local tunnel env vars:

| Env var      | Default     | Meaning                                       |
|--------------|-------------|-----------------------------------------------|
| `RELAY_PORT` | `8090`      | HTTP + `/register` WebSocket port.            |
| `RELAY_HOST` | `127.0.0.1` | Bind address. `0.0.0.0` to reach it over LAN. |

Non-default port? Tell the tab once in the browser console:

```js
localStorage.setItem("nano_local_health", "http://127.0.0.1:9000/health");
localStorage.setItem("nano_local_ws",     "ws://127.0.0.1:9000/register");
localStorage.setItem("nano_local_ext",    "http://127.0.0.1:9000");
```

Self-hosting the cloud relay? Override its host the same way:
`nano_cloud_ws` (`wss://…/register`) and `nano_cloud_ext` (`https://…`).

## Troubleshooting

- **Footer says “connecting…” forever on cloud** — the hosted relay isn't
  reachable from your network; install the local tunnel instead.
- **Safari** — connecting an `https://` page to `ws://localhost` can be blocked.
  Use Chrome/Edge/Firefox, or serve Nano over `http://localhost`.
- **“no Nano tab registered” (503)** from your SDK — the tab isn't connected;
  open Nano and confirm the footer shows *connected* before sending requests.

## The cloud relay (operators) — already deployed

The Cloudflare Worker (`wasm/relay/worker.js` + `wrangler.toml`) is **deployed and
live at `relay.vyomi.cloud`** (Workers Custom Domain → the Worker; SQLite-backed
Durable Object; `ALLOWED_ORIGIN=https://vyomi.cloud`). The Nano bundle's cloud
default already points there, so nothing to wire.

Redeploy after changes:

```bash
cd wasm/relay
npx wrangler deploy       # provisions/refreshes the custom domain + cert
```

Because it's origin-gated to `https://vyomi.cloud`, the cloud tunnel is usable once
the Nano bundle is **served from vyomi.cloud**; local development uses the local
tunnel above (the tab 403s the cloud relay from `localhost` by design). See
`wasm/relay/README.md` for the Worker internals + guardrails.
