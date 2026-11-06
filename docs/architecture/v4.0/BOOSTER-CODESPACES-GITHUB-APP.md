# Booster pack on the user's own Codespaces — GitHub App flow (handoff)

Status: **design + partial spike proof. Nothing is implemented.** Written 2026-11-06 for the session that
implements the flow. Nothing here touches v4 UI code; it only describes the launch/lifecycle plumbing.

## 1. Goal

Pro and Max licences include a **booster pack**: 40 h (Pro) / 60 h (Max) of remote compute per billing
cycle that runs **inside the user's own GitHub Codespaces** (their free quota, $0 to us).

Hard requirements from the product owner:

- **No PAT.** The user never pastes a token.
- **No download / install on the user's machine.** Everything starts from the vyomi.cloud dashboard.
- The user is **never redirected away** from vyomi.cloud to use it.
- **Headless**: the booster in the Codespace has no UI of its own. Nano (browser) is the only UI.
- **8-hour TTL on every start**: each time the booster starts it is brought down after 8 h.
- Pro/Max only (licence-gated). Nano-only users get none of this.

## 2. Why a GitHub App (not OAuth / not a PAT)

A classic OAuth app needs the `codespace` scope, which includes read access to the user's Codespaces
secrets — a consent screen that scares developers. A **GitHub App** has granular permissions:

| Permission (repository) | Level | Why |
|---|---|---|
| Codespaces | write | create Codespaces |
| Codespaces lifecycle admin | write | stop / delete (the user-level stop endpoint requires `codespaces_lifecycle_admin` for GitHub Apps) |
| Metadata | read | mandatory |
| Codespaces secrets / user secrets | **no access** | the whole point |

Manifest used in the spike (works as-is):

```json
{
  "name": "Vyomi Booster",
  "url": "https://vyomi.cloud",
  "redirect_url": "https://vyomi.cloud/api/booster/github/created",
  "callback_urls": ["https://vyomi.cloud/api/booster/github/callback"],
  "public": true,
  "request_oauth_on_install": true,
  "setup_on_update": false,
  "default_events": [],
  "default_permissions": {
    "codespaces": "write",
    "codespaces_lifecycle_admin": "write",
    "metadata": "read"
  }
}
```

`request_oauth_on_install: true` makes **install + authorise a single GitHub screen**. In production the
App is created once by us (not per user via manifest); the manifest above is just the permission set.

User tokens (user-to-server) **expire after 8 h and come with a refresh token** (verified in the spike:
`expires_in=28800`, `refresh_token` present). Store the refresh token **encrypted** (needed for the
portal-side stop/delete after the browser session is gone).

## 3. What the spike PROVED (2026-11-06, account `vyomi-admin`)

Throwaway App + local harness (see §9). All with a GitHub App user token, **no PAT**:

- Install + authorise → user token (8 h) + refresh token. ✅
- `GET /user`, `GET /user/installations`, `GET /user/installations/{id}/repositories`. ✅
- `POST /repos/{owner}/{repo}/codespaces` → **201**. ✅
  (`machine=standardLinux32gb`, `idle_timeout_minutes=5`, `devcontainer_path=.devcontainer/aws/devcontainer.json`)
- Poll `GET /user/codespaces/{name}` → `Available` after ≈ 2 min. ✅
- `POST /user/codespaces/{name}/stop` → 200. ✅
- `DELETE /user/codespaces/{name}` → 202, then GET → **404** (gone). ✅
- `api.github.com` sends `access-control-allow-origin: *` and allows POST/DELETE → the **dashboard JS can
  call the API directly from vyomi.cloud** (only the code→token exchange needs our client secret, server-side). ✅

## 4. What the spike found BLOCKING / unresolved

1. **403 "Resource not accessible by integration"** creating a Codespace on `vyomi-cloud/sandbox` (a repo the
   App is not installed on), and the same 403 forking it with the user token.
   → The Codespace must be created from a repo **in an account where the App is installed**.
   **Open question #1 (test first):** can the App token create directly on the public upstream repo with no
   fork? (GitHub's web "Open in Codespaces" auto-forks public repos; the API for an App token is UNTESTED —
   our App was not installed on `vyomi-cloud/sandbox` during the spike. Test by installing the App on the
   `vyomi-cloud` org and retrying.) If it works, no per-user fork is needed.
2. If it does not work, **one fork per user (once, reused for every launch)** is needed — NOT per Codespace
   and NOT one shared fork (the App only acts where it is installed, and a shared fork would put users on
   our repo/quota). Ways to get it: a one-time "create your copy" step, or make the repo a GitHub
   **template** (user creates their own copy in one click, no extra permission). Forks need syncing when
   `.devcontainer` changes.
