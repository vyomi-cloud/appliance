# v4 agentic pipeline: crawl, identify, fix, release (all three clouds)

Owner directive (2026-11-12): the git runners are agentic. They **crawl, identify, fix and release at the end of the day**, for **azure, aws and gcp**, all on GitHub Actions runners (no local runs).

## Crawl scope (owner, verbatim intent)
For all three clouds, every day:
1. **CLI <-> UI** bi-directional checks.
2. **SDK <-> UI** bi-directional checks.
3. **API <-> UI** bi-directional checks.
   (Each: create on one side, read and compare the data on the other, both directions, delete both ways.)
4. **The UI exhaustively**: all sections and subsections, every click, toggle, dropdown, form validation, and every broken UI component behaviour: `PAGE_ERROR`, 5xx, dead tab, placeholder pane, empty panel, raw errors (`[object Object]`, `undefined`, `Internal Server Error`) and wrong field-level validation wording.

### What runs for each item (wired = exists today)
| Scope | Suites / scripts | Registered ids (stable) |
|---|---|---|
| CLI<->UI | `tests/release/cli_crosscheck.py` (real aws/gcloud/az CLIs vs the console's calls, both ways) | `bidi-<cloud>-cli-ui` |
| SDK<->UI | `roundtrip/ui-sdk-roundtrip.mjs`, `nightly/aws-v4-roundtrip.mjs`, `gcp-v4-roundtrip.mjs`, `gcp-roundtrip.mjs`, `gcp-compute-vertex-bidi.mjs`, `wasm/ui-tests/validate-azure-v4-bidirectional.mjs` | `bidi-<cloud>-sdk-ui` |
| API<->UI | the same round-trip suites' API halves | `bidi-<cloud>-api-ui` |
| UI exhaustive | `hourly/ui_crawler.mjs` (`nano-ui-crawl`; findings PAGE_ERROR, HTTP_5XX, HTTP_404, PLACEHOLDER_PANE, DEAD_TAB, raw-error text, empty panels) | `crawl-<cloud>-ui` |
| Form validation | `nightly/gcp-validation.mjs` (+ per-cloud siblings as they are built) | `validation-<cloud>-ui` |

The gap map (which of these still have no suite) is kept by a separate agent, which registers missing ones as `pending` suites under the stable ids above (reported each run, never counted as failures). `bidi_report.py` selects by those id patterns, so a suite starts being crawled the day it is registered; nothing in the workflows changes.

## The loop
```
hourly   v4-known-issues-hourly.yml  fix ONE open row per cloud (headless agent), re-test, gate, fast-forward v4-on-main
daily    v4-bidi-daily.yml (03:30 IST) run the crawl scope above, write findings to the register (AUTO-<cloud>-... rows; passing again = resolved)
EOD      v4-eod-release.yml  (23:00 IST) re-run the crawl scope, gate, and release the next patch when everything is green
on release v4-release-checklist.yml     deterministic checklist per cloud
```
One register ties it together: `docs/architecture/v4.0/V4.0.0-KNOWN-ISSUES.md`, edited only through `tests/conformance/nightly/lib/known_issues.py`. Row prefixes: `AZ-`/`AUTO-azure-`, `AWS-`/`AUTO-aws-`, `GCP-`/`GW-`/`AUTO-gcp-`.

### Scripts
- `tests/conformance/nightly/bidi_report.py`: `select` (suite ids for `run_suites.py --only`), `report` (log checks + `--cli-results` CLI cross-check + crawler JSON -> rows, self-healing).
- `tests/conformance/nightly/crawl_report.py`: crawler findings -> `AUTO-<cloud>-crawl-<service>-<type>` (S2 for broken features, S3 for fidelity).
- `tests/release/v4_checklist.py`: the per-cloud release gate. `tests/conformance/nightly/gate.py`: nothing green may go red.
- `tests/release/v4_eod_plan.py`: the EOD decision (pure, unit-tested): `skip | blocked | dry-run | release`, next patch version, known-issues delta.

## The end-of-day workflow (`v4-eod-release.yml`)
1. **guard**: honours `V4_RELEASE_PAUSE`; counts commits since the last `v4.*` tag; refuses while the hourly fixer or the daily run is in progress.
2. **crawl** (matrix azure, aws, gcp): fresh stack from `v4-on-main`; runs the scope above (offline + Nano) and `cli_crosscheck.py`; records findings in the register (pushed to `v4-on-main`, rebase+retry); runs the release checklist for that cloud.
3. **decide**: `v4_eod_plan.py`. Blocks on any red/missing cloud, any open **S1** row, or a tag clash. Skips if `VERSION` is not 4.x (v4.0.0 not cut yet), nothing changed since the last tag, or something is mid-flight.
4. **release**: bump `VERSION`, `release_notes.py` (CHANGELOG + README), commit to `v4-on-main`, tag `v<next>` on that commit, create `release/v<next>`. **Never `main`.** The tag triggers `release.yml` and `docker-publish.yml` (a real image publish). Portal Nano sync only when the dispatch input `sync_portal` is true.
5. **summary**.

### Safety, arming and pausing
- Releases happen only when repository variable **`V4_AUTO_RELEASE=true`**, the run is not a dry run (dispatch `dry_run` defaults to **true**; the schedule is never a dry run), and **`V4_RELEASE_PAUSE`** is not `true`.
- Arm: `gh variable set V4_AUTO_RELEASE --body true`. Disarm: set it to `false`. Stop everything: `gh variable set V4_RELEASE_PAUSE --body true` (also pauses the EOD crawl).
- Secrets: `CONFORMANCE_BOT_TOKEN` (push + tag), `CLAUDE_CODE_OAUTH_TOKEN` (subscription token only, never an API key), `VYOMI_TEST_LICENSE_JWT` (optional).

## Limits and decisions the owner must take
- **Cron fires only from the default branch.** Until the v4 workflows are on `main`, run them by hand (Actions > Run workflow). The workflow files live in `ci/v4/` on trunk because the integrator token cannot push under `.github/workflows`; the owner installs them.
- **`service-gate.yml` auto-merge**: on `main` an expansion PR that passes the gate triggers `conformance-release.yml`, which cuts a v3-style patch. Decide before go-live whether it stays, so two release paths do not race for the same version.
- **Agent files**: `KNOWN-ISSUES-AGENT.md` (the fixer). Per-cloud nightly fixers: `AZURE-AGENT.md`, `AWS-AGENT.md`, `GCP-AGENT.md` (same folder).
- The Mesh (live Codespace, real Docker compute, tunnel) job is only in the daily run and needs `NIGHTLY_CODESPACES_PAT` + variable `NIGHTLY_MESH_SIM_URL`; otherwise it reports NOT RUN.
- Never verified on a real runner yet: every workflow here was linted (`actionlint`) and its scripts unit-tested, not run.
