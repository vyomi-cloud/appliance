# v4/mcp-v4-knowledge

Owner: overnight Claude session for Rohith - Started: 2026-11-14 - Base: origin/v4-on-main (41161ac3e) - Status: in progress

## Purpose
Make `vyomi mcp` (the Go MCP server in `cmd/vyomi`) work for v4, where the simulator lives in a Nano browser tab, a local mesh
or a Codespace mesh, not only a Docker appliance on `:9000`. This branch carries these steps of
`vyomi-mcp-v4-implementation-plan.md` (owner's specs folder, outside the repo):
- D0 discovery, items 1 and 3: Nano SDK wiring through the local relay, and `vyomi-tunnel list --json`.
- K1–K2: knowledge v2, from `core/capabilities/**` and `wasm/docs/**`.
- H1–H3: home detection and home-aware tools.
- Run 2 (2026-11-14, owner decision: same branch): T1 (`vyomi-tunnel mcp`, the `list --json` contract), T2 option C (the five
  `vyomi-mcp` binaries bundled in the `vyomi-tunnel` npm package) and S1 wiring (plugin manifest, README, skills).
- Run 3 (2026-11-14, unattended): D0 items 2 and 4 **locally** (a local v4 mesh from this worktree's image, no licence, portal, GitHub
  or Codespace), and the `spaces_warning` fix that item 4 found.

Out of scope for this branch: publishing (npm, tap, plugins repo), releases and tags, the portal, D0 items 2 and 4 on a real Codespace
(run 3 did them locally), the agent evals.

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
- **S1 wiring (run 2)** — `plugin.json`: `mcpServers.vyomi = {"command":"vyomi-tunnel","args":["mcp"]}`, version 4.0.0 (appliance `VERSION`),
  description names Nano/mesh and the 1.3.0 floor; `marketplace.json`: metadata and plugin version 4.0.0, same description change;
  `integrations/claude-plugins/README.md` rewritten per plan S1.5 (install the tunnel >= 1.3.0 by brew or npm, then the marketplace and
  `/plugin install vyomi@vyomi`; MCP-only registration `claude mcp add --scope user vyomi -- vyomi-tunnel mcp`; v4.0.0 offline users keep
  `vyomi mcp`; the 8 tools and 3 skills). The three skills now state the minimum tunnel version (1.3.0) explicitly; `vyomi-mesh` says that
  `ssh <vm>.vyomi` needs a one-time `vyomi-tunnel config` (asked first), since T1 listing no longer edits ssh config.
- **S1 (stretch, draft in run 1)** — skill text in `integrations/claude-plugins/plugins/vyomi/skills/`: `vyomi-setup/SKILL.md` rewritten
  (home-aware: status -> ask when ambiguous / hand off -> scan with `home` -> env -> propose -> ask -> write -> verify with `vyomi_snippet`),
  new `vyomi-nano/SKILL.md` (tunnel install and version, key by asking never reading, tab check, relay-URL fallback, the Nano limits found in
  D0) and new `vyomi-mesh/SKILL.md` (locked handling, `vyomi mesh status`, `vyomi_reach mesh` and the forwards for the user to run, then
  `home: mesh`, AI via `vyomi_capability`). The four shared rules are word for word; added: "`vyomi up` only for offline / mesh-local".
  (Run 1 left `plugin.json`, `marketplace.json` and the README alone; run 2 changed them, above.)

- **T1 — `vyomi-tunnel mcp`** (`wasm/relay/mcp-launch.mjs` new; `local-relay.mjs`, `mesh-cli.mjs`; packaging copies in
  `packaging/tunnel/bin/`, `package.json` 1.3.0, `README.md`).
  - Dispatch: `argv[2] === "mcp"` is the first thing both entry files do (`local-relay.mjs` and the hand-derived
    `packaging/tunnel/bin/vyomi-tunnel.mjs`), before the `ws` require and the credentials gate, so the MCP needs no key and
    nothing reaches stdout before it.
  - `mcp-launch.mjs`: `resolveMcp` picks `../mcp/<platform>-<arch>/vyomi-mcp[.exe]` (relative to the launcher; restores 0755 once
    if an unpack dropped the bit), else `vyomi-mcp`, else `vyomi mcp` on PATH; nothing found = one stderr line + exit 127.
    `launchMcp` spawns with `stdio: inherit`, sets `VYOMI_TUNNEL_BIN` to the entry script (real path), appends node's directory
    to the child's PATH (the MCP runs `node <entry> list ...`), forwards SIGINT/SIGTERM/SIGHUP and passes the exit code through
    (128 + signal when killed).
  - `list --json` is now the contract `{schema: 1, rows: [{where, name, type, address, connect}], notes: [string]}`. Exit 0 with
    rows, 1 with none, 2 with no credentials or a usage error. JSON on every path but a usage error: no credentials or a bad key
    print `{schema:1, rows:[], notes:[<error>]}`. `NoMeshSession`/`SessionEnded` mean the key is valid and only the Mesh is down,
    so the Nano rows are listed and the Mesh gets a `mesh: ...` note (text mode too). Listing calls `openMesh({configure:false})`:
    it never writes `~/.ssh/config` or `~/.vyomi/ssh_config`; when a row's connect is `ssh <name>.vyomi` and the Include is
    missing (read-only `sshConfigured()`), a note says `vyomi-tunnel config`. `connect`/`forward` still configure ssh as before.
  - Help: an "Agents" heading with `vyomi-tunnel mcp`, `help mcp`, and the `--json` contract under `help list`.
  - Packaging regeneration (no generator exists; the old header pointed at itself): `bin/*.mjs` other than the entry are copies of
    `wasm/relay/<same>` with only the version stamps changed (`mesh-cli.mjs` `vyomi-tunnel X.Y.Z`, `credentials.mjs`
    `version = "X.Y.Z"`); the entry is ported by hand. The recipe is now in the entry's header. The 1.2.1 help text that existed
    only in the packaging copy (`help ssh`, `help troubleshoot`, the https note) was back-ported to the canonical `mesh-cli.mjs`
    first, so the copy is a pure regeneration.
  - Tests: `wasm/relay/test-mcp-launch.mjs` (L1-26..L1-28, exit code and SIGTERM passthrough) and `wasm/relay/test-list-json.mjs`
    (L1-29, auth-error JSON, no ssh edits, usage errors), both `node --test`, against a temp copy / the packaged bin.
- **T2 — bundle the binaries in `vyomi-tunnel` (option C)** (`scripts/build_tunnel_mcp.sh` new, `.gitignore`, `packaging/tunnel/package.json`,
  `.github/workflows/tunnel-release.yml`).
  - `scripts/build_tunnel_mcp.sh [outdir]`: `gen_mcp_matrix.py` (fresh embedded knowledge), then `CGO_ENABLED=0 go -C cmd/vyomi build -trimpath
    -ldflags "-s -w"` for darwin/arm64, darwin/amd64, linux/arm64, linux/amd64, windows/amd64 into `packaging/tunnel/mcp/{darwin-arm64,darwin-x64,
    linux-arm64,linux-x64,win32-x64}/vyomi-mcp[.exe]` (Node's names, the launcher's lookup), `chmod 755`.
  - `packaging/tunnel/mcp/` is git-ignored (one line next to `packaging/docker/mcp/`). `package.json` `files`: `bin/`, `mcp/`, `README.md`;
    no `optionalDependencies`, no new packages.
  - `tunnel-release.yml`: `actions/setup-go` (`go-version-file: cmd/vyomi/go.mod`) and `actions/setup-python` 3.12 next to the existing
    setup-node 22 (the generator needs node); `scripts/build_tunnel_mcp.sh` before the dry pack; the dry-pack step now also reads
    `npm pack --dry-run --json` and fails when any of the five binaries is missing or the packed size is over 25 MiB. Trusted publishing,
    the status step and the tap bump are unchanged. Not run (no workflow runs from this branch).
- **Run 3: `spaces_warning` (D0 item 4)** (`cmd/vyomi/mcp_tools.go`). `countSpaces` became `meshSpaces` (reads id, name and cloud for each
  space, plus `active_space_id`, from `/api/spaces`; an absent provider is aws, as on the appliance) and `spacesWarning`. The warning now
  appears only when one cloud has more than one space (a fresh mesh has aws-, gcp- and azure-default, which used to trigger it). It names
  where each cloud's calls land (the mesh's active space for its cloud, otherwise that cloud's first space) and says that only
  `POST <mesh>/api/spaces/<id>/switch` moves it, not the Nano console. Regression test: `TestMCPStatusMeshSpacesWarning`.
  Evidence: `MCP-V4-DISCOVERY.md` §4.

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

### Decisions taken unattended (run 2)
| Decision point | Default taken | Source of the default |
|---|---|---|
| Gate 0a: trunk moved past `41161ac3e` | merged `origin/v4-on-main` @ `debec6ae7` (claims-only commit) as `e7acaff98`, full suite green, pushed | run-2 instructions |
| Gate 0b: claim | proceed: the only row on the trunk's `SESSION-CLAIMS.md` is this branch's, claiming `wasm/relay/{local-relay,mesh-cli,mcp-launch,test-*}.mjs` and `packaging/tunnel/**` | run-2 instructions |
| `test-mesh-shell` red on the unchanged base (`simulator refused the shell: HTTP 404`) | environment, not code: the system Python's uvicorn has no WebSocket library. Run with `PY=` a temp venv (fastapi, uvicorn, websockets); no repo change | test header (`PY=<venv>/bin/python`) |
| How to "regenerate" `packaging/tunnel/bin` (the header named only itself) | copy + version stamps for the shared modules, hand-port for the entry; recipe written into the entry header | how 1.2.1 was actually made (`a10498d75`) |
| Packaging `mesh-cli.mjs` was ahead of canonical (1.2.1 help text) | back-ported to canonical before editing, so nothing is lost on regeneration | spec §1 (canonical source is `wasm/relay`) |
| Canonical version strings | unchanged (`1.2.0`, as before: canonical is not stamped per release); packaging stamped `1.3.0` with `package.json` | existing practice |
| `list --json` key `targets` | dropped (`rows` only, plan T1.3); the two assertions in `test-tunnel-credentials.mjs` that read `.targets` now read `.rows` (+ `schema`). The MCP reads both shapes | plan T1.3, spec §4.3 |
| `NoMeshSession` / `SessionEnded` | the key is valid: list Nano, note the Mesh; same in text mode (was: nothing listed, exit 1) | plan T1.3 ("still print valid JSON with a note") |
| Listing and ssh config | never configured by `list`; a note points at `vyomi-tunnel config` when needed | plan T1.3, D0 §2 |
| T2 Python in the workflow | `actions/setup-python` 3.12 (the job used the runner's python3 before) | plan T2.4 ("then Python") |
| T2 size guard unit | 25 MiB (26,214,400 bytes) on npm's packed `size`; the step also fails if one of the five binaries is missing | plan T2.5 |
| T2 Homebrew formula | unchanged (it installs the same npm tarball); L2-10 not run (needs the tap branch and two Macs) | plan T2.6 |
| S1 plugin version | 4.0.0 in `plugin.json` and both `marketplace.json` fields (= appliance `VERSION`) | spec decision 11, Q6 |
| S1 plugin description | updated in both manifests to say Nano/mesh and "Needs vyomi-tunnel 1.3.0" (the manifest has no version-floor field) | spec decision 11 |
| S1 plugin icon | none added (validator advisory `ICON_MISSING`, non-blocking; 3.0.45 had none either) | out of scope (no asset to use) |

### Decisions taken unattended (run 3)
| Decision point | Default taken | Source of the default |
|---|---|---|
| Compose project name | `vyomi-mesh`, as asked: no project of that name existed (`docker compose ls -a`), so the container is `vyomi-mesh-simulator-1`, as in a Codespace | run-3 instructions |
| `vyomi-net` (fixed network name in the mesh compose) belongs to the owner's running `vyomi` project, whose `simulator` is on it | the `/tmp` override also renamed the network to `mcpv4-run3-net` (and `VYOMI_INSTANCE_NETWORK` with it). Joining it would have put two `simulator` services on one network, and `down` would have tried to remove the owner's network. Classification does not depend on the network name | Docker hygiene rule (never touch what this run did not create) wins over "override only image and port" |
| `pull_policy: always` in the compose file vs a local image | `docker compose up -d --pull never simulator` (CLI flag; the override stays minimal) | the compose file stays unchanged |
| boto3 for item 4 | the existing `/tmp/mcpv4-venv` (boto3 1.44.3, from run 1), used read-only; the system python has no boto3 | no new install needed |
| Item 2 inspect rows on a shared Docker host | `docker ps -q` limited to `label=com.docker.compose.project=vyomi-mesh` (a Codespace runs only those); the exact `-f` format of `mesh-ssh.mjs`. The all-host listing (43 rows) was kept in `/tmp` only | faithful to a Codespace |
| The MCP's view with the owner's offline appliance on `:9000` | recorded as is (ambiguous, correct), and repeated with `VYOMI_SIMULATOR_PORT` pointing at a dead port to show the Codespace selection | the owner's `:9000` must not be stopped |
| The fake tunnel's rows | built by the `list` mapping of `mesh-cli.mjs` (copied verbatim into a `/tmp` script) from the real `classifyTargets()` output; a second variant adds a `forward` row for `127.0.0.1:9100` (the published port stands in for `vyomi-tunnel forward`) | task: "built from that real classification" |
| `spaces_warning` false positive and wrong advice (item 4) | fixed in `cmd/vyomi/mcp_tools.go` with a regression test (allowed: a fix found in item 4); `wasm/**` and the skill left alone | run-3 rules |
| `MESH-GOLIVE-CHECKLIST.md` §4 | not edited (outside the allowed paths); the lines to add are in `MCP-V4-DISCOVERY.md` §4.3 | run-3 rules |
| `vyomi-tunnel forward simulator` not resolving | recorded as an open issue for the tunnel session, not fixed (`wasm/**` is off limits) | run-3 rules |

## Open issues
- [x] D0 items 2 and 4 verified locally in run 3 (`MCP-V4-DISCOVERY.md` §4). A real Codespace is still to confirm: add the two lines of
  `MCP-V4-DISCOVERY.md` §4.3 to `MESH-GOLIVE-CHECKLIST.md` §4 (not edited here; owner: Rohith)
- [x] `vyomi-tunnel list --json` envelope: now `{schema: 1, rows, notes}` (T1)
- [ ] Nano `/health` lists RDS proxies under `vms[]`, never `dbs[]` (owner: tunnel session)
- [ ] Nano RDS Data API loses state between statements; `e2e-relay.mjs` step 7 fails on the trunk (owner: Nano core)
- [ ] Console bug: `wasm/docs` AWS `cli` names come from botocore serviceId (`scripts/gen_nano_docs.py:255`), so the Nano console's SDK & CLI tab shows `aws s3 put-object`, `aws secrets-manager ...`, `aws cloudwatch-logs ...`. The MCP corrects them (K2); fix the generator on the trunk and drop `_aws_cli_fix` (owner: Nano docs)
- [x] `vyomi-tunnel list` no longer runs `configureSsh` (T1). It still runs `gh` for a Pro key (that is how it reaches the Codespace)
- [x] Codespace API target name: `vyomi-mesh-simulator-1`, a `service` row on :9000 (run 3). `codespaceHome` picks it. The fallback text for
  "no service row on :9000" still says "not verified yet (D0 item 2)"; reword it on the next code change (owner: this branch)
- [ ] `vyomi-tunnel forward simulator 9000:9000` fails ("not found in the Codespace"): `resolve()` tries only `vyomi-i-<n>`, `vyomi-<n>` and `<n>`,
  never the compose-service label that `simulatorTarget()` uses. The user has to type `vyomi-mesh-simulator-1`, which `list` shows. Fix it in
  `wasm/relay/mesh-ssh.mjs` `resolve()` with a fallback to `composeContainer(name)` (owner: tunnel session)
- [ ] The Nano tab's active space and the mesh's active space are independent: `mesh-link.js` forwards `/_wire/*` without a space id, and a
  Nano switch writes only IndexedDB, so a mesh-homed Nano space is served by whatever space is active on the mesh. A product decision:
  send the space id, or switch the mesh too (owner: Nano core / mesh)
- [ ] `skills/vyomi-mesh/SKILL.md` describes `spaces_warning` as "direct SDK calls land in the active one". This is still true per cloud, but
  the skill could say "per cloud" and "not via the Nano console" (owner: this branch, next S1 touch)
- [ ] `gen_mcp_matrix.py` now needs `node` (snippets). `release.yml:156` and `conformance-release.yml:132` run it on GitHub runners (node preinstalled); `ci.yml:35` runs `--check` as a warning only. Confirm node is on every runner that regenerates (owner: integrator)
- [ ] S1 is wired (`plugin.json` runs `vyomi-tunnel mcp`, 4.0.0) but `vyomi-tunnel` 1.3.0 is not published: **do not sync the plugin before R1 step 1** (the tunnel release). The A-tier evals (A-01..A-08) have not run (owner: Rohith)
- [ ] Not run for T2: L2-10 (brew on arm64 + x64 macOS), L2-11 in the `node:20` linux/amd64 + linux/arm64 containers, P-02 (workflow dry run), P-03 (after a real publish) (owner: Rohith / release)
- [ ] Plugin icon: `claude plugin validate` advises `ICON_MISSING` (non-blocking) (owner: Rohith)
- [x] Claim row: on the trunk since `debec6ae7` (`wasm/relay/...`, `packaging/tunnel/**`); remove it when this branch merges (owner: integrator)
- [ ] `test-amqp-bridge.mjs` needs the vendored Pyodide (`wasm/vendor/pyodide`, absent in a worktree); not run (fixture for a conformance test, unrelated to T1)

## Owner review fixes (2026-11-14, independent Linux verification)

Found by re-running the branch on Linux (the overnight runs tested on macOS only):

| # | Problem | Fix |
|---|---|---|
| 1 | `TestMCPHomesCodespaceTimeout` and `TestMCPReach` failed on Linux: the killed probe processes are zombies until init reaps them, and `kill(pid, 0)` succeeds on a zombie. The product code (process-group kill) was correct; macOS reaps at once, so the runs never saw it. Would break Linux CI and containers without a prompt reaper. | `stillRunning(pid)` in `mcp_homes_test.go`: treats state `Z` in `/proc/<pid>/stat` as gone and waits up to 2 s. 59/59 on Linux, both tests stable over repeated runs, race-clean; vet clean for darwin and windows. |
| 2 | `vyomi-tunnel mcp` logged `endpoint http://127.0.0.1:9000` at startup even when the selected home was the Nano tab. | The banner names what is probed (Nano tunnel port, mesh/appliance URL, Codespace via vyomi-tunnel) and points to `vyomi_status`. `--help` now lists `vyomi_reach`. |
| 3 | `gen_mcp_matrix.py` (and so `build_tunnel_mcp.sh`) rewrote `mcp_caps.json.gz` / `mcp_docs.json.gz` on every run; gzip bytes differ between zlib builds, so on any other machine the tracked files showed as modified with identical content. | A `.gz` output is rewritten only when its decompressed content changed. Verified: a content-identical file recompressed differently is left alone; a stale file still fails `--check` and is rewritten. |

## Pre-release integration test (2026-11-14)

`tools/mcp-eval/prerelease-it.sh` tests the release candidate on the owner's Mac without publishing anything:
`package` (build_tunnel_mcp.sh, npm pack, install into a temp prefix, MCP handshake with no key), `linux` (the same tarball in
node:20 arm64/amd64 containers), `brew` (a throwaway tap whose formula points at the local tarball), `homes` (offline on :9000,
a local mesh on :9100 from the branch image, Codespace via a fake tunnel), `nano` (the real tab through the tunnel on :8090),
`agent` (`claude -p --plugin-dir` evals A01/A01b/A02/A03/A05/A06 with checks on tool calls, answer text and `.env.vyomi`).
It removes only what it created (compose project vyomi-it-mesh, image vyomi-it-mesh:local, tap vyomi/it, $IT_DIR).

Writing it found one launcher bug, fixed here: `vyomi-tunnel mcp` always overwrote `VYOMI_TUNNEL_BIN` with its own entry, so an
explicit value (a pinned install, a test harness) was ignored. It now keeps an explicit value and only defaults it when unset.
Regression test L1-27c in `wasm/relay/test-mcp-launch.mjs` (fails on the previous launcher, passes now; launcher suite 7/7).

## First pre-release run on the owner's Mac (2026-11-14)

`prerelease-it.sh all`: package 10, linux 2, brew 3 (+1 warn), homes 11 (incl. the local mesh from the branch image), nano 6
(real tab), agent 6 pass, **1 fail**. Fixed in this branch:

| Finding | Fix |
|---|---|
| A01: on "Set this project up to run against Vyomi, using the Nano tab." the agent wrote `.env.vyomi` without asking ("The user asked me to set it up … so I'll write"), then installed a venv and ran the app. The skill already said to get the user's OK. | Owner decision: keep ask-first. `vyomi-setup` step 4 and Rules now say a general "set this up" request is not approval; show the path + contents and stop. `vyomi_write_env` description and the server instructions say the same. Regression test `TestMCPWriteEnvRequiresExplicitApproval` (fails on the old wording). Re-run A01 with IT_RUNS=3. |
| brew: the formula's `test do` started the relay, which refuses to start without a key since 1.2.x, so `brew test` always failed. | `packaging/brew/vyomi-tunnel.rb` tests `--version` and an MCP `initialize` through `vyomi-tunnel mcp` (no key needed). The same block must go into `vyomi-cloud/homebrew-tap` (owner). prerelease-it now reports a failing `brew test` as FAIL. |

## Second pre-release run: A06 with IT_RUNS=3 (2026-11-14)

A06 ("Use my Mesh Codespace") passed 2/3. Both findings are fixed here:

| Finding | Fix |
|---|---|
| Run 1: the agent ran `vyomi-tunnel forward …` itself (backgrounded through Bash). The skill rule read "The MCP never starts anything", which a model can take as being about the MCP only. | `vyomi-setup` and `vyomi-mesh` Rules: never start the tunnel, a forward, a Codespace or `vyomi up` yourself, never through Bash, not even in the background. The status hint and the `vyomi_reach` note now say "ask the user to run … (do not run it yourself)". |
| Runs 2-3 (flagged by the agent itself): with a Codespace mesh, `vyomi_env` / scan with `home: mesh` used the local-mesh target (`VYOMI_MESH_URL`) and labelled it `mesh-local`. Real use only worked by coincidence (forward `9000:9000`), and failed on a machine whose offline appliance holds :9000 (the owner's). | `home=mesh` resolves to the Codespace when no local mesh answers: its live forward's local port, or (no forward yet) the suggested forward's ports with a warning naming the command. Suggested forwards use a free local port (`9000`, else `9100+`; TLS `9443`, else `9543+`). Tests `TestMCPForwardPortSkipsBusyPorts`, `TestMCPEnvMeshIsCodespace`; prerelease-it `homes/codespace-env`. `api_target` fallback text no longer says "not verified yet". |

## Gated tunnel release (2026-11-14)

Before: `tunnel-release.yml` built and published in one job, and the release checks in `release.yml` run *after* a release
(`workflow_run`). Now nothing reaches npm or Homebrew unless every gate passed on the exact tarball being published.

| Job | Runs on | What it proves |
|---|---|---|
| `build` | ubuntu | tag matches `package.json` (or is `X.Y.Z-rc.N` on top of it: the build stamps that version into `package.json` and the three bin version strings); five `vyomi-mcp` binaries; `npm pack` **once**; 25 MB / five-binary guard; tarball uploaded as an artifact |
| `checks` | ubuntu | `tunnel-mcp-checks.yml` (reused): generator `--check` (fails, not warns), `go vet` + `go test -race`, launcher + `list --json` tests, the relay suites, `claude plugin validate`, shellcheck of `prerelease-it.sh` |
| `linux` | ubuntu (+QEMU) | `prerelease-it.sh package linux homes` on the artifact: install + handshake with no key, `node:20` arm64/amd64 containers, fake Codespace + a local mesh built from this commit |
| `macos` | macos-latest | `prerelease-it.sh package brew` on the artifact: darwin binary, formula rendered from `packaging/brew` installed from the tarball, `brew test` |
| `windows` | windows-latest | `npm i -g` the artifact; `vyomi-tunnel --version`; `vyomi-tunnel mcp` answers `initialize` |
| `publish` | ubuntu | needs all of the above; `npm publish <the tarball>` (no re-pack) to dist-tag `latest` (final) or `next` (RC); Homebrew tap only for final, non-dry releases, its formula rendered from `packaging/brew/vyomi-tunnel.rb` (so the tap gets the `test do` block too) |

Triggers: `tunnel-vX.Y.Z` (final), `tunnel-vX.Y.Z-rc.N` (testers: `npm i -g vyomi-tunnel@next`; `latest` and Homebrew untouched),
`workflow_dispatch` (dry run by default; any branch: `gh workflow run tunnel-release.yml --ref v4/mcp-v4-knowledge -f dry_run=true`).
`tunnel-mcp-checks.yml` also runs on pushes to `v4-on-main` / `v4/**` touching these paths and on PRs to the trunk (`ci.yml` covers only `main`).
Not covered by CI: the `nano` and `agent` stages (a real browser tab, a Claude login), which stay on the owner's Mac before tagging.
`prerelease-it.sh package` with `IT_SKIP_BUILD=1` no longer needs Go, and checks `--version` against the tarball's own `package.json`.

Verified here: actionlint + shellcheck clean; the version step on `tunnel-v1.3.0-rc.1` (stamps 4 files, channel `next`) and on a
mismatched tag (fails); the pack guard on the current tree; the plugin validates; relay tests pass. Not run here: Go (this sandbox cannot
download the Go 1.26 toolchain); GitHub ran both: `Tunnel + MCP checks` green on the push, and the release dry run passed every gate
(package 8, linux 2, homes 10 + offline SKIP incl. the mesh image build and S3 on it, macOS package + brew, Windows); its first dry-run
publish failed because npm reads `dist/x.tgz` as a GitHub `user/repo`, fixed with `./dist/…` (verified with a local `--dry-run`).
First real run: tag `tunnel-v1.3.0-rc.1` on `6ac9bc2` (pushed by the owner) -> all gates green -> `vyomi-tunnel@1.3.0-rc.1` on npm `next`
via trusted publishing with SLSA provenance; `latest` stays 1.2.1, Homebrew untouched. Installed from npm here: `--version` = 1.3.0-rc.1,
`vyomi-tunnel mcp` answers (server `vyomi` 4.0.0, 8 tools) with an empty HOME and writes nothing to it.
Owner's Mac with the RC: `vyomi_status` correct (offline selected as the only serving home; Nano tunnel up, no tab; :9000 not a mesh).
Its Codespace probe showed GitHub's misleading 403 "Must have admin rights to Repository" (a `gh` login without the `codespace` scope),
cut off before the fix. `findCodespace` (`mesh-ssh.mjs`, both copies) now says: "gh cannot list your Codespaces: its login lacks the
codespace scope. Run: gh auth refresh -h github.com -s codespace" (and "Run: gh auth login" when logged out), short enough for the
MCP's 160-char note clip. Test in `test-mesh-ssh-transport.mjs` (fails on the old code); that suite now also runs in CI.

## Testing
- Run 3 (local mesh, D0 items 2 and 4): step 0 fast-forward to `8708cfe83`, `go test ./...` and `--check` green. Image built from the worktree,
  mesh `vyomi-mesh` up, `/mesh/status` `mesh:true` (tier max); `classifyTargets` row `vyomi-mesh-simulator-1` / `service` / `172.23.0.2:9000`;
  `vyomi mcp` with a fake `list mesh --json` in five scenarios (`MCP-V4-DISCOVERY.md` §4.1); item 4 with eight boto3 steps (§4.2).
  After the fix: `go test ./...` 60 PASS / 0 FAIL (new: `TestMCPStatusMeshSpacesWarning`, which fails on `8708cfe83`'s `mcp_tools.go`);
  `GOOS=windows go vet` clean; `--check` OK; the fixed binary on the live mesh printed the per-cloud warning.
- Run 2, gate 0a (after merging the trunk @ `debec6ae7`): `go test ./...` 59 PASS / 0 FAIL; `gen_mcp_matrix.py --check` OK; relay
  `test-mesh-link` 29 PASS, `test-mesh-shell` 47 PASS (with `PY=` a venv that has uvicorn + websockets), `test-mesh-session-derived` 4 PASS,
  `test-mesh-ssh` 23 PASS.
- T1: `node --test wasm/relay/test-list-json.mjs wasm/relay/test-mcp-launch.mjs` 14 PASS / 0 FAIL (L1-26..L1-29 included; L1-26 builds the real
  `vyomi-mcp` and drives `initialize` + `tools/list` through the packaged entry with no credentials). The no-ssh-edit test was checked
  against the 1.2.1 code (`git archive HEAD`): the old `list mesh --json` writes `~/.ssh/config`, so the test fails there. Also green:
  the four relay tests above, `test-tunnel-credentials`, `test-mesh-ssh-transport`, `test-tunnel-k3s`, `test-keeper`, `test-gw-egress`,
  `test-gh-manager`, `test-mesh-lazy-hub`, `test-mesh-forwarded-host`, `test-worker-egress`; go 59/0; generator `--check` OK.
- T2, P-01 PASS (local): `scripts/build_tunnel_mcp.sh` in ~20 s (binaries 7.6–8.3 MB; the generator rewrote nothing tracked);
  `npm pack --dry-run` lists `bin/mcp-launch.mjs` and the five `mcp/<platform>-<arch>/vyomi-mcp[.exe]`, 18 files, package size 19.6 MB
  (18.7 MiB) / unpacked 41.9 MB; the workflow's guard snippet passes; no `optionalDependencies`; `git status` shows no binaries.
- S1, P-04 PASS (local): `claude plugin validate` (Claude Code 2.1.309) passes for the marketplace, the plugin and the skills directory
  (one non-blocking advisory, `ICON_MISSING`); JSON parses; each `SKILL.md` has `name` = folder + `description` (289/327/390 chars); the four
  shared rules are byte-identical to the 3.0.46 skill in all three (the fifth, the old `vyomi-docker` install line, is replaced on purpose);
  `vyomi up` appears only in the restricting rule, the never-start rule and the local-mesh step. `plugin.json` command = `vyomi-tunnel mcp`,
  which L2-11 below exercises from an installed tarball.
- T2, L2-11 local half PASS (macOS arm64 only): `npm pack` to `/tmp`, `npm i -g --prefix /tmp/mcpv4-npm ./vyomi-tunnel-1.3.0.tgz`; all five
  bundled binaries are 0755 after install; `vyomi-tunnel mcp` with a temp HOME and no key answered `initialize` (server `vyomi` 4.0.0,
  protocol 2024-11-05) and `tools/list` (8 tools), exit 0, stdout = exactly the two responses, nothing written to HOME. Not run:
  the `node:20` linux/amd64 and linux/arm64 containers, L2-10 (brew), P-02 (workflow dry run), P-03 (after a real publish).
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
