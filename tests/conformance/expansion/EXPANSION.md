# Expansion agent — build a new cloud service, end to end

You run continuously in GitHub Actions. Each run you work on ONE service from
the backlog (a GitHub issue labelled `new-service`), on its own branch
`expansion/<cloud>-<key>`. You may need several runs for one service: pick up
where the last run stopped (read the issue comments and the branch). A service
is **released to users only when the service gate passes** — nothing ships
half-built.

The offline appliance is running at `$VYOMI_BASE_URL` (built from this branch),
the Nano relay at `$RELAY_HTTP`. The issue number is in `$ISSUE`; its body has
the upstream id and the checklist.

## Definition of done (the gate checks every item)

1. **Engine** `core/<cloud>_<key>_core.py` (AWS: `core/<key>_core.py`) — the
   service's state + operations, substrate-free (pure Python, no network), so the
   same code runs offline and in Nano. Implement at least the resource lifecycle
   (create / get / list / update / delete) and the operations developers use most;
   names, request/response fields and error codes must match the real API
   (botocore model / Google Discovery doc / Azure REST spec). Persist through the
   existing store seams.
2. **Native wire / API routes** — real SDKs and CLIs must work unchanged with only
   the endpoint pointed at Vyomi: AWS via `core/aws_wire_router.py` (X-Amz-Target
   / Query Action / REST paths), GCP via `providers/gcp_routes.py` REST paths,
   Azure via the ARM dispatcher (`/subscriptions/{sub}/resourceGroups/{rg}/providers/...`).
3. **Nano** — add the core to `wasm/build_cores.py` and run it; wire it into
   `wasm/nano-boot.js` / the SW route table like the existing cores. The vendored
   copy in `wasm/core/` must be byte-identical to `core/`.
4. **Console UI (offline + Nano)** — add the service to
   `providers/<cloud>_catalog.py` (rail entry, columns, create fields with
   realistic defaults, detail tabs/sub-blades, `api_paths`), then run
   `python3 wasm/build_fixtures.py` so Nano gets the same catalog. Every grid
   column must be filled for resources you create — never `-`/blank. Creating a
   resource must update the space's cost-savings metrics (add list prices to
   `core/cost_model.py`).
   **Nano and offline must be feature-identical**: the Nano catalog entry must be
   exactly what `build_fixtures.py` generates (never hand-edit
   `wasm/fixtures/*`), and both consoles must show the same tabs, columns,
   create fields and actions. The gate checks both, and the service's Nano
   changes must apply cleanly to the portal's copy (`portal/app/nano`), because
   the portal ships them in the same release.
5. **Conformance test beds**, using the **official SDKs/CLIs** with only the
   endpoint changed, each printing one `[PASS]`/`[FAIL]` line per check and
   exiting non-zero on failure:
   - Java: a class under `tests/conformance/<cloud>-sdk-java/` (AWS SDK v2 /
     google-cloud-* / azure-*), wired into that project's runner
   - Go: `tests/conformance/<cloud>-sdk-go-<key>/main.go` (aws-sdk-go-v2 /
     cloud.google.com/go / azure-sdk-for-go)
   - CLI: `tests/cli/<cloud>-<key>-cli-smoke.sh` (`aws` / `gcloud` / `az`)
   - Console, offline: `tests/conformance/ui/<cloud>-<key>.mjs` (Playwright against
     `$VYOMI_BASE_URL/console/<cloud>`): open the service, create with defaults,
     every column filled, detail tabs render, delete.
   - Console, Nano: `wasm/ui-tests/validate-<cloud>-<key>.mjs` (same flows, Nano).
6. **Hand-over to the hourly pipeline** — register every test bed above in
   `tests/conformance/hourly/suites.json`, and add the upstream id to
   `tests/conformance/upstream/tracked.json` (AWS botocore list / GCP discovery
   list / Azure specs list) so real-cloud changes to it are watched hourly.
7. **Registry + manifest** — add the service to `services/registry.json` with
   `"status": "pending-release"` (the release flips it to `released` and stamps the
   version), and write `services/manifests/<cloud>-<key>.json`:
   ```json
   {"cloud": "aws", "key": "ecs", "name": "Amazon ECS", "upstream": "ecs", "issue": 123,
    "core": "core/ecs_core.py", "operations": ["CreateCluster", "..."],
    "suites": ["offline-sdk-java-aws-ecs", "offline-sdk-go-aws-ecs", "offline-cli-aws-ecs",
               "offline-ui-aws-ecs", "nano-ui-aws-ecs"],
    "status": "building"}
   ```
   Set `"status": "ready"` only when you believe every item above passes locally.

## How to work

- Before anything else: read the issue + its comments, `git log` on the branch,
  and the manifest if it exists. Continue, don't restart.
- Some backlog services already exist in part (e.g. an SNS engine inside the
  SQS core, STS for SDK auth, CloudWatch/Logging stubs): `grep -ri <service>
  core/ providers/ server.py wasm/` first and extend what's there — never a
  second implementation of the same API.
- Run what you build: the suites via
  `python3 tests/conformance/hourly/run_suites.py --only <your suite ids>` and the
  static gate via `python3 tests/conformance/expansion/gate.py services/manifests/<cloud>-<key>.json --static`.
- Commit in small steps with messages `expansion(<cloud>/<key>): …`, then
  `git pull --rebase origin "$BRANCH" && git push origin HEAD:"$BRANCH"`.
- Before you stop, comment on the issue: what's done, what's next, any blocker.
- Never edit `.github/`, release/version files, other services' behaviour (fix a
  shared seam only if your service needs it, with tests), or anything outside
  this repo. Never weaken or delete tests. Never push to `main`.
- Time budget ~50 minutes; stop starting new work after ~42.
