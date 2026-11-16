# v4/ai-s3trigger

- Owner: AI session (round 2 gap-fix lane). Base: `v4/ai-integration` (5cb53ee00). Pushed to topic branch only.
- Purpose: reference-app component 12 gap, "S3 upload does not invoke the ingest Lambda".

## Finding
The notification engine already existed (`core/s3_object_core.py` parse/Get/Put, filters, `_deliver_notifications`; appliance path
`routes/aws_s3.py` `_s3_emit_event`, which delivers to the unified Lambda/SQS/SNS/EventBridge cores). The failure was not missing
delivery: real S3 requires the Lambda resource policy (`lambda:AddPermission`, principal `s3.amazonaws.com`) and the simulator
correctly returned `AccessDeniedException: Lambda policy does not allow this invocation source`. The reference app never granted it.
So the app was wrong against real AWS; fixed in `c12_pipeline.py` (add_permission before PutBucketNotificationConfiguration).

## Engine fidelity fixes (small, additive)
- `s3.configurationId` is now the matching rule's `Id` (was the API source name), per target (`routes/aws_s3.py`, `core/s3_object_core.py`).
- `s3.object.eTag` unquoted, as in real S3 events. `wasm/core/s3_object_core.py` regenerated with `wasm/build_cores.py`.

## OSS choices
None needed: no new backend. Reuses the existing S3, Lambda, SQS, SNS, EventBridge engines (hand-written wire adapters already in repo).
Substrates: Nano (core router, InMemoryObjectStore cross-wired to msg/lam stores) and offline appliance (routes/aws_s3.py) both covered.

## Tests
`PYTHONPATH=. python3 tests/conformance/test_s3_notifications.py` (real boto3, in-process server): Get/Put round-trip with filters,
Lambda invoke with prefix+suffix filters (non-matching keys skipped), SNS->SQS fan-out with real event JSON, ObjectRemoved to SQS,
EventBridge `Object Created`, plus a Nano-router no-HTTP check. 10/10 pass. `test_s3_core`, `test_s3_checksums_core` still pass.
Facilities e2e: component 12 PASS 7/7 (was BLOCKED 6/7); overall 9 PASS, 2 BLOCKED, 2 FAIL.

## Declared limits
- Free tier allows 1 bucket per space, so the test shares one bucket.
- Lambda invocation is async fire-and-forget (no DLQ/retry semantics). Event delivery is synchronous with the S3 request.
- Not verified inside a real browser Nano session (core path verified through the Nano router in Python only).
- Put-time validation of destination existence/permission (real S3 returns InvalidArgument) is not added.
