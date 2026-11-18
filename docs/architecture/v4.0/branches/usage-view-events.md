# v4/usage-view-events

**Why:** the portal's "How we count" usage report needs to know which console views people spend time on, per cloud and per service (owner decision 2026-11-18: every view emits entry and exit timestamps so average time per view can be computed).

**Changes:** `wasm/nano-usage.js` (one shared emitter, `data-cloud` per console) included in the three v4 Nano consoles (`wasm/v4/{aws,gcp,azure}/index.html`) and the three classic consoles (`wasm/{aws,gcp,azure}-console.html`); `scripts/gen_nano_usage_routes.py` regenerates the route-pattern table inside it from `consoles/src/<cloud>/**` (`--check` detects drift); `tests/wasm/nano_usage.test.mjs` (fake-browser unit test); README privacy line.

**Contract (the portal receiver is built to exactly this):** `POST /api/usage/views` same-origin, credentials included, `{v:1, events:[{sid, cloud, view, service, enter, exit, dur}]}`, at most 50 events per request, expect 204. `sid` = 16 random hex per browser tab (sessionStorage). `view` = the console's route PATTERN (`s3/buckets/:name`), `service` = its first segment; never real names. `dur` = ACTIVE ms (hidden-tab time and time after 60 s without input excluded), capped at 30 min per event (longer visits are split); visits under 1 s are dropped.

**Privacy:** no email or id from the client (the server hashes the Nano cookie); no URL, title or query string; opt-out via `localStorage vyomi.telemetry=off`, Do Not Track, or `window.VYOMI_NO_TELEMETRY`; 404/405/501 from the endpoint (offline appliance) silently disables the emitter for the session.

**Not included:** the portal receiver and report (separate portal branch); the classic consoles are in-page state with no routes, so they report a single `classic` view per visit.

**Open:** new console routes must be added by re-running `python3 scripts/gen_nano_usage_routes.py` (unlisted routes fall back to `<service>/other`); not yet checked in a real browser against a live portal.
