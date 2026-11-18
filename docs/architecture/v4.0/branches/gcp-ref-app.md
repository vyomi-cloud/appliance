# v4/gcp-ref-app: GCP implementation of the 13-component reference application

Lane 1 of the GCP 13/13 reference-architecture build. Base: `origin/v4-on-main` a54fc442f. Work in progress; sections are filled as component groups land.

## Changes
- Harness made cloud-neutral without changing the AWS run (`examples/enterprise-facilities-agent`): `facilities/runtime.py` imports boto3 lazily and
  `Ctx.blocked_lane()` / `Ctx.COMPONENTS` are overridable; `facilities/agents.py` routes model, tool, approval and statistics calls through an IO adapter
  (`AwsIO` default, `facilities/gcp/io.py` for GCP); `run_e2e.py --cloud gcp`; `report.py` shows the cloud. AWS e2e step statuses are identical before and
  after (75 steps; 11 PASS, 2 BLOCKED on "local model", as before).

## Design decisions
- (filled in below as components land)

## Open issues
- (filled in below)
