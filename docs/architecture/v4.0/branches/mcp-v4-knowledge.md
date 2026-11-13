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
- **H1 — home resolver** (`cmd/vyomi/mcp_homes.go`, `mcp_proc_{other,windows}.go`). `probeHomes` runs in parallel, 1.5 s each:
  `GET {VYOMI_MESH_URL}/mesh/status` + `/healthz` (and the same on the legacy `VYOMI_ENDPOINT`/`VYOMI_SIMULATOR_PORT` base when it differs),
  `GET 127.0.0.1:{RELAY_PORT}/health`, `GET <relay URL>/` when `VYOMI_ENDPOINT` is the cloud relay, and
  `{VYOMI_TUNNEL_BIN|vyomi-tunnel} list mesh --json` (8 s cap, 1 MB stdout cap, own process group killed on timeout).
  Classification: `nano-local` (tunnel answers; `serving` = `tab:true`), `nano-cloud`, `mesh-local` (`mesh:true`; not serving when `locked`),
  `offline` (`/healthz` and no mesh), `mesh-codespace` (mesh rows = reachable; a live `forward ... -> <api>:9000` = serving at that local port;
  a Codespace forward on the mesh port is reported as the Codespace, not as a local mesh). Whitelists: `meshFields` (+ `health.state`,
  `resources.memory_cap_mb/usage_mb/free_mb`, `ai.state`) and the tunnel fields (`version, tab, tabs, features, vms[].vm/host_port,
  dbs[].db/engine/host_port`). `selectHome`: `VYOMI_TARGET` > `VYOMI_ENDPOINT` > the single serving home > the single reachable home; else none.
  Results are cached 10 s per process. `vyomi_status` gains `homes`, `selected`, `why` (legacy fields unchanged until H2); tools with
  `home=auto` use the selection and fall back to the legacy target with a warning when several homes answer.
- **H2 — `vyomi_status` v2 + `vyomi_reach`** (`cmd/vyomi/mcp_tools.go`). Status returns `homes`, `selected`, `why`, `endpoint`/`tls_endpoint`
  of the selected home and a hint per home (spec decision 8): Nano onboarding (nothing found), "run `vyomi-tunnel`" (installed, not running),
  "Open https://vyomi.cloud/nano" (tunnel without a tab), relay URL dead, mesh locked, Codespace without an API forward (the exact
  `vyomi-tunnel forward <target> 9000:9000`), "ask which space" (several homes). `vyomi up` appears only for an offline appliance or local
  mesh that does not answer. Selected `offline`: the 3.0.46 fields unchanged (`running, health, license, readiness, active_space`). Mesh:
  the `/mesh/status` whitelist under `mesh`, the same `/api/*` state, and `spaces_warning` when `/api/spaces` lists more than one (spec Q4
  default). Nano: `nano` (tunnel whitelist) and `running` = tab connected. `vyomi_reach {scope}` builds `{where,name,type,address,connect}`
  rows from the cached probes (tunnel `/health`: api, amqp, VMs, DBs; local mesh API; Codespace `list` rows) plus notes; it starts nothing,
  and the tunnel probe's process group is reaped after it exits.
- **H3 — env, scan, write_env (and services) take `home`** (`mcp_tools.go`, `mcp_scan.go`, `mcp_knowledge.go`, `mcp_homes.go`).
  `homeTarget` resolves `home` (auto/nano/mesh/offline); the offline home keeps the legacy target exactly. `envVars(cloud, home, target)`
  reads `homes.<offline|nano|mesh>`, drops any `{tls_*}` value on Nano with a warning, returns `unavailable` as warnings, and for the
  cloud relay rewrites the host-style Queue endpoint to path-style and drops AMQP. `vyomi_env` stamps `home` and adds `warnings`.
  `vyomi_scan_repo` findings carry `level` (Nano or offline column), `tier`, `mesh`, `mesh_only`; v4-only services (`aks`, `eks`, `bedrock`...)
  are `status: v4` (emulated) instead of "not emulated"; a mesh-anchored service on a Nano/offline home gets "needs a Pro/Max mesh" and is
  listed separately in the summary; Nano uses `homes.nano.scan_warnings` instead of the offline ones (which talk about :9443 and gRPC
  emulators); next steps carry `home=`. New scan aliases: `containerservice`, `armcontainerservice`, `kubernetes` -> `aks`.
  `vyomi_write_env` header `# Vyomi <home> <endpoint> — generated <RFC3339>`, filenames must start with `.env.vyomi`, an existing
  non-regular file (symlink) is never written through, and unavailable settings become `# WARNING` comments. `vyomi_services home=` says which
  `levels` column applies.
