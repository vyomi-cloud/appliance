# v4/ref-arch-probe-gcp

Owner: appliance session - Started: 2026-11-18 - Base: origin/v4/ref-arch-gcp-azure (daf4ccc81) - Status: probe complete, report written, nothing in the simulator changed

## Purpose
Step 1 (the probe) of the GCP half of REFERENCE-ARCH-GCP-AZURE.md: run the real Google SDK calls the 13-component reference app would make against the simulator and record PASS / BLOCKED / FAIL with evidence.

## What is in it
- `examples/ref-arch-probe/gcp/probe_NN_<name>.py`: one plain-SDK probe per component (05b = the real Pub/Sub + Firestore emulator question), `_common.py`, `run_probe.py`, `results/gcp-probe.json`.
- `docs/architecture/v4.0/REF-ARCH-PROBE-GCP.md`: per-component results, cause class, gap estimates, updated GCP total.
- No simulator code changed.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| In-process `start_in_process()` front door (wire router only), fresh state per probe | Booting `server:app` for every probe | Same harness as the AWS app; a one-off run of `server:app` showed the tier gate (Firestore needs Max) and the same function sandbox, so no extra signal |
| REST transport clients where the SDK offers one; raw REST where it does not; every SDK-without-REST case reported as its own step | Hiding gRPC-only SDKs behind raw REST | The pass bar is unmodified vendor SDKs; a raw-REST pass is labelled as such |
| Model-dependent steps reported BLOCKED(no model), never PASS | Faking a model response | No local LLM in the sandbox |
| Real emulator containers started from the image already in the local Docker store, removed by exact name | Pulling images / installing anything | Disk guard and "do not install heavy stuff" |

## Open issues
- [ ] No model run: generateContent, memories:generate, Agent Engine :query, grounded answer are unproven end to end
- [ ] Cloud Run service hosting of the app (alternative to Agent Engine) not probed
- [ ] KMS data-access audit entries not verified (needs an auditConfig the probe did not enable)
