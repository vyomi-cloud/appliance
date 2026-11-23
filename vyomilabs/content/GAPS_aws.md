# AWS labs: simulator gaps

None found. Every block in chapters 3, 12, 6, 11, 9, 4, 5, 1, 2, 8 and 13 ran and passed against the simulator.

Verification note: blocks marked `needs_runtime` execute real Lambda handlers (boto3 inside the function): the knowledge-search and
ingest tools, the S3 event, the approval workflow (Step Functions invokes Lambdas), the API Gateway proxy call, and the agent calls that depend on
them. The plain in-process simulator used by `labrun` runs Lambda in a restricted sandbox with no imports, so it reports these BLOCKED.
They were verified PASS against an in-process simulator with the appliance's real Lambda runner installed
(`routes/aws_lambda_unified.run_function`) via `labrun --endpoint`.