- **S1 (stretch, draft only)** — skill text in `integrations/claude-plugins/plugins/vyomi/skills/`: `vyomi-setup/SKILL.md` rewritten
  (home-aware: status -> ask when ambiguous / hand off -> scan with `home` -> env -> propose -> ask -> write -> verify with `vyomi_snippet`),
  new `vyomi-nano/SKILL.md` (tunnel install and version, key by asking never reading, tab check, relay-URL fallback, the Nano limits found in
  D0) and new `vyomi-mesh/SKILL.md` (locked handling, `vyomi mesh status`, `vyomi_reach mesh` and the forwards for the user to run, then
  `home: mesh`, AI via `vyomi_capability`). The four shared rules are word for word; added: "`vyomi up` only for offline / mesh-local".
  `plugin.json`, `marketplace.json` and the plugin README are **not** changed (they move with T1/T2/R1).

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
| H3: offline `vyomi_env` checked against goldens from `42d870e` for all three clouds (`testdata/mcp_env_*_offline_42d870e.golden.json`) | Azure only (as L1-23 says) | the offline home must not change for any cloud; the goldens were produced by building `42d870e`'s `cmd/vyomi` from `git archive` in `/tmp` |
| H3: `write_env` refuses to write through a symlink even with `overwrite=true` | keep `os.WriteFile` following links | an `.env.vyomi` symlink could point outside the project; found while adding the `.env.vyomi*` rule (regression test added) |
| K1 per-service `levels` = worst level (as the plan says), plus `level_counts` | worst only | S3 is 11 full / 36 limited: "limited" alone hides that most of it works |

### Decisions taken unattended
(Defaults taken without the owner because the session ran overnight; each is reversible.)

| Decision point | Default taken | Source of the default |
|---|---|---|
| Spec Q3: can Nano serve Cosmos / Key Vault through the tunnel? | D0 answered it: Cosmos yes (plain HTTP, root endpoint, Python verified); Key Vault no, so `homes.nano.azure.unavailable` carries the warning | D0 evidence; spec Q3 default ("mark them not via tunnel") applied to Key Vault only |
| Spec Q4: which space a direct `:9000` call hits on a multi-space mesh | not answered (D0 item 4 open); the resolver reports the mesh's `/mesh/status` and H2 reports its active space | spec Q4 default |
| Spec Q5: probe `mesh-codespace` by default? | only when `vyomi-tunnel` is found (`VYOMI_TUNNEL_BIN` or PATH) **and** credentials exist (env key, or the credentials file exists: `os.Stat` only, never read); 8 s cap | spec Q5 default |
| Plan H1.5 DECISION: a different Azure account form for Nano? | none needed: D0 rows 8–12 show `devstoreaccount1` with path-style Blob and host-style Queue works through the tunnel, so `Account` is unchanged | D0 evidence |
| `list --json` without a `schema` field (1.2.x) | accepted, rows read from `targets` (or `rows`); an explicit `schema` other than 1 is refused with a note (L1-14) | D0 item 3 shape; T1 adds `schema: 1` |
| Nano tunnel up but no tab | `reachable: true, serving: false`; it is selected only when it is the only reachable home (so the hint can say "open the tab") and does not make a working mesh ambiguous | spec decision 8 (tab:false hint) + §2 "exactly one reachable" |
| `VYOMI_ENDPOINT` meaning in v4 | a relay host (`*relay.vyomi.cloud`) or a non-local URL with a path is the Nano cloud relay; a bare host[:port] stays an appliance (Multipass VM IP), as in 3.0.46 | spec §2 (`nano-cloud` endpoint via `VYOMI_ENDPOINT`) + backward compatibility |

## Open issues
- [ ] D0 item 2 (Codespace mesh API target) and item 4 (space semantics on a mesh) need a Pro/Max key and a Mesh Codespace (owner: Rohith)
- [ ] `vyomi-tunnel list --json` envelope is `{targets, notes}` with no `schema`; the spec says `{rows, notes}` + `schema: 1` (T1, owner: tunnel session)
- [ ] Nano `/health` lists RDS proxies under `vms[]`, never `dbs[]` (owner: tunnel session)
- [ ] Nano RDS Data API loses state between statements; `e2e-relay.mjs` step 7 fails on the trunk (owner: Nano core)
- [ ] Console bug: `wasm/docs` AWS `cli` names come from botocore serviceId (`scripts/gen_nano_docs.py:255`), so the Nano console's SDK & CLI tab shows `aws s3 put-object`, `aws secrets-manager ...`, `aws cloudwatch-logs ...`. The MCP corrects them (K2); fix the generator on the trunk and drop `_aws_cli_fix` (owner: Nano docs)
- [ ] The Codespace probe is not side-effect free: `vyomi-tunnel list mesh` with a Pro key runs `configureSsh({yes:true})` (appends to `~/.ssh/config`) and `gh` (D0 §2). A status call should not edit ssh config; T1 could skip `configureSsh` for `--json` (owner: tunnel session)
- [ ] Codespace API target name (`service` row on :9000) is a guess until D0 item 2 runs; the resolver says so in `detail.api_target` (owner: Rohith)
- [ ] `gen_mcp_matrix.py` now needs `node` (snippets). `release.yml:156` and `conformance-release.yml:132` run it on GitHub runners (node preinstalled); `ci.yml:35` runs `--check` as a warning only. Confirm node is on every runner that regenerates (owner: integrator)
- [ ] S1 is a draft: the skills reference `vyomi-tunnel` >= 1.3.0 and `vyomi-tunnel mcp`, which exist only after T1/T2; `plugin.json` still says `vyomi mcp` / 3.0.45. Do not sync the plugin before R1 step 1. The A-tier evals (A-01..A-08) have not run (owner: Rohith)
- [ ] No claim row in `SESSION-CLAIMS.md`: this branch edits only non-shared paths (`cmd/vyomi/**`, `scripts/gen_mcp_matrix.py`, `scripts/mcp_wiring.json`, docs), and the claims file lives on the trunk (owner: integrator, if a row is wanted)

