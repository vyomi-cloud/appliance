# Hosted MCP: deploy runbook

The hosted Vyomi MCP server runs as the **`mcp` component of the portal's DigitalOcean App Platform app**, routed
at `vyomi.cloud/mcp` (D-H2 = B', `HOSTED-MCP-DESIGN.md` §5). It runs from a **pinned private image**,
`ghcr.io/vyomi-cloud/mcp-hosted:<version>`, `linux/amd64` only, so a portal deploy only re-pulls the same image
and an MCP build can never block a portal deploy.

**App Platform deploys all components together.** Bumping this component's image tag also redeploys the portal's
current `main` from its own source, and a failed component rolls the whole app back. That is the known trade-off
of B'. Deploy when the portal's `main` is in a state you are willing to ship.

Who can run this: whoever holds `DIGITALOCEAN_ACCESS_TOKEN` for the Vyomi team and can edit the portal app. The
one-time steps are owner gates (`HOSTED-MCP-IMPLEMENTATION-PLAN.md` §9, O-G2 and O-G3).

---

## 0. One-time, in this order

### 0a. Publish the image (it stays private)

The first release tag builds the image, smoke-tests it, then pushes `ghcr.io/vyomi-cloud/mcp-hosted:<version>`.
The GHCR package is **private** (decided 2026-11-23), so App Platform pulls it with credentials:

1. Push the first release tag, `mcp-hosted-v0.1.0` (owner's call, plan §9; the repo's pre-push hook refuses
   tags, so the owner pushes with `git push --no-verify origin <tag>`). The build, smoke and push succeed; the
   deploy job fails, which is expected on a first release, because the portal app has no `mcp` component yet.
2. Make a **pull token**: a GitHub **classic** personal access token with only `read:packages`, ideally on a
   machine/bot account that is a member of `vyomi-cloud` (so it does not die with a person's account). Note its
   expiry date in your calendar: an expired token makes every **portal** deploy fail on the image pull.
3. Check the token can pull, without changing the package:
   `echo "$TOKEN" | docker login ghcr.io -u <github-user> --password-stdin && docker pull ghcr.io/vyomi-cloud/mcp-hosted:0.1.0`

Leave the package private. If it is ever made public, `add-component.py --public` drops the credentials.

### 0b. Add the component to the portal app (gate O-G2)

```sh
export PORTAL_APP_ID=<the portal's App Platform app id>      # doctl apps list
doctl apps spec get "$PORTAL_APP_ID" > /tmp/portal-app.yaml
cp /tmp/portal-app.yaml /tmp/portal-app.yaml.bak             # keep the pre-change spec

# Check first: prints what would change and which components are left alone.
read -rs GHCR_TOKEN                                          # paste the pull token; it is not echoed
export GHCR_PULL_CREDENTIALS="<github-user>:$GHCR_TOKEN"
python3 deploy/mcp-hosted/add-component.py /tmp/portal-app.yaml

# Then write it and apply.
python3 deploy/mcp-hosted/add-component.py /tmp/portal-app.yaml --apply
diff -u /tmp/portal-app.yaml.bak /tmp/portal-app.yaml | grep -v registry_credentials   # read this; never paste the token
doctl apps update "$PORTAL_APP_ID" --spec /tmp/portal-app.yaml --wait
rm -f /tmp/portal-app.yaml; unset GHCR_TOKEN GHCR_PULL_CREDENTIALS     # the file held the token in plain text
doctl apps get "$PORTAL_APP_ID" --format ActiveDeployment.Phase,InProgressDeployment.Phase
```

`add-component.py` adds or replaces **only** the `mcp` service and the `/mcp` ingress rule, refuses to write if
anything else would change, and puts the rule before the portal's catch-all (`prefix: "/"` matches everything, so
it has to stay last). It never prints the token and writes the file mode 600. App Platform stores the credentials
encrypted: later `doctl apps spec get` shows `EV[...]`, which `add-component.py` (without the env) and
`set-image-tag.py` keep as they are, so re-running is a no-op and releases never need the token.

**Rotating the token** (before it expires): make a new one, then repeat 0b with `GHCR_PULL_CREDENTIALS` set to the
new value; only the `mcp` component's credentials change.

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
| The whole app's deploy fails on an image pull | the pull token expired or was revoked, or the tag does not exist | rotate the token (§0b), or check the tag in the Packages tab |
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