3. **2-core is refused today**: `Machine 'basicLinux32gb' is not allowed for this repository` because the
   repo's devcontainers set `hostRequirements` (all-clouds: 8 cpu/16 gb/48 gb; aws & azure: 4/8/32;
   gcp: 4/16/40). 40–60 h only fits on **2-core** (see §5), so a **new lighter booster devcontainer is
   required** (§6.1).
4. Not tested: booster boot inside the Codespace, the readiness webhook, port/tunnel reachability, and any
   account other than `vyomi-admin`.

## 5. Quota & billing facts (docs.github.com/en/billing/concepts/product-billing/github-codespaces)

| Cores | $/hr | Quota multiplier |
|---|---|---|
| 2 | 0.18 | 2 |
| 4 | 0.36 | 4 |
| 8 | 0.72 | 8 |
| 16 | 1.44 | 16 |
| 32 | 2.88 | 32 |

- Personal accounts: **GitHub Free 120 core-hours + 15 GB-mo storage; Pro 180 + 20 GB-mo** per month.
  120 core-h ⇒ ≈ **60 h on 2-core, ≈ 30 h on 4-core** (the page doesn't state the multiplier math
  explicitly — treat as the working assumption).
- **Org/enterprise accounts get no free quota** → this flow is personal-account only.
- Storage $0.07/GB-mo, accrues hourly **while the Codespace exists** (stopped ≠ free). A persistent 32 GB
  Codespace burns the 15 GB-mo free storage in ≈ 2 weeks → **recreate per session; don't keep stopped
  Codespaces around** (delete only with the user's consent).
- **No credit card needed** for the free quota. Without a payment method usage is **blocked** when the quota
  is exhausted ("can no longer create or resume codespaces"). With a card, overage is billed to the user
  (subject to their budgets) → warn card-holders.
- Therefore our 40/60 h is a **ceiling on our side, not a guarantee**: if the user's GitHub quota is lower
  (other Codespaces use it too) GitHub blocks first. Surface a clear message. (No known API for remaining
  quota — verify before promising a meter.)
- Machine-name gotcha: GitHub's names are `basicLinux32gb` (2-core), `standardLinux32gb` (4-core),
  `premiumLinux` (8), `largePremiumLinux` (16), `xLargePremiumLinux` (32) — **verify against GitHub's
  machines endpoint** (`GET /repos/{o}/{r}/codespaces/machines`). Existing portal `app/sandbox_launch.py`
  maps S(8-core)→`standardLinux32gb`, which looks off by one; fix when touching it.

## 6. Target design

### 6.1 Booster devcontainer (new, light)

- New config e.g. `.devcontainer/booster/devcontainer.json` in the sandbox/template repo with
  `hostRequirements: {cpus: 2, memory: "8gb", storage: "32gb"}` and only the booster services
  (compute + AI engines). Cloud emulators stay in Nano.
- Pulls the **public booster image** from the registry on GitHub's machines (nothing on the user's box).
- `boot.sh` (reuse the existing script/pattern): on start, POST the readiness webhook to the portal
  (`/api/sandbox/status` style, two-tier readiness already exists), receive the **signed session token**
  (includes `session_end = start + 8h`, licence tier, user id).
- Create call: `machine=basicLinux32gb`, `idle_timeout_minutes=5`, `devcontainer_path=.devcontainer/booster/devcontainer.json`,
  optional `retention_period_minutes`.

### 6.2 Launch flow (dashboard → Codespace)

1. User (Pro/Max, signed in) clicks **Start booster**. If not connected: GitHub App install+authorise
   (one screen). Callback exchanges code→token server-side; store access + **encrypted** refresh token.
2. Portal checks licence tier + remaining hours; resolves the user's repo (see §4 fork question).
3. `POST /repos/{user}/{repo}/codespaces` (headless, from the portal or the dashboard JS with the user token).
4. Poll until `Available`; wait for the booster's readiness webhook; mark session `running`.
5. Nano connects through the private link (§6.4). User never leaves vyomi.cloud.

### 6.3 Lifecycle: 8-hour TTL + hours ledger

- **Every start gets a hard 8 h TTL** (`session_end = start + 8h`), enforced in three layers:
  1. **Portal timer (authoritative):** at `session_end` call `POST /user/codespaces/{name}/stop` using the
     stored refresh token (the 8 h user token expires at the same moment — refresh first).
  2. **Booster self-expiry:** `boot.sh` reads `session_end` from the token; at that time it stops serving and
     shuts the stack down. The Codespace can't stop itself, so it then goes idle and the
     `idle_timeout_minutes: 5` stops it (backstop only).
  3. **Dashboard:** live countdown, warning ≈ 15 min before the end, offer a fresh session.
