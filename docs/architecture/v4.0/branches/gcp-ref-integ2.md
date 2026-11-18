# v4/gcp-ref-integ2

Integration of the GCP 13-component reference architecture (base `v4-on-main`, trunk merged in 0d75471b5).

## Changes
- Merges lane branches: `gcp-ref-app` (cloud-neutral harness + GCP app), `gcp-ref-corefix`, `gcp-ref-sandbox`, `gcp-ref-realbackend`, `gcp-ref-identity`, `gcp-ref-glue`, `gcp-ref-vertexfix`. Each has its own branch doc.
- `FACILITIES_READ_TIMEOUT` env override for the reference app SDK read timeout (default 60 s).
- Removed test-output dirs (`lambda_functions/{dbl,inc,mkkey,upper}`, `engsrc-*`) that lanes had committed.

## Design decisions
- Real Pub/Sub + Firestore emulators are an opt-in data plane (`VYOMI_GCP_REAL_BACKENDS=1`, offline/Mesh only). Default behaviour and Nano are unchanged.
- Own code added where no open-source option fit: Identity Platform core, gRPC-to-REST adapter for Logging/Monitoring (`core/gcp_grpc_front.py`).

## Verification (macOS arm64, in-process simulator, no tier gating)
- GCP app `run_e2e.py --cloud gcp --start-emulators` with Qwen3-4B (CPU, Docker): 13 PASS / 0 BLOCKED / 0 FAIL, run twice (before and after merging trunk).
- AWS app `run_e2e.py`: 13/13 with `FACILITIES_READ_TIMEOUT=400` (60 s default times out on the CPU model).
- Lane regression tests and `test_relay_cores_parity` pass.

## Open issues
- Not run on a Codespace / real Mesh stack. Model is small and CPU-served.
- Real-backend mode: Pub/Sub schemas/IAM/console peek and non-default Firestore databases do not apply to emulator data; Firestore triggers do not fire for direct gRPC writes.
- Firestore is Max-tier on a licensed appliance (harness skips tier gating).
