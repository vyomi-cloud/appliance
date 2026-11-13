# v4/mcp-v4-knowledge

Owner: overnight Claude session for Rohith - Started: 2026-11-14 - Base: origin/v4-on-main (41161ac3e) - Status: in progress

## Purpose
Make `vyomi mcp` (the Go MCP server in `cmd/vyomi`) work for v4, where the simulator lives in a Nano browser tab, a local mesh
or a Codespace mesh, not only a Docker appliance on `:9000`. This branch carries these steps of
`vyomi-mcp-v4-implementation-plan.md` (owner's specs folder, outside the repo):
- D0 discovery, items 1 and 3: Nano SDK wiring through the local relay, and `vyomi-tunnel list --json`.
- K1–K2: knowledge v2, from `core/capabilities/**` and `wasm/docs/**`.
- H1–H3: home detection and home-aware tools.

Out of scope for this branch: distribution (T1/T2, `vyomi-tunnel mcp`), the plugin manifest, and release work.

## Architecture
- `docs/architecture/v4.0/MCP-V4-DISCOVERY.md`: D0 evidence (Nano SDK wiring through the local relay, `vyomi-tunnel list --json`).
- **K1 — knowledge v2 generator** (`scripts/gen_mcp_matrix.py`, `scripts/mcp_wiring.json`). It writes three outputs into `cmd/vyomi/`:
  - `mcp_matrix.json` (schema 2): the v3 fields, plus `homes.{offline,nano,mesh}` wiring, and per registry service
    `capability_service`, `levels{nano,offline}` (worst), `level_counts`, `tier`/`mesh` (anchor capability), `mesh_only`, `pro_capabilities`.
    `v4_services` lists capability files the v3 registry lacks (bedrock, eks, aks, ...).
  - `mcp_caps.json.gz`: every capability of `core/capabilities/{aws,gcp,azure}/*.json` (`id, title, level, tier, mesh, limitations, tests`),
    grouped by cloud and file stem.
  - `mcp_docs.json.gz`: per service of `wasm/docs/**`, the wired operations with a short description, the console's own
    CLI/Python/JavaScript/curl snippets aimed at `{sim}`, the `pickOps` defaults, the per-feature level and Azure data-plane rows.
    Snippets are rendered by running `wasm/nano-docs.js` under node (no second copy of the templates).
  - `mcp_wiring.json` now holds `homes` (the old `clouds` block moved to `homes.offline`; `homes.nano` from D0, each value
    with `verified`; `unavailable` for settings an SDK cannot use through the tunnel; `homes.mesh = same_as offline`) and
    `capability_aliases` (registry key -> capability stem, e.g. `logs` -> `cloudwatch`, `elbv2` -> `ec2#ec2.load-`).
- **K2 — loader + two tools** (`cmd/vyomi/mcp_caps.go`, `mcp_homes.go`, `mcp_knowledge.go`, `mcp_tools.go`, `mcp.go`).
  - `mcp_caps.json.gz` / `mcp_docs.json.gz` are `//go:embed`ded and decompressed lazily (`sync.Once`) on first use; `initialize` does not touch them.
  - `vyomi_capability {query, cloud?}`: ranks exact id > id prefix (with or without the `azure.`/`gcp.` prefix) > exact title > all title/id words
    (prefix-tolerant), then full before limited; at most 20, with `total_matches`/`truncated`, `needs` for mesh-only / Pro, and a level legend.
  - `vyomi_snippet {cloud, service, op?, lang, home}`: resolves the service by docs stem, registry id, title or unique substring and the op by
    name/boto3/CLI alias; the default op is the registry's first known action (CreateBucket...), then the console's `pickOps`. Only `{sim}` is substituted.
  - `vyomi_services` returns `v4_services` and the roll-ups, with legends. `mcpInstructions` covers homes, the new tools and "never tell a Nano
    user to run `vyomi up`"; the real-cloud steering sentence is unchanged.
  - `mcp_homes.go` (started in K2, completed in H1): home ids, explicit `home` resolution (`nano` -> local tunnel `127.0.0.1:$RELAY_PORT`, or the
    cloud relay when `VYOMI_ENDPOINT` is non-local, keeping its `/<session>` path; `mesh` -> `VYOMI_MESH_URL`; `offline` -> the legacy target).
    `mcpTarget` gained `Path` and a default-port form for the relay URL.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| D0 static server on `:8017` instead of `:8000` | stopping the process on `:8000` | `:8000` belonged to an unrelated local app and `:8001` to Docker; the harness takes `TAB_URL` |
| D0 item 3 run against a local fake portal with dummy env keys, `HOME`/`VYOMI_HOME` in a temp dir | reading the real key; calling vyomi.cloud | the session rules forbid both; this still exercises every `list` branch except a live Codespace |
| Regenerated `cmd/vyomi/mcp_matrix.json` in its own commit first | leaving `--check` red until K1 | the base was red only because `VERSION` moved to 4.0.0; every later commit must be green |
| K1 snippets: run `wasm/nano-docs.js` (the console's templates) under node from the generator | port the templates to Python, or to Go at runtime | one source of truth: the MCP hands out exactly what the console's SDK & CLI tab shows; a port would drift. Cost: the generator needs `node` |
| K1 `--check` compares the *decompressed* JSON of the `.gz` outputs; writes are deterministic (sorted keys, `mtime=0`, no name, level 9) | byte-compare the `.gz` files | deflate output can differ across zlib builds (macOS vs Ubuntu, zlib-ng), which would make CI flaky for no content change. L1-01 (byte-identical twice on one machine) still holds |
| K1 service-level `tier`/`mesh` = the service's anchor (first) capability; extras listed in `mesh_only` / `pro_capabilities` | any capability mesh-only => service mesh-only; all => service | "any" would mark all of Lambda and Bedrock mesh-only (one extra each); "all" would miss AKS/GKE, whose clusters (the anchor) need a mesh |
| K2 the MCP corrects AWS CLI command words in snippets (`s3`->`s3api`, `secrets-manager`->`secretsmanager`, `cloudwatch-logs`->`logs`, `sfn`->`stepfunctions`, ...) in the generator | hand out the console's snippet verbatim | `wasm/docs` takes the CLI word from botocore's serviceId, so ~15 AWS APIs give commands that do not exist; an agent would run them. Root fix belongs in `scripts/gen_nano_docs.py:255` (trunk) |
| K1 per-service `levels` = worst level (as the plan says), plus `level_counts` | worst only | S3 is 11 full / 36 limited: "limited" alone hides that most of it works |

### Decisions taken unattended
(Defaults taken without the owner because the session ran overnight; each is reversible.)

## Open issues
- [ ] D0 item 2 (Codespace mesh API target) and item 4 (space semantics on a mesh) need a Pro/Max key and a Mesh Codespace (owner: Rohith)
- [ ] `vyomi-tunnel list --json` envelope is `{targets, notes}` with no `schema`; the spec says `{rows, notes}` + `schema: 1` (T1, owner: tunnel session)
- [ ] Nano `/health` lists RDS proxies under `vms[]`, never `dbs[]` (owner: tunnel session)
- [ ] Nano RDS Data API loses state between statements; `e2e-relay.mjs` step 7 fails on the trunk (owner: Nano core)
- [ ] Console bug: `wasm/docs` AWS `cli` names come from botocore serviceId (`scripts/gen_nano_docs.py:255`), so the Nano console's SDK & CLI tab shows `aws s3 put-object`, `aws secrets-manager ...`, `aws cloudwatch-logs ...`. The MCP corrects them (K2); fix the generator on the trunk and drop `_aws_cli_fix` (owner: Nano docs)
- [ ] `gen_mcp_matrix.py` now needs `node` (snippets). `release.yml:156` and `conformance-release.yml:132` run it on GitHub runners (node preinstalled); `ci.yml:35` runs `--check` as a warning only. Confirm node is on every runner that regenerates (owner: integrator)
- [ ] No claim row in `SESSION-CLAIMS.md`: this branch edits only non-shared paths (`cmd/vyomi/**`, `scripts/gen_mcp_matrix.py`, `scripts/mcp_wiring.json`, docs), and the claims file lives on the trunk (owner: integrator, if a row is wanted)

## Testing
- Base (`41161ac3e`): `cd cmd/vyomi && go test ./...` 28 PASS / 0 FAIL; `python3 scripts/gen_mcp_matrix.py --check` red (stale version stamp only).
- K1: L1-01 PASS (three outputs byte-identical across two runs; `--check` exit 0). L1-02 PASS (in a `/tmp` copy, `s3.bucket.versioning` `level.nano` full -> limited: `--check` exit 1, names `mcp_matrix.json` and `mcp_caps.json.gz (changed: core/capabilities/aws/s3.json)`). L1-03 PASS (`TestMCPCapsIndexMatchesRegistry`: 1,444 / 86 / 16). L1-04 PASS (`TestMCPDocsSnippetsUsePlaceholder`: 24,636 snippets, all with `{sim}`, none hard-coded).
- K2: L1-05 PASS (`TestMCPCapabilityIDPrefix`), L1-06 PASS (`TestMCPCapabilityWords`), L1-07 PASS (`TestMCPSnippetNano`, also the cloud-relay URL form), L1-08 PASS (`TestMCPServicesLevels`), L1-09 PASS (`TestMCPInstructionsNoVyomiUpForNano` + `TestMCPInstructionsSteerAwayFromRealCloud`); regression `TestMCPSnippetAWSCLICommandNames`. `go test ./...` 37 PASS / 0 FAIL.
- D0: headless Nano tab via Playwright + local relay; real Python SDKs; results in `MCP-V4-DISCOVERY.md`. Not run: the local portal on `:8099` with the service worker, a real Chrome tab, the cloud relay.