- **Idle / tab-closed:** dashboard heartbeat (e.g. every 60 s). No heartbeat for 5 min ⇒ portal calls stop.
  GitHub's 5-min idle timeout is the independent backstop.
- **Hours ledger** (per user, per billing cycle): count **actual running time** (start→stop), NOT the 8 h
  reservation. Allowance from the signed licence: Pro 40 h / Max 60 h. GitHub has no webhook for Codespace
  state → record start/stop ourselves and reconcile by polling `GET /user/codespaces` for stragglers.
  40 h = five full 8 h sessions (Pro); 60 h = seven and a half (Max).
- **At the limit:** stop the Codespace; **ask before deleting** (deleting destroys the user's data in their own
  account). Recreate-per-session by default so storage doesn't eat their 15 GB-mo.
- Restart after a TTL ends = **new session**, same monthly allowance.

### 6.4 Headless + private link

- Booster has **no UI**; APIs only. Nano is the only UI.
- Recommended link: **outbound reverse tunnel** — the booster dials out over WSS to our relay with the
  signed session token; Nano and the user's local SDK/CLI connect to the same relay. **No inbound/public
  port on the Codespace**, access dies with the session TTL. The relay already exists inside the booster
  appliance and `vyomi-tunnel` is published (npm `vyomi-tunnel`, Homebrew tap) — mostly wiring. (See memory
  notes "Tunnel bundled in booster", "Booster scope".)
