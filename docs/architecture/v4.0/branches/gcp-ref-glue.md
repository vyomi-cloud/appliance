# v4/gcp-ref-glue: cross-lane integration fixes for the GCP reference app

Round 2, lane 7. Base: `origin/v4/gcp-ref-integ` 77b2a7fa6 (the five round-1 lanes merged).

## Changes
- (5) Function stdout/stderr -> Cloud Logging `run.googleapis.com%2Fstdout|stderr` on `cloud_run_revision` (service/revision labels) from the subprocess runtime
  (`core/gcp_function_runtime.py` LOG_SINK, set by the wire router). `functions-framework` in requirements.txt is always satisfied (the harness is the framework).
  `GOOGLE_FUNCTION_SIGNATURE_TYPE=cloudevent` build env selects the CloudEvent signature (as the buildpack does).
- (1) GCS bucket notifications publish through `gcp_pubsub_core.dispatch` (the real-backend seam), not `_publish`.

## Design decisions
- No new backend; all fixes sit on existing seams.

## Open issues
- (filled in as fixes land)
