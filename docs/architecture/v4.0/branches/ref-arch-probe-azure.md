# Branch: v4/ref-arch-probe-azure

## Title
Step 1 (PROBE) of the Azure half of REFERENCE-ARCH-GCP-AZURE.md: real Azure SDK calls for the 13 reference-app components against the simulator.

## Changes
- `examples/ref-arch-probe/azure/`: `_common.py` (in-process appliance harness), `probe_01..13_*.py`, `run_probe.py`, `results/azure-probe.json`.
- `docs/architecture/v4.0/REF-ARCH-PROBE-AZURE.md`: per-component PASS/BLOCKED/FAIL, exact failing call, error text, cause (a/b/c/d), day estimates.
- No simulator code changed. Nothing mocked.

## Design decisions
- The probes start the real appliance app (`server.py`) in-process, not only `core.wire_ingress`, because Functions invoke, APIM gateway, the `/azure-data/*` routes and the Service Bus AMQP listener are mounted by `server.py`. Offline behaviour differs from the shared router (e.g. `/openai/*` GET), and the offline appliance is what ships.
- `CLOUDLEARN_TIER_ENFORCE=0` so tier locks (Cosmos is locked on Free) do not hide capability results.
- No model is running: model-dependent steps are BLOCKED(no model) but still exercise the API surface.
- Service Bus entities are seeded through the runtime store (harness shortcut), because no native control path reaches the AMQP store; this is reported as a gap.
- SDKs that refuse non-TLS bearer auth are BLOCKED(d), not FAIL.

## Open issues
- Steps run only against the appliance server; the shared wire router (Nano) was not run as a second pass.
- Search semantic ranker, Event Grid delivery and AI Search indexer were probed only as far as the simulator exposes them.