- Alternatives considered: GitHub **private** forwarded ports (GitHub-auth only, but browser cookie/CORS
  problems from vyomi.cloud — don't rely on it for Nano); a real VPN (WireGuard/Tailscale) needs a client on
  the user's device — optional power-user extra only, a browser can't create a VPN interface.
- **Do not** use a public forwarded port with a shell; if a public port is ever used it needs a per-session
  token + `Origin` allow-list for vyomi.cloud.
- An inline `xterm.js` terminal is **not** directly possible: there is no public WebSocket to attach to a
  Codespace bash session and the Codespace web page is not embeddable. If a terminal is wanted, run our own
  `ttyd`-style bridge in the Codespace behind the same tunnel + token.

## 7. Implementation checklist (suggested order)

1. **Test open question #1:** install the App on the `vyomi-cloud` org and try creating directly on
   `vyomi-cloud/sandbox` with the App token. Result decides fork vs. template vs. none.
2. Create the **2-core booster devcontainer**; prove it boots on `basicLinux32gb` (`GET .../codespaces/machines`
   to confirm the name; check `hostRequirements`).
3. Register the production **GitHub App** (permissions in §2). Add portal routes: `/api/booster/github/connect`,
   `.../callback` (exchange code→token server-side, store access+refresh encrypted), token refresh helper.
4. Portal: `Booster session` model (user, codespace_name, start, session_end, state, hours_used), licence
   claim for allowance (Pro 40 / Max 60), licence gate (Pro/Max only).
5. Launch/poll/stop/delete service using the GitHub REST endpoints in §3; readiness webhook handler;
   8 h TTL scheduler + heartbeat watcher + hours ledger + cycle reset.
6. Tunnel wiring: booster dials out with the session token; Nano connects via the relay; Origin/token checks.
7. Dashboard UI (v4 design): Connect GitHub, Start/Stop booster, countdown, hours remaining, clear errors
   (quota exhausted / no free quota on org accounts / card-on-file overage warning).
8. Test matrix: a different account than `vyomi-admin` (e.g. a plain personal account), org-owned account
   (expect no free quota), quota-exhausted account (expect GitHub block + our message), revoked refresh
   token (expect layer-2 backstop to stop it).

## 8. Risks / open items

- Direct creation on the upstream repo for an App token: **unknown** (blocking #1).
- 40–60 h only holds on GitHub **Free + 2-core**; 4-core halves it; org accounts get nothing.
- Stored refresh tokens = sensitive; encrypt at rest, never log, revoke on disconnect/licence end.
- Portal stop failing (revoked token) leaves only the idle-timeout backstop.
- A stopped Codespace still consumes storage quota → prefer delete-on-end with consent.
- App token fork returned 403 → don't plan on the portal creating forks for users.

## 9. Spike artefacts

- Harness (manifest → install/authorise → create → wait → stop → delete), stdlib Python, localhost:8765:
  `/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/56440f95-4078-4730-9852-08a9021227ad/scratchpad/ghapp/spike.py`
  (log: `.../ghapp/run.log`). Scratchpad paths are session-local and may disappear — copy if needed.
- Throwaway App `Vyomi Booster Spike` (slug `vyomi-booster-spike-a6d7`) exists on the `vyomi-admin` account —
  **delete it** in GitHub Settings → Developer settings → GitHub Apps. Its credentials file was deleted.
- One older Codespace `animated-garbanzo-gx4v494jpwwph9r6w` (Shutdown) is on `vyomi-admin`; not from the spike.
- Source docs: GitHub Codespaces billing page (above); REST "Stop a codespace for the authenticated user".

---

# Addendum (2026-11-06) — v4.0.0 compute model, tiers and what the booster carries

Decisions taken after the sections above were written. Design only; items marked **built** exist on
`v4-on-main`, everything else is not started.

## 10. Substrates and tiers (supersedes any Multipass/LXD wording above)

- **Multipass/LXD is retired.** v4.0.0 compute = **WASM Edge** (Nano, in the browser) + **Docker** (Pro/Max).
  Pending: stop building/publishing Multipass deb/rpm/MSI and the brew `vyomi` formula in `release.yml`;
  mark `cmd/vyomi/multipass.go` deprecated.
- **Pro vs Max differ only by clouds:** Pro = ALL services on **one chosen cloud**; Max = all three clouds.
  Free/Nano = in-browser. Enterprise is separate.
- **One-cloud rule — built** in three places that must agree:
  - appliance: `core/tier_policy` (`providers: "primary_cloud_only"`) + tier gate in `core/middleware.py`;
    Pro pins the first cloud it touches (`tenant["primary_cloud"]`), space-create returns
    `tier_provider_locked` / `tier_primary_cloud_unset`; licence claims also set `primary_cloud`.
  - booster/Nano: `wasm/booster-link.js` (`planCloud`, `cloudAllowed`, `pinCloud`), `clouds.html` gate,
    SW `/api/runtime/tier` `active_policy`.
  - portal: booster account record carries `clouds` + `primary_cloud`;
    `POST /api/account/booster/primary-cloud`.
  The booster must enforce the same rule server-side (a Pro session on cloud X rejects Y), not trust Nano.

## 11. What runs where

| Layer | Runs in | Holds |
|---|---|---|
| Nano (only UI) | user's browser | cloud emulators/consoles, WASM Edge toolchain (below) |
| Booster | user's Codespace (Docker) | heavy compute + AI + every language runtime; headless |
| Relay/tunnel | inside the booster appliance (**no separate vyomi-tunnel release**) | outbound WSS link, see §6.4 |

### 11.1 In-browser toolchain (all tiers) — built, behind a flag
- Only **git + Python** in the browser, plus a package manager: git (https clone), Python 3, **pip**, **apk**.
- v86 (32-bit x86 Alpine 3.21, rootfs in RAM), dropbear SSH over the tunnel `/vm` bridge, default **512 MB**
  (pip OOMs at 256). Flag `localStorage.nano_vm_compute="1"`, default **off** — flipping it on for all
  tiers is an open decision.
- Package access goes through the allow-listed egress proxy (`wasm/relay/egress.mjs`: alpinelinux, pypi/
  pythonhosted, github/gitlab, npm, maven, golang…); the guest speaks plain HTTP, the proxy upgrades to
  HTTPS. **Without the local tunnel the browser has no package access** — a hosted egress proxy is a
  portal/product decision, not made.

### 11.2 Booster language image — not started
- All other languages live in the booster, not the browser: **latest stable** of Java, Go, Node, Python,
  Rust, .NET, Ruby, PHP, C/C++ etc. 64-bit image (v86 is 32-bit only, so this cannot be the in-browser VM).
- Needs: pinned versions manifest + a refresh job, per-language smoke (hello-world build+run, package-manager
  install, a small web server reachable through the tunnel), image size budget so it pulls fast on the
  Codespace, and signed images (Phase 2).
- Fits the 2-core `basicLinux32gb` / 8 GB budget in §6.1; measure before promising concurrency.

## 12. Booster capacity and accounting (known gaps to close first)
- Instance memory is counted as a flat **1024 MB**; capacity check does **not reserve**; REST create paths
  and Azure VM updates are not pre-checked. Fix before the hours ledger (§6.3) is trusted.
- Allowance (Pro 40 h / Max 60 h) stays a ceiling; GitHub quota may block first (§5).

## 13. Phases
1. (built) tier/one-cloud gating, account link, Nano link, VM toolchain in Nano.
2. Open question #1 (§7.1), 2-core booster devcontainer, GitHub App, session model + 8 h TTL, readiness.
3. Language image + per-language smokes; signed images; compute IAM.
4. Certs/hostname, optional VPN extra, purchase flow + price, admin page for feedback.

## 14. Release interaction
- v4.0.0 is **not** cut until booster is finished (owner's call, 2026-11-06). Nothing is tagged, merged to
  `main`, deployed or published without an explicit prod-ready from the owner.
