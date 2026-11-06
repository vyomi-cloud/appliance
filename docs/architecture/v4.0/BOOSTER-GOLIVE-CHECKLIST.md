# Booster go-live checklist (what a human must do)

Everything below is code-complete against FAKES (fake GitHub, fake relay/booster). Nothing has run against real GitHub,
a real Codespace or a real wss:// relay. Design: `BOOSTER-CODESPACES-GITHUB-APP.md`.

## 1. GitHub App (once, on the `vyomi-cloud` org)
1. Register the production GitHub App "Vyomi Booster" (permissions in design doc section 2: Codespaces write, Codespaces lifecycle admin write,
   Metadata read; NO secrets access). Callback URL `https://vyomi.cloud/api/booster/github/callback`, "Request user authorization during
   installation" ON, user tokens expire ON.
2. **Install the App on the `vyomi-cloud` org (repo `vyomi-cloud/sandbox`) and answer open question #1:** with a personal account that is NOT a
   member, can the App user token `POST /repos/vyomi-cloud/sandbox/codespaces`?
   - Yes -> keep `BOOSTER_REPO_MODE=auto` (direct create; no copy made).
   - No (403) -> the portal automatically falls back to a per-user fork, then a template copy (`BOOSTER_REPO_MODE=auto`). Make the repo a GitHub
     template so the template path works, and confirm the App token may fork/generate (spike saw 403 on fork). If neither works the dashboard shows
     "Create your copy on GitHub" + a field to register it (`POST /api/booster/repo`): verify that manual path end to end.
3. Make sure `.devcontainer/booster/` (devcontainer.json + boot-booster.sh + docker-compose.booster.yml) is on the default branch of the repo
   the Codespace is created from. **`docker-compose.booster.yml` is referenced by boot-booster.sh; confirm it exists in `codespace/.devcontainer/booster/`
   before the first boot test.**

## 2. Portal env vars (DigitalOcean app)
`GITHUB_APP_CLIENT_ID`, `GITHUB_APP_CLIENT_SECRET`, `BOOSTER_TOKEN_KEY` (Fernet key for stored GitHub tokens; losing it forces everyone to reconnect),
`BOOSTER_SESSION_KEY` (session-token master key; the relay needs the SAME value as `VYOMI_BOOSTER_SESSION_KEY`), `BOOSTER_RELAY_URL`
(public `wss://.../booster`), optional `BOOSTER_REPO`, `BOOSTER_REPO_MODE` (auto|direct|fork), `PORTAL_BASE_URL`. Do NOT set `BOOSTER_WORKER=0` in prod
(it is the 8 h TTL / heartbeat / hours-limit enforcer).

## 3. Relay with TLS
Deploy the relay (`wasm/relay/local-relay.mjs`, booster hub enabled by the session key) behind wss:// termination. Set `VYOMI_RELAY_ORIGINS`
to the portal origins. Tested over ws:// only.

## 4. Real boot test (personal GitHub Free account, NOT vyomi-admin)
- [ ] Dashboard: Connect GitHub -> single install+authorise screen -> back on the dashboard, "GitHub: <login>".
- [ ] Start booster -> Codespace created on `basicLinux32gb` (2-core accepted by `hostRequirements`), status goes starting -> running (~2 min).
- [ ] boot-booster.sh fetches the token (`GET /api/booster/session/token`), posts `/api/booster/session/ready`, starts the outbound link.
- [ ] Nano (`/nano/clouds.html`): bottom-left chip shows "Booster connected - ends in 7h 5xm".
- [ ] A real EC2 RunInstances / Lambda / AI call from the Nano console reaches the booster (the compute classifier in `wasm/booster-link.js`
      `isComputeCall` is a HEURISTIC over SigV4 service scope + GCP/Azure paths; check it against real console traffic) and S3 stays in the browser.
- [ ] Stop booster -> Codespace Shutdown; hours ledger counts actual seconds.
- [ ] Close the dashboard tab for 5+ minutes -> auto-stop (heartbeat). Wait for 8 h (or shorten `MAX_SESSION` on a test deploy) -> TTL stop.
- [ ] Extend is refused (`POST /api/booster/extend` -> 409).
- [ ] Failure matrix: org-owned account (expect `org_no_free_quota`), exhausted quota (expect `quota_exhausted`; GitHub's exact wording is matched by
      substring in `map_github_error` and was NOT verified), revoked grant (expect reconnect prompt), Free-tier portal user (expect no booster).
- [ ] Check the Codespace is not left running and its storage is not growing (we never auto-delete; `POST /api/booster/delete` needs consent).

## 5. Open product decisions
Price/purchase flow, signed images, compute IAM, certs/hostname (design doc section 13 phases 3-4); amd64 build of `docker/booster-lang`;
how a repo copy is kept in sync (`merge-upstream` is called best-effort on reuse).

## 6. Not to do without the owner's say-so
Merge to `main`, tag, deploy the portal (each build costs money), publish images.
