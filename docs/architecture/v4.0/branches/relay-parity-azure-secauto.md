# v4/relay-parity-azure-secauto

Adds `azure_security_automations_core.py` to the CORES list in `wasm/relay/nano-endpoint.html`.

## Changes
- `wasm/relay/nano-endpoint.html`: one list entry. `relay-shared-worker.js` (since the v4.0.6 release-checks commit 1dcbc19bf) and `wasm/nano-boot.js` already list it; the endpoint page did not, so a request through the Nano relay endpoint that lazily imports it (Azure security automations) would fail, the same class of bug as the 14 missing cores in v4.0.3.

## Design decisions
- Parity is enforced by `tests/conformance/test_relay_cores_parity.py`, which fails on trunk without this entry.

## Open issues
- None.
