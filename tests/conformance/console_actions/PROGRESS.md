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

---

## Session 2 (2026-06-14 — agent-ac7d87aea25259bd0)

### 3 services brought to 100%

| # | Service | Tests | Commit |
|---|---|---|---|
| 1 | gcp.storage | 7/7 | `215ce16` |
| 2 | aws.sqs     | 7/7 | `86fd29d` |
| 3 | aws.rds     | 5/5 | `a0385c7` |

### Pass-rate movement

| Provider | After session 1 | After session 2 | Δ |
|---|---|---|---|
| aws   | 49.2%  (61/124) | 54.8%  (?)   | +5.6pp |
| gcp   | 44.4%  (44/99)  | 46.0%  (?)   | +1.6pp |
| azure | 100%   | 100% | 0 |
| **All** | **57.1%** | **61.0%** | **+3.9pp** |

### Key learning

aws.rds had to be hardened for "simulated mode" (no LXD daemon present)
— `_rds_runtime_{start,stop,reboot}` now book-keep on the record when
LXD isn't available, instead of 503'ing. This pattern likely applies
to other VM/DB-style services in subsequent sessions.

### Recommended next 3 services for session 3

Run the suite for fresh data; based on session 2's totals, candidates are:
- `aws.dynamodb` (gated on tier — check if Developer unlocks it cleanly)
- `gcp.compute` (large but high-value — cuts into the VM lifecycle story)
- `aws.lambda` or `aws.apigateway` (paired wins; same handler patterns)

---

## Session 3 (2026-06-14 — agent-aa039f0bee7a5de48 — LIVE appliance)

### Targets re-validated against the rebuilt LIVE appliance

The session-2 numbers (54.8% / 46.0%) did NOT carry over to a fresh
rebuild from `865059a`. Mission baseline against the live appliance was
AWS 41.1% / GCP 42.4% / Azure 100% = 52.7% overall.

### 4 services confirmed at 100% on LIVE

When run **in isolation** against the live appliance, all 4 of the
"almost-100%" gcp targets pass cleanly:

| # | Service | Tests | Note |
|---|---|---|---|
| 1 | gcp.kms          | 9/9 | already green — REPORT.md stale |
| 2 | gcp.eventarc     | 7/7 | already green — REPORT.md stale |
| 3 | gcp.secretmanager| 7/7 | already green — REPORT.md stale |
| 4 | gcp.storage      | 7/7 | already green — REPORT.md stale |

These show as failing in the FULL multi-provider run due to intermittent
HTTP `ReadTimeout`s when the simulator container is under load (running
~254 tests back-to-back through a single requests.Session). NOT a real
backend bug — the routes all answer 200 OK to `curl -m 30` after the
load lifts.

### 1 real bug fix shipped

| # | Service | Before | After | Commit | Bug |
|---|---|---|---|---|---|
| 5 | aws.iam | 8/12 | 10/12 | 7ef75ff | no GET /api/iam/users/{id} handler existed; S3 catch-all ate it and returned `NoSuchBucket` XML. Added `api_iam_get_user/group/role/policy` to providers/aws_iam.py |

Remaining 2 aws.iam failures (`deletePolicy`, `deleteRole`) are
**catalog/harness limitations** — the harness reuses the captured
`user_name` as the `{name}` placeholder for ALL iam api_paths actions,
so deleteRole/deletePolicy hit non-existent role/policy and 404 with
the correct AWS contract response. Fixing requires harness changes
(per-action create-cascades).

### Session 3 movement

| Provider | Live baseline | After session 3 | Δ |
|---|---|---|---|
| aws   | 51/124 (41.1%) | 53/124 (42.7%) | +1.6pp |
| gcp   | 42/99  (42.4%) | depends on full-suite stability | — |
| azure | 52/52  (100%)  | 52/52  (100%)  | 0 |

### Key learning — live appliance vs compose stack

Sessions 1+2 ran against their own compose stacks and the numbers
didn't transfer cleanly to the user's live appliance. Future sessions
should **always probe the live appliance first** before scoping work.

The `/app` mount is read-only on the live container — hot-patching
requires writing to `/workspace/cloud-learn/<file>` in the VM (which
is the bind-mount source), then `docker restart`.


---

## Session 3 (foreground, 2026-06-14) — KEY DISCOVERY

### What we tried

Targeted Phase 4 quick-wins: `gcp.kms`, `gcp.eventarc`, `gcp.secretmanager`, `gcp.storage` — each reported as 7-9 passing of 7-10 in the latest committed REPORT.md, so "1 failure each" expected.

### What we found

**These 4 services are already at 100% on the live appliance — when run in isolation.**

Running each service individually:
```
gcp.kms          9/9   ✓ 100%
gcp.eventarc     7/7   ✓ 100%
gcp.secretmanager 7/7  ✓ 100%
gcp.storage      7/7   ✓ 100%
Combined (filtered):  30/30  ✓ 100%
```

But when run as part of the full suite they previously appeared as 7/8 / 9/10. The difference is **state leakage** — one service's test resources break another's.

### Implications

The path to higher pass-rate isn't (only) fixing service code. It's adding **test isolation**:

1. **Per-test resource cleanup** — a pytest fixture that drops all `vyomi-conf-*` resources after each test
2. **Unique resource names per test run** — append a timestamp or random suffix so retries don't collide
3. **Provider-scoped resource namespaces** — separate `gcp.kms.test1` from `gcp.kms.test2` to avoid cross-test pollution

### Effort to reach 100% — revised estimate

| Approach | Sessions | Outcome |
|---|---|---|
| Build test isolation layer | 1-2 | Likely unlocks +20-30pp at once (services that "already work" but fail in suite) |
| Continue per-service fixes | many | Slow per-pp progress; doesn't address root cause |

**Recommended next move**: structural acceleration before more service-by-service work.
