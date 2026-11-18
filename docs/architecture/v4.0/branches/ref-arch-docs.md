# v4/ref-arch-docs

Docs, probe scripts and result files for the GCP/Azure reference architecture work, combined from `ref-arch-gcp-azure`, `ref-arch-probe-gcp`, `ref-arch-probe-azure` and `gcp-ref-app` (results + status doc). Base `v4-on-main` 999940d18. No product code changes.

## Changes
- `docs/architecture/v4.0/REFERENCE-ARCH-GCP-AZURE.md` (mapping, decisions, probe results, scope), `REF-ARCH-PROBE-GCP.md`, `REF-ARCH-PROBE-AZURE.md`.
- `examples/ref-arch-probe/{gcp,azure}/`: per-component probe scripts and `results/*.json` from the probe runs.
- GCP app results (`results/gcp-e2e-result*.json`, `gcp-report*.html`) and the updated `gcp-ref-app.md` status doc.
- Dropped the probe lane's scratch helpers (`run.sh`, `run1.sh`, `t.py`: local paths).

## Design decisions
- Probe results are point-in-time (v4.0.4 / pre-fix). The GCP gaps they list were fixed by #659; the Azure gaps are still open (12-21 d estimate).

## Open issues
- The mapping doc's estimates for GCP are superseded by the 13/13 result; the Azure half is still a proposal.
