# usage-install-id (`v4/usage-install-id`)

The Nano view emitter (`wasm/nano-usage.js`) now adds an optional `iid` to each batch: the same device fingerprint the Nano install ping sends as `install_id` (`nano-fp-` + 24 hex), computed the same way and cached in localStorage `vyomi.nano.iid`. The portal hashes it (salted, own namespace) and only counts distinct browsers per day for the "Daily Active Simulators" tile. Older builds send no `iid`; the portal accepts that. Cache buster `?v=<md5>` added to the five script tags.

Tests: `node tests/wasm/nano_usage.test.mjs` (iid absent/cached/malformed/computed/opt-out). Node only, not run in a browser.

Open issues: `wasm/v4/aws/index.html` has no nano-usage script tag today (AWS v4 emits nothing); the fingerprint is per device, so Chrome and Safari on one machine are one "simulator".
