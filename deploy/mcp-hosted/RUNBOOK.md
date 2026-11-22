# Hosted MCP: deploy runbook

The hosted Vyomi MCP server runs as the **`mcp` component of the portal's DigitalOcean App Platform app**, routed
at `vyomi.cloud/mcp` (D-H2 = B', `HOSTED-MCP-DESIGN.md` §5). It runs from a **pinned public image**,
`ghcr.io/vyomi-cloud/mcp-hosted:<version>`, `linux/amd64` only, so a portal deploy only re-pulls the same image
and an MCP build can never block a portal deploy.

**App Platform deploys all components together.** Bumping this component's image tag also redeploys the portal's
current `main` from its own source, and a failed component rolls the whole app back. That is the known trade-off
of B'. Deploy when the portal's `main` is in a state you are willing to ship.

Who can run this: whoever holds `DIGITALOCEAN_ACCESS_TOKEN` for the Vyomi team and can edit the portal app. The
one-time steps are owner gates (`HOSTED-MCP-IMPLEMENTATION-PLAN.md` §9, O-G2 and O-G3).

---

## 0. One-time, in this order

### 0a. Publish the image and make the package public

The first release tag builds and pushes `ghcr.io/vyomi-cloud/mcp-hosted:<version>`. A new GHCR package is
**private** by default, and App Platform pulls it **anonymously** (the component carries no registry
credentials), so the package must be public before the component is added:

1. Push the first release tag, `mcp-hosted-v0.1.0` (owner's call, plan §9). The release workflow's
   build-and-push job succeeds; its deploy job fails or is skipped, which is expected on a first release,
   because the portal app has no `mcp` component yet.
2. github.com/orgs/vyomi-cloud → **Packages** → `mcp-hosted` → **Package settings** → **Change visibility** →
   **Public**. Confirm with the package name.
3. Check an anonymous pull works, from a machine with no GHCR login:
   `docker pull ghcr.io/vyomi-cloud/mcp-hosted:0.1.0` (or
   `curl -sI https://ghcr.io/v2/vyomi-cloud/mcp-hosted/manifests/0.1.0` → `200`, not `401`).

Only then continue. If the component is added while the package is private, every deploy of the **whole portal
app** fails on an image pull, and App Platform rolls the app back.

### 0b. Add the component to the portal app (gate O-G2)

```sh
export PORTAL_APP_ID=<the portal's App Platform app id>      # doctl apps list
doctl apps spec get "$PORTAL_APP_ID" > /tmp/portal-app.yaml
cp /tmp/portal-app.yaml /tmp/portal-app.yaml.bak             # keep the pre-change spec

# Check first: prints what would change and which components are left alone.
python3 deploy/mcp-hosted/add-component.py /tmp/portal-app.yaml

# Then write it and apply.
python3 deploy/mcp-hosted/add-component.py /tmp/portal-app.yaml --apply
diff -u /tmp/portal-app.yaml.bak /tmp/portal-app.yaml        # read this diff before applying
doctl apps update "$PORTAL_APP_ID" --spec /tmp/portal-app.yaml
doctl apps get "$PORTAL_APP_ID" --format ActiveDeployment.Phase,InProgressDeployment.Phase
```

`add-component.py` adds or replaces **only** the `mcp` service and the `/mcp` ingress rule, refuses to write if
anything else would change, and puts the rule before the portal's catch-all (`prefix: "/"` matches everything, so
it has to stay last). Re-running it is a no-op.

### 0c. Let `/mcp*` through Cloudflare (gate O-G3)

`vyomi.cloud` sits behind Cloudflare. MCP clients (ChatGPT, claude.ai, Claude Code, Codex) are server-to-server:
no browser headers, no JS challenge. Add a rule that skips bot protection, managed challenges and rate limiting
for `vyomi.cloud/mcp*`, or they get a challenge page instead of JSON-RPC.

### 0d. Repository secrets

`DIGITALOCEAN_ACCESS_TOKEN` and `PORTAL_APP_ID`. **No registry secrets**: the image goes to GHCR with the
workflow's own `GITHUB_TOKEN` (`permissions: packages: write`).

---

## 1. Release

Push a `mcp-hosted-v<version>` tag (for example `mcp-hosted-v0.1.1`) from a `v4-on-main` commit whose guardrails
and Go tests are green. Tagging is the owner's call; nothing deploys on a merge.

`.github/workflows/mcp-hosted-release.yml` then: guardrails → `go test ./cmd/vyomi/...` → build and push
`ghcr.io/vyomi-cloud/mcp-hosted:0.1.1` (amd64) → fetch the portal spec, set **only** the `mcp` component's image
tag (`set-image-tag.py`), `doctl apps update --spec` → wait for the deployment → smoke
`https://vyomi.cloud/mcp`.

Changing a tool name, schema, description or annotation is a **contract change**: the directories re-review the
tool set (plan §7). Server-only fixes that keep the contract deploy freely.

## 2. Verify by hand

```sh
curl -s https://vyomi.cloud/mcp/healthz                 # {"ok":true,"version":"4.0.x","tools":8}
tools/mcp-hosted-smoke.sh https://vyomi.cloud/mcp       # every transport and limit case
curl -s https://vyomi.cloud/ -o /dev/null -w '%{http_code}\n'   # 200: the portal still answers
claude mcp add --transport http vyomi-hosted https://vyomi.cloud/mcp
```

## 3. Rollback

```sh
doctl apps spec get "$PORTAL_APP_ID" > /tmp/portal-app.yaml
python3 deploy/mcp-hosted/set-image-tag.py /tmp/portal-app.yaml 0.1.0   # the last good version
doctl apps update "$PORTAL_APP_ID" --spec /tmp/portal-app.yaml
```

The image tags stay in GHCR, so any previous version can be pinned again. A failed component rolls the whole app
back on its own, so a bad MCP image does not leave the portal down — but it does block the portal's deploy, so
roll the tag back rather than leaving it red.

## 4. If something is wrong

| Symptom | Likely cause | What to do |
|---|---|---|
| The whole app's deploy fails on an image pull | the GHCR package is private, or the tag does not exist | step 0a (visibility), or check the tag in the Packages tab |
| `/mcp` returns the portal's 404 page | the ingress rule is missing, or it is after the portal's `prefix: "/"` rule | re-run `add-component.py` (it inserts before the catch-all) |
| `POST /mcp` answers `301`/`308` | something is redirecting to `/mcp/` in front of the component | the Go server never redirects; look at the Cloudflare rules and the ingress rule's `preserve_path_prefix` |
| A challenge page instead of JSON | Cloudflare bot protection | gate O-G3 |
| `405` on `POST` | the client is sending `GET` (an SSE probe); or the request reached the portal, not this component | expected for `GET`: this server is stateless JSON, no SSE stream |
| `429` | the per-client rate limit (60/min, burst 20) or the 50 req/s process limit (D-I4) | read `Retry-After`; revisit the limits after a month of logs |
| Healthy container, no traffic | the health check path is not `/healthz`, or `http_port` is not 8080 | compare against `portal-app-component.yaml` |

## 5. Build and run it locally

```sh
docker build -f deploy/mcp-hosted/Dockerfile -t mcp-hosted:dev .
docker run --rm -p 8080:8080 mcp-hosted:dev
tools/mcp-hosted-smoke.sh http://localhost:8080/mcp
```

The image is distroless and non-root, with no shell: `docker exec` and `docker run ... sh` do not work by design.
Read the JSON request log with `docker logs`.
