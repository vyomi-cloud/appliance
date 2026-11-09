# v4/gap-c-gcp

Class C (honest-forever) GCP gaps. Base: `origin/v4-on-main`.

## Decisions
- Real local engine where one exists; "Dev Simplified" only where a real local engine is simplified versus the cloud; "Not in scope" (registry `not_simulated` + `outOfScope: true`) where the real thing exists only inside Google.
- Rollouts: `core/gcp_computesim_core.py` rolls an instance template over the Compute store's managed instance groups via the MIG PROACTIVE rolling replace, per-wave RUNNING health check, rollback.
- Preview features: config record only (`config_only`); nothing in Vyomi is gated by it.
- Object enrichments: `core/gcp_enrich_core.py`, local extraction on upload into `vyomi-enrich-*` object metadata (not Document AI). OCR needs tesseract on the host.
- Run/Functions GPU: config validated and stored; annotation `vyomi.dev/gpu-status` states "No GPU on this host" or that an NVIDIA runtime was detected. No passthrough, CUDA never faked.
- Bare Metal Solution (7 pages) and HSM/External protection levels: Not in scope.

## Open issues
- Passthrough of a host GPU to Cloud Run revisions is not built (Cloud Run revisions are not executed as containers by the core).
- SoftHSM-backed keys were deliberately not built (owner: HSM is not in scope).
- Rollouts: advance is manual; no time/metric validation.
