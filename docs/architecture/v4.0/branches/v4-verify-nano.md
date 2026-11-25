# v4/verify-nano

Faithful IAM verified in the real Nano build (Chrome, service worker, in-browser engine, Pyodide) by driving the built v4 consoles (`/v4/<cloud>/`).

Suite: `wasm/ui-tests/iam/iam-console-e2e.mjs` (`PHASE=aws,gcp,azure`). Credential-less console traffic is never gated by design (same as Mesh), so denied-call checks sign requests like an SDK/CLI from the same page after the console flips enforcement.

Product bugs found and fixed:
- AWS visual editor / ARN pickers prefilled `${Account}` with 000000000000; the simulated account is 123456789012, so generated resource ARNs never matched.
- GCP typed service-account emails were normalised to `user:`; Policy Troubleshooter / Effective access did the same, and the Troubleshooter ignored conditions and resources (testIamPermissions on the project). It now uses the engine evaluate.
- Azure picker blades (Select / Add / Review + assign) sat under the fixed Vyomi dock and Nano footer: unclickable.
- Azure `/api/iam/azure/evaluate` ignored the plane, so a data action (ABAC case) always implicit-denied. `_rbac` now tries both planes when the caller does not state one; the API forwards `data` when given.
- Nano adapter (`iam_state_nano.azure_state`) treated the console's `kind=deny` roleAssignments records as allow assignments, so deny assignments never blocked requests (Mesh adapter already handled it).
