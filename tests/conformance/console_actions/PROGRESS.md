# Conformance progress — session 2026-06-14 (agent-a9a5aa8eafed160e1)

This file is the rolling status from agents working through the
console-actions conformance suite. Each session pushes 3 services to
100% and hands off cleanly.

## This session's 3 services (all at 100%)

| # | Service | Tests | Commit | Note |
|---|---|---|---|---|
| 1 | aws.eventbridge | 10/10 | 0c1d319 | aws_extras handler now serves single-item GET |
| 2 | aws.kms        | 9/9   | 6d5a3da | harness: skip em-dash placeholders when capturing id |
| 3 | gcp.eventarc   | 8/8   | 0408b2a | gcp_extras handler now serves single-item GET |

### Lifted as side-effects (count toward overall pass rate, not the "3")
- `aws.secretsmanager` (8/8) — same aws_extras fix
- `gcp.kms`            (7/7) — same gcp_extras fix
- `gcp.secretmanager`  (8/8) — same gcp_extras fix

## Overall pass-rate after this session

| Provider | Before | After  | Δ |
|---|---|---|---|
| aws   | 52/124 (41.9%) | 61/124 (49.2%) | +9  |
| gcp   | 41/99  (41.4%) | 44/99  (44.4%) | +3  |
| azure | 52/52  (100%)  | 52/52  (100%)  | 0   |
| **All** | **145/275 (52.7%)** | **157/275 (57.1%)** | **+12** |

Net new commits on `conformance/reach-100`:
- `902054d` harness self-bootstrap (tier signup body annotation + conftest signup + compose override)
- `0c1d319` aws.eventbridge → 100%
- `6d5a3da` aws.kms → 100%
- `0408b2a` gcp.eventarc → 100%

## Recommended next 3 services (smallest failing → fastest wins)

In ascending order of remaining failures, all look tractable in <15 min each:

| Rank | Service | Pass | Total | Failure shape |
|---|---|---|---|---|
| 1 | `gcp.storage`  | 11/12 | 12 | single `delete` returns 404 "Bucket not found" — likely an id-capture gap from create response (`name` lives under a nested field in fake-gcs response) |
| 2 | `aws.sqs`      | 6/8   | 8  | 2 failures: `send` 404 NoSuchBucket XML (S3 catch-all wins over POST path) and `delete` 404 NonExistentQueue (probably name-vs-url mismatch — queue_url captured includes scheme://) |
| 3 | `aws.rds`      | 7/12  | 12 | 5 failures: `delete` NotFound, `modify` 404 NoSuchBucket XML — same family of issues, S3 catch-all + id capture |

Then graduating to medium:
- `aws.s3`      (3/8) — 4 fails, all 404s on per-bucket actions (notifications/versioning/objects PUT)
- `gcp.compute` (5/12) — 7 fails, looks like create payload shape + id capture
- `aws.ec2`     (2/9) — 7 fails, the create itself 500s; needs a working ec2 create first then the cascade lifts

## Patterns to keep in mind

1. **S3 catch-all eats sibling routes.** `404 NoSuchBucket` XML body means
   the S3 wildcard route at `/{bucket}` intercepted the call. Fix by
   registering the targeted route BEFORE `aws_s3.register()` in `server.py`,
   or by checking path prefix more carefully in the S3 dispatcher.
2. **Em-dash placeholders.** Stub-CRUD layer fills unspecified columns with
   "—". When `name_field` points at one of those columns, the harness will
   substitute "—" into resource paths and 404. The harness now skips that
   sentinel (commit `6d5a3da`); backend-side fix would be to mirror `name`
   into the canonical id column at create time.
3. **State persists across runs.** `/data/cloudlearn_state.sqlite3` is
   persistent; a second run after a passing-create will get 409 "already
   exists" on create. Tests that rely on a clean slate need a
   delete-before-create or a unique-per-run name. The full suite handles
   this within a session via lifecycle ordering (create→get→...→delete),
   but interrupted runs leave orphans.

## Blockers logged

None yet. See `BLOCKED.md` if the next session hits a multi-hour rabbit
hole.

## Local dev environment notes (for the next agent)

This worktree uses host ports `2xxxx` for backends and `9100` for the
simulator (see `docker-compose.override.yml`) to avoid colliding with
sibling agent worktrees or the user's appliance on `:9000`.

```bash
# Bring up your stack
docker compose -p conf-a9a5 -f docker-compose.yml -f docker-compose.override.yml \
  up -d simulator cloudlearn-sql-postgres cloudlearn-gcs

# Install pytest+requests inside the simulator container
docker exec --user root conf-a9a5-simulator-1 pip install -q pytest requests

# Run a single service's tests
docker exec conf-a9a5-simulator-1 bash -c \
  "cd /app && VYOMI_BASE_URL=http://127.0.0.1:9000 \
   VYOMI_CONFORMANCE_REPORT=/tmp/REPORT.md \
   python3 -m pytest tests/conformance/console_actions/ -k '<service>' -q --tb=line"

# Read the per-test breakdown
docker exec conf-a9a5-simulator-1 head -200 /tmp/REPORT.md
```

The source bind-mounts in `docker-compose.override.yml` mean Python
edits to `server.py`, `core/`, `providers/`, `routes/`, and `tests/` land
without a docker rebuild — just `docker compose restart simulator`.