## Testing
- Base (`41161ac3e`): `cd cmd/vyomi && go test ./...` 28 PASS / 0 FAIL; `python3 scripts/gen_mcp_matrix.py --check` red (stale version stamp only).
- K1: L1-01 PASS (three outputs byte-identical across two runs; `--check` exit 0). L1-02 PASS (in a `/tmp` copy, `s3.bucket.versioning` `level.nano` full -> limited: `--check` exit 1, names `mcp_matrix.json` and `mcp_caps.json.gz (changed: core/capabilities/aws/s3.json)`). L1-03 PASS (`TestMCPCapsIndexMatchesRegistry`: 1,444 / 86 / 16). L1-04 PASS (`TestMCPDocsSnippetsUsePlaceholder`: 24,636 snippets, all with `{sim}`, none hard-coded).
- K2: L1-05 PASS (`TestMCPCapabilityIDPrefix`), L1-06 PASS (`TestMCPCapabilityWords`), L1-07 PASS (`TestMCPSnippetNano`, also the cloud-relay URL form), L1-08 PASS (`TestMCPServicesLevels`), L1-09 PASS (`TestMCPInstructionsNoVyomiUpForNano` + `TestMCPInstructionsSteerAwayFromRealCloud`); regression `TestMCPSnippetAWSCLICommandNames`. `go test ./...` 37 PASS / 0 FAIL.
- H1: L1-10..L1-16 PASS (`TestMCPHomesNanoOnly`, `...MeshOnly`, `...Offline`, `...Ambiguous`, `...Codespace`, `...CodespaceTimeout` (8.0 s, no child left), `...MeshWhitelist`) + `TestMCPHomesCache`. `go test -race` clean; `GOOS=windows go vet` clean. All tests hide any real `vyomi-tunnel`/credentials (`isolateHomes`) and probing tests use dead ports (`deadHomes`). Manual: the built binary against this machine saw the headless Nano tab (`nano-local`, serving) and a Docker offline appliance on `:9000`, and correctly selected nothing.
- H2: L1-17 PASS (`TestMCPStatusNanoNoTab`), L1-18 PASS (`TestMCPStatusMeshLocked`), L1-19 PASS (`TestMCPStatusNothingReachable`, also tunnel-installed and explicit-offline-down cases), L1-20 PASS (`TestMCPReach`: rows from `/health` + `list`, the fake tunnel's backgrounded `sleep` is gone after the call); `TestMCPStatusOtherHints` (ambiguous, Codespace forward, relay down, multi-space mesh). L1-13's "hint asks which space" is covered here. `go test -race` clean.
- H3: L1-21 PASS (`TestMCPEnvNanoAWS`), L1-22 PASS (`TestMCPEnvNanoAzure`, plus GCP), L1-23 PASS (`TestMCPEnvOfflineGolden`, all three clouds), L1-24 PASS (`TestMCPScanNanoHome`), L1-25 PASS (`TestMCPWriteEnvHome`); plus `TestMCPEnvNanoCloudRelay`, `TestMCPWriteEnvRefusesSymlink` (regression), `TestMCPServicesHome`. `go test ./...` 58 PASS / 0 FAIL; `-race` clean; `GOOS=windows go vet` clean.
- Fix after H3: a service whose every feature is `not_simulated` in the selected home (EKS on Nano) was summarised as emulated; now listed under NOT emulated "(not simulated on <home>)". Regression `TestMCPScanNotSimulatedInHome`. 59 PASS / 0 FAIL.
- Headless end-to-end (an L2-02/L2-03 equivalent without a real Chrome): `vyomi_env home=nano` output for aws, azure and gcp, sourced as shell env, drove boto3 (S3 create/list), azure-storage-blob (upload/download) and google-cloud-storage (bucket/upload/list) against the headless Nano tab through the local relay: all three worked.
- S1 drafts: frontmatter parsed (name matches the folder, description present), the four shared rules are byte-identical to the 3.0.46 skill in all three files, and `vyomi up` appears only in the restricting rule, the "never start" rule and the local-mesh step. No agent eval run.
- D0: headless Nano tab via Playwright + local relay; real Python SDKs; results in `MCP-V4-DISCOVERY.md`. Not run: the local portal on `:8099` with the service worker, a real Chrome tab, the cloud relay.
