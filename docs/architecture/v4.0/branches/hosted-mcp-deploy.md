# v4/hosted-mcp-deploy

Owner: claude (hosted MCP, PR 3) - Started: 2026-11-23 - Base: v4/hosted-mcp-scan-proposals (stacked, PR #709) - Status: in progress

## Purpose
PR 3 of `HOSTED-MCP-IMPLEMENTATION-PLAN.md`: everything needed to ship the hosted MCP server, and nothing that
ships it. The image, the portal App Platform component, the runbook and the release workflow. No image is pushed,
no tag is cut, and the DigitalOcean app, Cloudflare and DNS are untouched — those are owner gates (plan §9,
O-G1b, O-G2, O-G3).

The server is the `mcp` component of the **portal's** app, routed at `vyomi.cloud/mcp` with the prefix trimmed
(D-H2 = B', D-I6), running a pinned public image from GHCR.

## Architecture
| File | What it is |
|---|---|
| `deploy/mcp-hosted/Dockerfile` | Two stages: `golang:1.26-bookworm` builds `cmd/vyomi` with `CGO_ENABLED=0 GOARCH=amd64 -trimpath -ldflags=-s -w` and checks the binary advertises `--hosted`; the runtime is `gcr.io/distroless/static-debian12:nonroot` with `ENTRYPOINT ["/vyomi","mcp","--hosted"]` and `EXPOSE 8080`. No shell, no package manager, non-root |
| `deploy/mcp-hosted/portal-app-component.yaml` | The one service and the one ingress rule to merge into the portal's spec: `registry_type: GHCR`, registry `vyomi-cloud`, repository `mcp-hosted`, pinned `tag`, `basic-xxs`, 1 instance, `http_port: 8080`, health check `/healthz`, `match.path.prefix: /mcp` with no `preserve_path_prefix` so the prefix is trimmed |
| `deploy/mcp-hosted/add-component.py` | Merges that component into a fetched portal spec. Adds or replaces only the `mcp` service and the `/mcp` rule, inserts the rule before the portal's catch-all, refuses to write if anything else would change, and is a no-op on a second run |
| `deploy/mcp-hosted/set-image-tag.py` | Bumps only that component's image tag; refuses to write if more than the tag would change, and exits non-zero when the component is absent, so a release can never silently deploy nothing |
| `deploy/mcp-hosted/RUNBOOK.md` | The one-time steps in order (make the GHCR package public, add the component, the Cloudflare rule, the two secrets), the release, the by-hand verification, the rollback, a symptom table, and how to build and run it locally |
| `deploy/mcp-hosted/test_spec_scripts.py` | 36 checks over the component spec, both scripts, the Dockerfile and the workflow |
| `.github/workflows/mcp-hosted-release.yml` | On a `mcp-hosted-v*` tag only: guardrails → vet, `go test`, gofmt → build and push `ghcr.io/vyomi-cloud/mcp-hosted:<version>` (amd64) and smoke the image in the job → pin the tag in the portal spec and `doctl apps update --spec --wait` → smoke `https://vyomi.cloud/mcp` and check the portal still answers on `/` |

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| GHCR (`ghcr.io/vyomi-cloud/mcp-hosted`), public, no registry credentials in the app spec | Docker Hub with `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` (the plan's original row) | The workflow's own `GITHUB_TOKEN` with `permissions: packages: write` pushes it, so a release needs no registry secret at all. Owner's decision, 2026-11-23 |
| `linux/amd64` only | Also arm64, as the appliance images do | App Platform runs amd64; a second architecture would double the build for nothing |
| An immutable tag per release, never `:latest` | A moving `:latest` the component tracks | App Platform redeploys every component together, so a floating tag would let an unrelated portal deploy pick up an unreleased MCP |
| The merge and the tag bump are two small scripts that refuse to touch anything else | `yq` one-liners, or editing the spec by hand | "Without touching the portal component" is the actual requirement, and a script can prove it: both refuse to write when the diff reaches beyond the `mcp` component. It also makes the workflow's deploy step reviewable |
| The image is smoke-tested inside the release job before the tag is pinned | Deploy first, smoke production only | A broken image pinned into the portal's spec fails the whole app's deploy. Catching it in the job costs 20 seconds |
| `environment: production` on the deploy job | A plain job | Gives the owner a place to require an approval for a production deploy without changing the workflow |

## Open issues
- [ ] `docker build` / `docker run` could not be run on this machine: the Docker daemon stopped answering (the
  socket connects, `/_ping` returns nothing, `docker ps` hangs). The build stage was validated natively instead —
  see Testing. Needs one `docker build` + `docker run` + smoke on a machine with a working daemon before the
  first release (owner: next session, or me once Docker is back)
- [ ] O-G1b (GHCR package public), O-G2 (portal component + the two secrets) and O-G3 (Cloudflare) are owner
  gates; nothing here performs them (owner: Rohith)
- [ ] `packaging/tunnel/server.json` gets its `remotes` entry only after the first production deploy (owner: Rohith)

## Testing
Run on macOS (darwin/arm64), 2026-11-23.

| What | Command | Result |
|---|---|---|
| Deploy spec checks | `python3 deploy/mcp-hosted/test_spec_scripts.py` | 36/36 PASS |
| Workflow + spec YAML parse | `python3 -c "import yaml, sys; [yaml.safe_load(open(f)) for f in (...)]"` | both parse |
| Dockerfile build stage, natively | `cp -R cmd <ctx>/ && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w"` | a statically linked `ELF 64-bit x86-64`, stripped, 8.7 MB — so `distroless/static` is the right base and the context needs only `cmd/` |
| The image's own build-stage check | `vyomi mcp --help \| grep -- --hosted` | passes |
| Go suite + guardrails | `go -C cmd/vyomi test -count=1 ./...`, `bash tools/guardrails/run.sh` | unchanged from PR 2: green, eight hosted rows PASS |
| Smoke against the server from source | `tools/mcp-hosted-smoke.sh http://localhost:8080/mcp` | 27/27 PASS (the binary this image ships) |

**Not run: `docker build` and `docker run`.** The daemon on this machine is wedged, and restarting Docker Desktop
would kill the containers the developer has running, so it was left alone. What that leaves unverified is narrow
and worth naming: that `gcr.io/distroless/static-debian12:nonroot` resolves and runs this binary, that the
`golang:1.26-bookworm` tag exists, and the `COPY` paths inside a real build context. The release workflow runs
exactly those three things (build, run, smoke) before it pushes anything, so the first tag would catch a mistake
in them — but it should be run by hand first.
