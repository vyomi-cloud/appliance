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

1. Release tags are pushed by the owner (plan §9; the repo's pre-push hook refuses tags, so
   `git push --no-verify origin <tag>`). Each one builds, smoke-tests, pushes and deploys (§0b, §1).
2. Make a **pull token**: a GitHub **classic** personal access token with only `read:packages`, ideally on a
   machine/bot account that is a member of `vyomi-cloud` (so it does not die with a person's account). Note its
   expiry date in your calendar: an expired token makes every **portal** deploy fail on the image pull.
3. Optional: check the token can pull, without changing the package:
   `echo "$TOKEN" | docker login ghcr.io -u <github-user> --password-stdin && docker pull ghcr.io/vyomi-cloud/mcp-hosted:0.1.0`

Leave the package private. If it is ever made public, `add-component.py --public` drops the credentials.

### 0b. Let the pipeline add the component (gate O-G2)

The release workflow adds the `mcp` component itself; nobody needs `doctl` locally.

1. Store the pull token as a repository secret, typed at a hidden prompt:
   `gh secret set GHCR_PULL_CREDENTIALS --repo vyomi-cloud/appliance` and enter `<github-user>:<token>`.
2. Recommended: GitHub → repo **Settings → Environments → `production` → Required reviewers** → add yourself.
   Every deploy (including this first one, which changes the portal app's spec) then waits for your click.
3. Push the next release tag, for example `git push --no-verify origin mcp-hosted-v0.1.1`. The deploy job runs
   `add-component.py --tag <version> --apply` on the live spec: it adds the `mcp` service and the `/mcp` rule
   (before the portal's catch-all) with the credentials, refuses to write if anything else would change, prints the
   diff into the job summary without the credentials line, applies it and smoke-tests production.

App Platform stores the credentials encrypted (`EV[...]` in later spec reads). **Rotating the token**: update the
`GHCR_PULL_CREDENTIALS` secret; the next release re-applies it. Only the `mcp` component changes.

Manual fallback (the same script, by hand), for example when GitHub Actions is down:

```sh
export PORTAL_APP_ID=<the portal's App Platform app id>
doctl apps spec get "$PORTAL_APP_ID" > /tmp/portal-app.yaml && cp /tmp/portal-app.yaml /tmp/portal-app.yaml.bak
read -rs GHCR_TOKEN; export GHCR_PULL_CREDENTIALS="<github-user>:$GHCR_TOKEN"
python3 deploy/mcp-hosted/add-component.py /tmp/portal-app.yaml --tag <version> --apply
diff -u /tmp/portal-app.yaml.bak /tmp/portal-app.yaml | grep -v registry_credentials
doctl apps update "$PORTAL_APP_ID" --spec /tmp/portal-app.yaml --wait
rm -f /tmp/portal-app.yaml; unset GHCR_TOKEN GHCR_PULL_CREDENTIALS
```

### 0c. Let `/mcp*` through Cloudflare (gate O-G3)

`vyomi.cloud` sits behind Cloudflare. MCP clients (ChatGPT, claude.ai, Claude Code, Codex) are server-to-server:
no browser headers, no JS challenge. Add a rule that skips bot protection, managed challenges and rate limiting
for `vyomi.cloud/mcp*`, or they get a challenge page instead of JSON-RPC.

### 0d. Repository secrets

`DIGITALOCEAN_ACCESS_TOKEN`, `PORTAL_APP_ID` and `GHCR_PULL_CREDENTIALS` (the pull token, §0b). Pushing the image
needs no secret: the workflow uses its own `GITHUB_TOKEN` (`permissions: packages: write`).

---

## 1. Release

Push a `mcp-hosted-v<version>` tag (for example `mcp-hosted-v0.1.1`) from a `v4-on-main` commit whose guardrails
and Go tests are green. Tagging is the owner's call; nothing deploys on a merge.

`.github/workflows/mcp-hosted-release.yml` then: guardrails → `go test ./cmd/vyomi/...` → build and push
`ghcr.io/vyomi-cloud/mcp-hosted:0.1.1` (amd64, after a local smoke test) → fetch the portal spec, add or update
**only** the `mcp` component (`add-component.py --tag`, credentials from the secret), `doctl apps update --spec` →
wait for the deployment → smoke `https://vyomi.cloud/mcp` and check the portal still answers.

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
