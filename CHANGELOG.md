# Changelog

All notable changes to Vyomi will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.7] — 2026-06-20

**Bug-fix release dominated by a release-blocking fresh-install regression, plus a stack of fixes surfaced by actually running the appliance from a clean machine.** The headline: **every multipass-based install (brew/deb/rpm/scoop) has failed to launch since v2.0.3** because the source bundle omitted `packaging/` (whose init scripts the compose file bind-mounts) — Docker stubbed them as directories, the backing containers crash-looped, and the simulator never started. Docker-Compose installs and pre-2.0.3 upgrades were unaffected, which is why dogfood appliances never caught it. This release fixes that (and hardens the bundle check against the whole class), plus: the disk-cleanup 422, idempotent default-space self-heal, live launcher cold-start progress, Azure VM create UX, Azure VM SSH connect, LXD stop→start recovery, and a swallowed-error fix. Most of these predate v2.0.6 (verified by `git diff`); none was caused by the v2.0.6 upgrade itself.

### Fixed

- **Disk cleanup on the `/clouds` workspaces page returned HTTP 422** — the "Free up selected" action posted `{ ids: [...] }` to `POST /api/runtime/disk-cleanup/run`, but the backend `_DiskCleanupRequest` required a field named `categories`, so every cleanup request failed Pydantic validation with a 422. Worse, the SPA derived each checkbox's value from `it.id || it.path || label` — but suggestion items are keyed by `key` (`terminated_workspaces`, `tmp_and_apt`, `lxd_orphans`, `journald`, `lxd_image_cache`), so even a renamed field would have sent human-readable labels that match no category. Fixed on both sides: `static/clouds.html` now reads `it.key` for the checkbox value and posts `{ categories: ids }`; `_DiskCleanupRequest` now accepts `categories` (canonical) **and** a legacy `ids` alias, both defaulting to `[]`, so a missing/renamed field is an empty no-op instead of a 422. The handler merges `req.categories or req.ids`.

- **Fresh installs broken since v2.0.3 — the appliance never finished launching (release-blocking).** Every multipass-based install path (brew, deb, rpm, scoop) failed on first `vyomi up`: the launcher's source bundle (`scripts/cloud-learn` `required` list) omitted `packaging/`, but `docker-compose.appliance.yml` bind-mounts `packaging/{firestore,vault,elasticmq}/*` init files at runtime. Docker therefore created the missing mount sources as empty **directories** → firestore/vault/elasticmq crash-looped (`exit 126: Is a directory`) → the simulator `depends_on` them and never started → the health check timed out → "APPLIANCE LAUNCH FAILED." Fixed by adding `packaging` to the launcher bundle, to the **deb/rpm build scripts** (`build-deb.sh`, `cloud-learn.spec` — which also still omitted `routes`/`setup_cython.py`/`cloudsim-backbone`), and by extending **`scripts/verify-bundle.sh`** to assert every compose bind-mount source is bundled (not just Dockerfile `COPY`s), so this class fails CI instead of a user's first boot. Same recurring bug class as the `routes`/`setup_cython.py` omissions in v1.0.0–v1.1.9.
- **Launcher showed multipass's blank "Waiting for initialization" spinner during cold start.** `multipass launch` ran in the foreground, so its detail-free spinner sat for the 3–5 min LXD-snap-install cloud-init while the launcher's own progress poller only ran *afterward*. New `appliance_launch_and_track` runs the launch in the background and streams live cloud-init progress (`[48s] Installing LXD container runtime…`) with a 30 s liveness heartbeat, and reaps a failed launch with its output instead of marching to the 10-min bail-out.
- **Azure VM "Review + create" went silent and the new instance needed a hard refresh.** In `static/azure-console.html` the Create button was silently `disabled` on any validation error (no feedback) and `submitWizard` had no `try/catch`. Now Create is always clickable and jumps to the first errored step with a toast; submit shows "Creating…", closes the blade immediately, re-fetches the list (no hard refresh needed), and toasts on any error instead of leaving a dead pane.
- **Azure VM SSH connect was half-wired — "no SSH command", couldn't connect.** `core/vm_connect.connect_info()` does the lazy SSH provisioning (key injection + lxc proxy) given a flat instance dict, but Azure VMs are ARM records that keep `container_name`/`state` under `properties.runtime`, so the connect path 409'd before provisioning anything (AWS/GCP pass a flat dict and worked). `_connect_info_response` now flattens the Azure record so it reaches the same path, and the Connect modal renders a real, copyable `ssh -i ~/.ssh/vyomi_ed25519 -p <port> ubuntu@<host>` command — parity with AWS/GCP. (The LXD instance was always attached; only the SSH wiring + modal were incomplete.)
- **LXD instance `stop` → `start` failed with "Missing source path … for disk workspace".** LXD validates disk-device sources at start time, and an instance's workspace deployment dir could be removed while it was stopped (terminated-workspace reaper / disk-cleanup / a simulator restart), so `lxc start` 503'd. `_start_lxd_instance` now recreates the workspace host dir (`_ensure_lxd_workspace_host_dir`) before starting, making stop→start always recoverable for EC2/GCE/Azure VMs.
- **Azure VM provisioning errors were silently swallowed.** `core/azure_dataplane.py` wrapped the LXD provisioning in `except Exception: pass`. It now records `status: provision_error` + the message on the VM record, so a real provisioning failure surfaces instead of looking like a silent metadata-only VM.
- **RDS databases weren't isolated per space on the shared engine — cross-space data clobber.** AWS RDS provisioning (`_rds_real_provision`/`_rds_real_deprovision`) named the physical database from the raw `db_instance_identifier` and the login role from the verbatim `master_username`, with **no space namespacing** — unlike Cloud SQL + Azure DB, which already namespace via `gcp_sql_engine.physical_name(space_id, …)`. Because all three clouds back onto the *same* `cloudlearn-sql-postgres` container, two spaces (or two users following the same tutorial) creating an RDS named `mydb` with master user `admin` collided: `CREATE DATABASE` was skipped (already exists) so the second space silently connected to the **first space's database**, and `ALTER ROLE "admin" WITH PASSWORD` ran unconditionally, **resetting the shared role's password**. RDS now namespaces the physical db + role per space exactly like Cloud SQL — verified live (same `db_instance_identifier`/`master_username` in two spaces → two isolated physical DBs `cl_sharedname_cdad9b3d` vs `cl_sharedname_f7c78009`). The boto3-visible `MasterUsername`/`DBInstanceIdentifier` stay verbatim (SDK conformance preserved); the *connectable* physical creds are surfaced in the RDS view's new `connection` block — parity with Cloud SQL's `connectionInfo`. The data-plane conformance tests (`tests/conformance/ui/aws/test_rds_{postgres,mysql}.py`) now connect with that `connection` block instead of the verbatim master username. Found while validating real app+DB deploys across AWS/GCP/Azure (the portal-as-real-app smoke test).
- **Paste-a-key license activation never worked in appliance mode — every real portal JWT was rejected.** `POST /api/license/activate` had two handlers for the same path: the correct RS256 one in `server.py` (`req.license_key` → `_apply_license_jwt()`), and a legacy HMAC one in `routes/licensing.py` (`payload["token"]` → `_verify_license()`). The licensing-route module registers before `server.py`'s `@app.post`, so the **legacy handler won** — and it (a) read the wrong field name (`token`, while the pricing.html "Activate" modal posts `license_key`), (b) verified with the local HMAC scheme instead of RS256, and (c) gated the call behind `require_admin_key`, which the end-user UI never sends. A pasted portal JWT therefore failed with `401 Invalid license token: not enough values to unpack (expected 2, got 1)` (empty `token` → one-part split). Rewrote the live `routes/licensing.py` handler to: accept `license_key` (and `token` for back-compat); route on segment count (a portal JWT has two dots → `_apply_license_jwt()` RS256 verify + apply, returning `active_tier`/`issued_to`/`jti` as the SPA expects; a one-dot legacy HMAC token → the old path, still `require_admin_key`-gated since those are locally forgeable); and drop the admin-key requirement for the JWT path — the RS256 signature + `install_id` binding is the auth boundary, identical to the ungated device-flow path (`/api/auth/poll-activation`). Malformed input now returns a clean `400 license_key_required` / `401 license_invalid` (with `detail.reason`) instead of a 500, so the modal shows a real error.

### Added

- **Idempotent default-space self-heal** — `core/app_context.py` previously seeded the `aws-default` / `gcp-default` / `azure-default` spaces only inside the `if not spaces_state["spaces"]:` fresh-install guard, so any install created before the v1.2.5 multi-default seeding (which only ever had the legacy AWS space) never gained the GCP/Azure defaults — not even across upgrades. The GCP/Azure ensure now runs on every init, guarded by **provider presence** (skips if a space for that provider already exists), so pre-v1.2.5 single-space installs get all three consoles after upgrading without duplicating any space the user (or an API re-seed) already created.
- **Standard host-reachability for every VM.** New `_ensure_lxd_host_proxy`, called from `_start_lxd_instance` (so EC2/GCE/Azure all inherit it), creates an LXD proxy device forwarding the instance's allocated host port → the VM's app port — making every new VM reachable from the host (and the user's machine) at `http://<host>:<host_port>`, not just SSH. App port defaults to `80`, overridable per instance via `instance['app_port']` or env `CLOUDLEARN_LXD_VM_APP_PORT`; the reachable port is surfaced as `instance['host_app_port']`. Recreated on every start (survives container recreation). Also added `_ensure_lxd_workspace_host_dir` (called before `lxc start`) so a stopped instance whose deployment dir was reaped can always restart.

### Notes

- **Neither issue was caused by upgrading to v2.0.6.** The disk-cleanup code is byte-identical between v2.0.4.1 and v2.0.6 (the inner-validation appliance on 2.0.4.1 reproduces the same 422 live), and the default-space seeding logic is unchanged since v1.2.5. The differences observed between an inner (fresh-built) and outer (long-lived) appliance were a pre-existing bug exposed by exercising it, and an old-state artifact — not a release regression.
- Existing appliances missing the GCP/Azure defaults are self-healed on the next restart once running ≥2.0.7; before that, they can be re-seeded via the `+ Create Space` button (or `POST /api/spaces`).
- **Validated end-to-end with a real app + DB on all three clouds.** Using the portal itself as the test application (it needs a VM + Postgres), we provisioned managed Postgres (RDS / Cloud SQL / Azure SQL) + a compute VM (EC2 / GCE / Azure VM) on each cloud, deployed the portal onto the VM pointed at the managed DB, and confirmed it created its full schema over the wire — proving the Azure VM now attaches a real LXD container (the gap this release fixes) and that the host-reachability proxy works on every provider. This smoke test is what surfaced the RDS cross-space isolation bug above.

### Design & exploration (docs + spike only — no runtime impact)

This release also lands the design work from a long architecture session. **None of
the below changes appliance behaviour** — they are documents under `docs/browser-lite/`
and a throwaway proof under `spikes/`. Captured here so the decisions survive.

- **LXD → Docker compute, de-risked by a passing spike** — `spikes/docker-instance/`
  (`backend.py` = a `ComputeBackend` seam + `DockerComputeBackend`; `run_spike.sh`;
  `Dockerfile.instance`; `README.md`). Ran end-to-end on the OUTER appliance VM
  (aarch64, Docker 29.1.3): create → boot (inner dockerd 16s) → shell → **docker-in-
  instance (DinD)** → persistence across stop/start → status/IP → terminate, all green.
  Finding: VM semantics are tractable on Docker (no systemd needed — `tini`+sshd+dockerd);
  the one real cost is `--privileged` for DinD. Direction: replace the ~45 `_lxd_*` /
  `_multipass_*` functions + `core/runtime_bridge.py` with a Docker `ComputeBackend`.
- **Vyomi Lite — full browser architecture** — `docs/browser-lite/ARCHITECTURE.md`
  (master) plus `VYOMI-LITE-DESIGN.md`, `VYOMI-LITE-MASTER-SPEC.md`, `IN-MEMORY-PLAN.md`.
  A browser-native edition where `server.py` runs in **Pyodide**, every backing
  container is replaced by an in-memory/WASM engine (PGlite · moto · cedar-wasm ·
  WebCrypto · BlobEngine+OPFS · in-proc pub/sub/queue/event), the SPA is served via a
  **service-worker fetch⇄ASGI shim**, and state persists to OPFS/IndexedDB.
- **Networking as a fractal** — tab = host, browser = Availability Zone (same-origin
  tabs share a SharedWorker hub enforcing VPC security groups over **tcpip.js** real
  TCP), federated browsers = VPC/region (WebRTC/overlay, e.g. Tailscale-wasm),
  devices = multi-region. Two tabs of WASM emulators form a real, SG-enforced VPC.
- **Compute backends** — `ProviderFacade → InstanceManager (budget/quota) →
  RuntimeBackend`: Simulated · Pyodide(Py) · WebContainers/BrowserPod(Node) ·
  CheerpJ(Java) · Container2Wasm(any image) · RemoteDocker(real host). Per-language
  WASM matrix documented (§4a). **Decision: integrate runtimes, do not build a
  Docker-in-WASM kernel** — moat stays in conformance + airgapped, not the runtime.
- **CloudSim in the browser** — keep the real engine via **CheerpJ** (`CloudSimBackend`
  with `CheerpJBackend`; gated on CheerpJ Java-17 support, since CloudSim Plus 8.5.7
  needs Java 17), or default to the existing Python `local-fallback`.
- **Product & licensing model** — **Vyomi Lite (B2C, browser, single-tenant)** vs
  **Vyomi Enterprise (B2B, real compute, airgapped)** as two backends of one codebase
  (`VYOMI_BACKEND` flag). **One emulator = one appliance = one browser profile = one
  tenant = one license seat**, bound by a **WebCrypto non-extractable keypair**
  (extends `core/license_remote.py`); seat enforcement is server-side. Free tier =
  anonymous simulation-only, with a **sign-in 30-day real-compute trial → simulation-
  only** (account-anchored, server-enforced). Multi-tenant = multiple peered appliances
  (browser-as-tenant).
- **MVP scope** — AWS-only, single-tenant: **S3 (OPFS) · DynamoDB (moto) · IAM
  (cedar-wasm)** core; SQS · RDS (PGlite) · minimal EC2 compute as stretch; the other 8
  AWS services + GCP/Azure + SDN + multi-AZ deferred. ~16 weeks / 2–3 engineers, with a
  week-2 GO/NO-GO gate on the Pyodide + fetch⇄ASGI shell spike. Conformance measured by
  running the existing 35/35 harness against the Lite build.

## [2.0.6] — 2026-06-19

**Real-SPA conformance 35/35, install-funnel phone-home from every install path, Docker Hub metadata rebranded to Vyomi, Azure detail blade gets a wide-view modal, and a 7.5× longer launch timeout that finally lets cold-host LXD spawns complete.** v2.0.6 is the polish-and-instrumentation release before we open the gates on the Founding 1000 promo: we can now actually see who installs, from which channel, in which country, and watch them traverse `DOWNLOADED → INSTALLED → ACTIVATED` on a globe. Plus a stack of UX fixes (S3 Upload button, Azure Connect modal, blade-expand toggle) and a buried 120-second timeout that was silently demoting every cold-host VM to metadata-only.

### Added

- **Install-funnel phone-home from every package manager** — `packaging/common/phone-home.{sh,ps1}` fires a single anonymous POST to `https://vyomi.cloud/api/install/register` on `brew install` / `apt install` / `dnf install` / `scoop install`. Payload is `{install_id, version, host_os, channel, state: "DOWNLOADED"}`; install_id is a 16-char random hex persisted at `$HOME/.vyomi/install_id` (or `%LOCALAPPDATA%\Vyomi\install_id` on Windows). Wired into `packaging/homebrew/Formula/vyomi.rb` post_install, `packaging/debian/postinst.sh`, `packaging/rpm/cloud-learn.spec %post`, and `packaging/scoop/vyomi.json` post_install array. Opt-out via `VYOMI_NO_TELEMETRY=1` (also honors `HOMEBREW_NO_ANALYTICS`). Closes the funnel that previously only started at "user booted the appliance".
- **Upgrade-continuity probe** — before generating a fresh random id, the phone-home script probes `http://vyomi.local:9000/api/runtime/install-id` (new endpoint) and adopts the existing appliance's install_id. This keeps the portal's funnel row continuous when a v2.0.5 user upgrades via `brew upgrade vyomi`. Belt-and-suspenders: `scripts/cloud-learn` also backfills `~/.vyomi/install_id` after a successful `vyomi up` if the file is missing.
- **`VYOMI_INSTALL_ID` env propagation** — `core/license_remote.get_or_create_install_id()` now adopts a pre-issued install_id from the env (forwarded by the CLI launcher from the host marker file) before falling back to the existing SHA-256-of-hostname derivation. Means the same row in the portal funnel traverses `DOWNLOADED → INSTALLED → ACTIVATED` end-to-end.
- **`GET /api/runtime/install-id`** — new read-only endpoint in `routes/runtime.py` returning the appliance's stable install identifier. Consumed by the upgrade-continuity probe + the CLI's post-`up` backfill.
- **`GET /api/runtime/version`** + **`GET /api/runtime/update-check`** — version reporting + GitHub-tag-based update-availability check (15-min cache, opt-out via `CLOUDLEARN_UPDATE_CHECK_DISABLED=1`). Surfaces the v2.0.6-available banner on the SPA when a newer release is out.
- **`vyomi upgrade` CLI** — `scripts/cloud-learn upgrade` pulls the new image, recreates the simulator container, and waits for healthz. Designed to be safe to run from inside the running appliance.
- **Public install stats endpoint** — `portal/app/installs.py::public_install_stats()` exposes `{total, active, downloaded, installed, activated, by_state, by_channel, by_country}` at `GET /api/stats/installs`. Country aggregation uses `_COUNTRY_META` (60 country centroids baked in-module). Powers the marketing globe.
- **Animated install globe + 4-row funnel stat card on portal home** — `portal/app/templates/home.html` gets a new section right below the Distribution stats. Stat card shows `Downloaded → Installed → Activated → Countries`; companion `globe.gl` widget (lazy-loaded ~250 KB from unpkg) renders pulsing green dots sized by per-country install count, slow auto-rotate, atmospheric glow. Refreshes every 60 s. Fail-soft: country pills below still tell the story if the globe lib doesn't load.
- **`channel` attribution** — `ApplianceInstall.channel` column + `_VALID_CHANNELS = {brew, deb, rpm, scoop, docker, tarball}`. First-time channel wins (channel-lock) so a user who deb-installed then later docker-pull'd keeps the original deb attribution. Surfaces in `/api/stats/installs by_channel` for funnel reporting.
- **GitHub community CTA on launch page** — new dropdown pill (Star count from `/repos/vyomi-cloud/appliance` live, sessionStorage-cached 10 min) → Watch releases / Discussions / Source / Issues / Contributing. `POST /api/runtime/community-click` tracks clicks with a 7-day sliding window for marketing visibility.
- **ASCII brand banner** — `print_brand_banner()` in `scripts/cloud-learn` prints the cyan VYOMI block on every `up`/`down`/`restart`/`upgrade`. Idempotent via `_VYOMI_BANNER_PRINTED`, suppressible via `VYOMI_NO_BANNER=1`.
- **Azure VM Connect "Expand" toggle** — detail blade now opens at 880 px (was 560), and the new top-right pill toggles to a centered 92 vw × 92 vh modal dialog with rounded corners and a darker scrim for inspecting long Resource IDs / property bags. Preference persisted via `localStorage["vyomi.azure.subnav.collapsed"]`.

### Fixed

- **35/35 (100%) real-SPA Playwright conformance** — closed the 2 remaining gaps from v2.0.5: `providers/gcp_services.py` got 4 firestore database CRUD handlers (api_gcp_firestore_list_databases, create, get, delete) returning the Google-shape `{name, uid, createTime, locationId, type, ...}` envelope, with 8 new route tuples in `providers/gcp_routes.py` (4 verbs × 2 path aliases). `routes/aws_extras.py` POST now write-throughs Alias→alias column, auto-generates `key_id` from `secrets.token_hex(4)`, and sorts items newest-first by `created`.
- **LXD launch timeout silently demoting cold-host VMs to metadata-only** — root cause of the long-standing "no runtime container backing" error on EC2 / GCE / Azure VMs after a fresh appliance install. `_ensure_container` in `server.py` was passing `timeout=120` to `_lxd_run_checked(["launch", "ubuntu:24.04", ...])`. On a cold host that has to download the ~150 MB image from `images.linuxcontainers.org`, 120 s is short by 2–4 minutes. Bumped to **900 s** for LXD and **1200 s** for multipass, both env-tunable via `CLOUDLEARN_LXD_LAUNCH_TIMEOUT` / `CLOUDLEARN_MULTIPASS_LAUNCH_TIMEOUT`. Subsequent launches still finish in <10 s because the image is cached locally. Existing failed-state VMs get healed by clicking Restart in the action toolbar.
- **AWS S3 Upload button was missing entirely** — the Objects tab in `static/aws-console.html` showed the list but had no upload affordance. Added a primary `Upload` button + secondary `Refresh` at the top of the tab; clicking Upload opens the native multi-select file picker, each file POSTs as `multipart/form-data` to `/api/s3/buckets/{name}/objects` (the wire-compatible endpoint that boto3 + `aws s3 cp` already hit), per-file progress in the status text, auto-refresh on completion. Empty buckets now show "Click Upload above" hint instead of just "This bucket is empty".
- **Azure VM Connect modal showed bare red error for the common metadata-only case** — when LXD/multipass isn't reachable, the modal used to dump "This VM has no runtime container backing (metadata-only). To get an SSH/shell target, run the simulator with LXD or multipass on the host and the runtime bridge active." Replaced with a 4-section info layout: amber status banner, VM details as wrap-friendly chips (`Status: Running`, `Size: Standard_B1s`, etc), SSH command preview, and a blue upgrade-path tip linking to docs. New CSS classes `.cnx-banner / .cnx-card / .cnx-chip / .cnx-action / .cnx-tip`. Modal widened 560 → 760 px with explicit `display: flex; flex-direction: column` on the body to prevent layout regressions.
- **Azure detail blade was wrapping property values mid-character** — root cause was the blade itself being only 560 px wide; sub-nav (230 px) + Essentials key column (200 px) left only ~110 px for values like Resource IDs. Bumped default blade width to 880 (matches real Azure portal proportions), reduced essentials key column 200 → 140 px and prop-kv key column 280 → 200, swapped `word-break: break-all` for `overflow-wrap: anywhere` with proper `minmax(0, 1fr)` grid tracks, added `min-width: 0` everywhere a 1fr blowout was possible. Per-character vertical strips gone.

### Changed

- **Docker Hub metadata rebranded to Vyomi** — `Dockerfile` OCI labels: title "Vyomi Appliance", vendor "Vyomi", authors `support@vyomi.cloud`, url `https://vyomi.cloud`, source `github.com/vyomi-cloud/appliance`, documentation `vyomi.cloud/docs`, licenses `BUSL-1.1` (was incorrectly `MIT`). `docs/DOCKERHUB.md` rewritten end-to-end for the Hub repo Overview page with vyomi-cloud install paths, BSL 1.1 mentioned, support@vyomi.cloud throughout. The `peter-evans/dockerhub-description@v4` step in `.github/workflows/docker-publish.yml` pushes the new README to Hub on the next stable tag.
- **RPM spec changelog + maintainer email** — `packaging/rpm/cloud-learn.spec` gets a v2.0.6 entry; historical v1.0.0 entry's `CloudLearn <support@cloudlearn.io>` corrected to `Vyomi <support@vyomi.cloud>`.
- **README.md + CHANGELOG.md GitHub URLs** — install snippets and reference links migrated from `cloudlearn/cloud-learn` to `vyomi-cloud/appliance`. Historical v1.0 release notes left as-is.
- **License JWT sidecar persists across `docker compose down/up`** — `/data/license-backup.{jwt,json}` survives container restarts; FastAPI startup hook restores tier from sidecar. License-activation path also POSTs an ACTIVATED phone-home update bypassing the 24 h throttle.

### Notes

- **Existing v2.0.5 users upgrading via `brew upgrade vyomi`**: the phone-home probe automatically picks up your existing appliance's install_id from `/api/runtime/install-id` so your funnel row stays continuous. If the appliance isn't running during the upgrade, a fresh random id is generated and the first subsequent `vyomi up` backfills `~/.vyomi/install_id` from the simulator's STATE.
- **Existing VMs in `launch_failed` state**: click Restart in the action toolbar after upgrading to v2.0.6. The bumped timeout will let the previously-aborted image fetch complete.
- **`gansudkum/cloud-learn` Docker Hub repo**: unchanged in v2.0.6. New images publish only to `vyomi/appliance` and `ghcr.io/vyomi-cloud/appliance` per the docker-publish workflow.

## [2.0.5] — 2026-06-18

**Real-SPA conformance lands at 33/35 + cloud CLIs bundled into every spinned compute.** v2.0.5 closes the v2.0.4 framework gaps in the Playwright real-SPA harness (45.7% → 94.3% pass rate, 0 failures) and ships a quality-of-life feature for anyone who SSHes into a Vyomi-spawned EC2 / GCE / Azure VM: the 3 cloud-vendor CLIs are now pre-installed and pre-configured to point at the local simulator endpoints with dummy credentials, so `aws s3 ls`, `gcloud compute instances list`, and `az vm list` all work the moment you `ssh ubuntu@<vm>`. Also includes the cosmetic palette refresh and a Dockerfile fix for the `/var/lib/cloudlearn` permissions footgun.

### Added

- **`aws` / `gcloud` / `az` bundled into every spinned compute** — `_lxd_clouds_clis_bootstrap_async` in server.py runs alongside the existing docker bootstrap on first VM start. Installs AWS CLI v2 (curl + unzip), gcloud (apt repo), and azure-cli (apt repo). Writes `/etc/profile.d/vyomi-cloud-endpoints.sh` system-wide with `AWS_ENDPOINT_URL`, `CLOUDSDK_API_ENDPOINT_OVERRIDES_*`, dummy AKID/secret/project, and `CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true`. Same code-path covers all three providers (EC2 / GCE / Azure VM) because they all flow through `_start_lxd_instance`. Instance dict surfaces `clouds_clis_bootstrap_state` (`"installing"` / `"ready: <versions>"` / `"failed: <err>"`) so the SPA can show progress. Opt-out via `VYOMI_LXD_NO_CLI_BOOTSTRAP=1`. Verified end-to-end on a real LXD spawn: aws-cli/2.35.7, Google Cloud SDK 573.0.0, azure-cli 2.87.0. Bootstrap takes ~4 minutes on a t3.small first-boot.
- **Hardened bootstrap script** — waits for `dpkg lock-frontend` + `dpkg lock` + `apt lists/lock` (not just dpkg) so cloud-init / unattended-upgrades races don't silently drop packages. Sets `DPkg::Lock::Timeout=300` so apt itself retries on contention. Fail-fast verification step (`for bin in curl unzip gpg; do command -v $bin || exit 90`) surfaces specific missing packages instead of reporting an opaque `aws=MISSING` 5 minutes later. ubuntu:24.04-safe package list (dropped python3-pip which was removed from the default repos and used to roll back the whole apt transaction).
- **`VYOMI_RUNTIME_BRIDGE_DISABLED` env kill-switch** — `core/vyomi_platform.py::bridge_enabled()` honors the new env so `_lxd_available()` falls through to the local `lxc` CLI when the bridge service isn't reachable. Used by the Vyomi-on-Vyomi dev-loop where `host.docker.internal:9171` resolves to the wrong gateway. Legacy `CLOUDLEARN_RUNTIME_BRIDGE_DISABLED` also honored.

### Fixed

- **Real-SPA conformance harness goes from 16/35 to 33/35 (94.3%) and 0 failures** — 5 framework fixes in `tests/conformance/ui_real/_spa_helpers.py`:
  - GCP service-list nav: original `wait_for_selector(".count")` matched a `<span class=count>` that GCP renders empty + hidden, causing all 9 GCP services to skip with a "not visible" timeout. Now waits for `.page-head h1` / `h1.page-h` / `.actions-bar button.primary` instead.
  - Azure wizard field fill: the helper only looked inside `.field` containers, but Azure uses `.wiz-field`. Adding `.wiz-field:has(label:has-text("X")) input` to the candidate list made the 7 Azure services that previously fell through with default values (e.g. VM name stayed "vm-demo") fill correctly.
  - Azure stepper-based wizard nav: replaced the Next-click chain (which raced the wizard's rerender DOM swap) with direct stepper-button clicks. `gotoTab()` still validates every tab, so submit gating still respects required-field rules.
  - Required `__*` synthetic fields now get filled instead of skipped — fixes the GCP API Gateway `__serviceAccount__` validation block.
  - `make_value()` now returns a sensible text default for `type=None` and recognises email/serviceAccount-shaped names so GCP service-account fields pass their format checks.
- **EC2 spawn permission denied on `/var/lib/cloudlearn/deployments/<id>`** — `Dockerfile` now creates `/var/lib/cloudlearn/deployments` and chowns it to the `cloudlearn` user (uid 100) alongside `/data` and `/app`. Without this, the simulator (running as non-root) couldn't create the per-instance workspace dir and EC2 creates returned 500.
- **2 v2.1-tracked backend gaps explicitly skipped** — `aws.kms` (extras POST returns 200 but the keys list stays empty — needs write-through fix in the extras store) and `gcp.firestore` (catalog declares `/databases` collection endpoint but providers/gcp_routes.py only wires `/databases/{database}/*` document routes). Tracked as v2.1 follow-ups via the `SERVICE_SKIPS` dict.

### Changed

- **Splash + workspaces + pricing palette refresh** — `static/clouds.html` and `static/pricing.html` move to a calmer `#f8f9fa` page background, consolidate the prior `#0f1b2d` / `#1a2330` / `#2563eb` accents to `#1f2937` (gray-800), and update the splash overlay from the gradient to flat `#f8f9fa`. Provider donut palette swaps to a black→gray ramp (AWS `#1f2937`, GCP `#6b7280`, Azure `#d1d5db`) for a more print-friendly look.

## [2.0.4.1] — 2026-06-18

**Hot-fix patch on top of v2.0.4.** Two UX bugs surfaced within hours of cutting v2.0.4; this 4-segment patch ships them without bumping the minor version (since the underlying behaviour is unchanged).

### Fixed

- **Cloud-locked space click now shows a modal, not a silent redirect** — clicking a GCP/Azure space card while on the Pro tier (`primary_cloud_only`) used to 302-redirect to `/console/<primary>?denied=<provider>`, which whisked the user to a different cloud's console with cryptic query params. `static/clouds.html` now pre-checks the tier policy via `/api/runtime/tier` and surfaces a clear modal: "Not enabled for your current subscription" + plan context + Upgrade CTA. Server-side gate at `routes/console.py` is unchanged (defence-in-depth).
- **"✓ Current Plan" badge centered on the tier card** — `.tier.active::before` used `right: 16px` which right-aligned the badge above the highlighted tier card. Now uses `left: 50%; transform: translateX(-50%);` so it sits dead-centre over the card.

### Release pipeline

- `release.yml` + `docker-publish.yml` tag filters extended to also match `v*.*.*.*` so 4-segment patch tags trigger the same image build + Docker Hub publish flow as 3-segment ones.

## [2.0.4] — 2026-06-17

**Workspaces dashboard + live host telemetry + docker-in-Vyomi-EC2.** v2.0.4 is the largest UX pass since the v2.0 rename — a new `/clouds` workspaces dashboard with per-cloud distribution donuts and live CPU/RAM/Disk gauges, a comprehensive splash + landing redesign, a floating disk-health chip on every cloud console, plus the A1 docker-in-LXD work that lets users run their own apps inside the simulator's "EC2" instances. Also adds a real-SPA Playwright conformance harness so regressions like the v2.0.3 RDS `db_instances` envelope bug get caught at the DOM level, not just the API level.

### Added

- **Vyomi splash screen** — full-screen wordmark overlay on `/`, fades in/out over 5s, cookie-suppressed for 24h after first view, honors `prefers-reduced-motion`, `?nosplash=1` query param skips it (used by the Playwright harness).
- **Local-fidelity emulation services section on `/`** — 3 horizontal cloud cards (AWS 12 / GCP 12 / Azure 11 services) moved up from `/clouds` to the launch page. Replaces the old "Compare all features" tier-comparison table — pricing now leads with what's emulated, not what's gated.
- **Workspaces dashboard `/clouds`** — split into two surface cards:
  - **Appliance health card** — 3 donut pies (CPU / RAM / Disk distribution per cloud) + 3 live stat cards (host CPU%, RAM total, Disk usage with color-coded amber/red thresholds at 70/88%). New `/api/runtime/host-distribution` aggregates per-provider resource footprint across ALL spaces (no active-space switching). Live VM filter: stopped/terminated/deallocated VMs no longer count toward the pies (matches LXD reality).
  - **Active spaces card** — provider filter pills (All / AWS / GCP / Azure with live counts) + `+ Create Space` modal (name validation + per-cloud picker + region) + filtered grid. Empty-state surfaces when a pill filters everything out.
- **Floating disk-health chip** — every cloud console (`/console/aws`, `/console/gcp`, `/console/azure`) now shows a small `● Disk N% ▾` pill in the top-right corner with pulsing color indicator (green/amber/red). Click to expand into the full disk widget (Free up space + Grow disk actions). GCP console gets its first disk widget at all (AWS + Azure had one previously but always-expanded).
- **`Back to Spaces` link in Azure console header** — matches the pattern that AWS already had, returns the user to `/clouds`.
- **A1 docker-in-Vyomi-EC2** — Vyomi-managed EC2 instances now run real Docker + compose. LXD containers launch with `security.nesting=true`; an idempotent `_lxd_docker_bootstrap_async` background job installs Docker engine on first start. Host-side `appliance_install_lxd_docker_bridge_fix` systemd unit restores `iptables FORWARD ACCEPT` + MASQUERADE so docker's default policy doesn't break LXD outbound. Enables customers to deploy their own apps directly inside the simulator's instances, and enables Vyomi-on-Vyomi dogfood.
- **Real-SPA Playwright conformance harness** — `tests/conformance/ui_real/` boots a real Chromium, walks every wizard, asserts DOM contents. 19/35 services pass, 16 deliberately skipped with documented framework gaps. Closes the gap the API-only suite missed.
- **Vyomi-on-Vyomi proof** — appliance source builds + runs healthy inside a Vyomi-managed EC2 instance (12 backend containers up at `vyomi.local:9001`, sharing Postgres with an inner portal at `:8081`). Validation milestone for v2.0.4 and forward.

### Changed

- **Auto-refresh interval bumped 5s → 30s** with modal-aware skip — the cloud-console resource list view used to repaint every 5s, which fought form input + lost cursor focus. Now 30s, plus an `_shouldSkipAutoRefresh()` gate that pauses entirely when a modal is open.
- **Landing page hero + workspaces hero** — both rewritten with "eyebrow chip + larger H1 + max-width subtitle" pattern. `Choose your tier.` becomes `Welcome to Vyomi · Choose your tier.`; `Your workspaces` becomes `Workspaces · Pick up where you left off.`
- **`/clouds` route split** — exact `/clouds` serves the polished standalone, `/clouds/<path>` remains SPA-routed (so deep links inside the workspaces view still work via the React app).
- **GCP Compute lifecycle actions** — Stop / Start / Reset / Delete buttons on the SPA grid (matching what AWS EC2 already had).
- **AWS catalog field-name fixes** — 5 column-path mismatches corrected (`rds`, `sqs`, `dynamodb`, `apigateway`, `iam`, `vpc`).
- **GCP catalog field-name fixes** — 3 column-path mismatches corrected (`compute` `internalIp`/`externalIp` dropped, `cloudsql` `tier→backendType`, `vpc` `subnetworkCount→IPv4Range`).

### Fixed

- **RDS empty-list bug** — `static/aws-console.html` envelope parser added `|| data.db_instances || data.DBInstances` so the RDS list view populates after Create. Previously required hard refresh.
- **Tier sizer host-budget rewrite** — `core/runtime_sizer.py` now uses `host_cpu-1` / `host_mem-2GB` instead of dividing the simulator's own budget; medium and large tiers bumped to 2c/3072MB and 3c/4096MB respectively.
- **`/clouds` nested-section markup bug** — the previous standalone page opened a `<section>` inside another `<section>` with a redundant heading "Real cloud APIs, on your laptop." right under "Start a new workspace". Collapsed into one clean section.
- **Disk chip syntax error (AWS + Azure consoles)** — first-pass chip integration captured the closing semicolon of the existing card markup inside the `_wrapWithChip(...)` call, killing the entire script block. Fix in the second pass.
- **GCP disk module dead-script** — the GCP module was injected inside a `<script src="...">` tag, which browsers ignore by spec. Moved to its own `<script>` block.

### Release-pipeline plumbing

- New `.github/workflows/release-candidate.yml` for the `-rc*` tag flow (this v2.0.4 cut is final, not RC).
- New `scripts/vyomi-rc-init` / `vyomi-deploy-rc` / `vyomi-rc-status` / `vyomi-promote-rc` companion CLI subcommands.
- New `docs/RUNBOOK-rc-cycle.md` documenting the RC discipline.

## [2.0.1] — 2026-06-15

**Zero-config first launch.** v2.0.0 shipped HTTPS via mkcert + Caddy at `https://vyomi.local:9443`, but a fresh laptop hit three Chrome gotchas in sequence: (1) Secure DNS bypassing `/etc/hosts` for `.local` TLDs, (2) HSTS cache locking failed early attempts into HTTPS-only, (3) HTTPS-First Mode auto-upgrading `http://` requests. Users were dropped into `chrome://net-internals/#hsts` to debug. v2.0.1 sidesteps all three by pivoting the canonical URL to `https://localhost:9443/` — a hostname Chrome universally trusts. mkcert already covered `localhost` in its SAN list, so the green padlock works without any browser config changes.

### Added

- **`socat` localhost bridge** — `vyomi up` now forwards `127.0.0.1:9000` → `VM_IP:9000` and `127.0.0.1:9443` → `VM_IP:9443` via two host-side `socat` processes (PIDs tracked at `~/.vyomi/run/socat-*.pid`). Bridge is loopback-only (`bind=127.0.0.1`) — not reachable from outside the laptop. Idempotent — old PIDs killed before respawn. `vyomi down`/`stop`/`kill` tear it down cleanly.
- **Auto browser open** — after the health check passes, the launcher opens the working URL in the default browser (`open` on macOS, `xdg-open` on Linux, `Start-Process` on Windows). Honors `VYOMI_NO_OPEN=1` for CI / headless / scripted environments.
- **Loud mkcert failure surface** — if the user dismisses the sudo prompt for `mkcert -install`, the launcher now prints a clearly-visible yellow `⚠` warning with the exact remediation command (`brew install mkcert && vyomi restart`). Old behaviour was a silent `verbose-mode-only` log line that users missed.

### Changed

- **Default appliance URL → `https://localhost:9443/`** (was `https://vyomi.local:9443/`). Banner probe ladder tries `localhost:9443` (TLS) → `vyomi.local:9443` (TLS) → `localhost:9000` (HTTP) → `vyomi.local:9000` (HTTP) → IP, and picks the first reachable one as primary. The other reachable URLs are advertised as fallbacks. **Existing v2.0.0 URLs continue to work** — this is purely a default-routing change.
- **mkcert SAN order** — the leaf cert is now generated with `localhost 127.0.0.1 vyomi.local` (was `vyomi.local localhost 127.0.0.1`). The cert covers the exact same names — just primary subject swapped to match the new default URL. Existing certs from v2.0.0 stay valid (all SANs preserved). Force regeneration with `VYOMI_REISSUE_TLS=1 vyomi up`.
- **Brew formula adds `depends_on "socat"` and `depends_on "mkcert"`** — both are required for the green-padlock-by-default UX. Pre-fetching them at `brew install vyomi` time means the first `vyomi up` has one fewer interactive prompt. Reinstall to pick up: `brew reinstall vyomi`.

### Notes for users on v2.0.0

- After `brew reinstall vyomi`, run `vyomi restart` once. The new launcher will start the socat bridge against your existing VM and your browser will land on `https://localhost:9443/`.
- The `vyomi.local` and `192.168.x.x` URLs from v2.0.0 still work — they're now listed as fallbacks rather than primary.
- If your Chrome had cached HSTS / HTTPS-First Mode for `vyomi.local`, the localhost pivot makes that irrelevant. You don't need to clear anything.
- Windows: the localhost bridge is not yet wired (no `socat` in standard tools). Windows users continue to hit `vyomi.local:9443` directly. `netsh interface portproxy`-based bridge is a v2.1.0 follow-up.

## [2.0.0] — 2026-06-15

The vyomi-branded release. 13-phase rebrand campaign: CLI binary, brew formula, Docker Hub namespace, GitHub org, license (MIT → BSL 1.1), HTTP headers, env vars, Python modules, filesystem paths, Docker volumes, Multipass VM name, and HTTPS by default. Every layer ships with runtime back-compat so v1.x upgrades are transparent. See [`docs/MIGRATION-v2.md`](docs/MIGRATION-v2.md) for the upgrade guide.

### Changed — BREAKING

- **HTTPS via mkcert + Caddy** — the simulator is now reachable at `https://vyomi.local:9443` with a **green padlock** (no 'Not Secure' browser warning). On first `vyomi up` (or `install.sh` curl-bash run), the launcher detects missing `mkcert`, offers to install it (brew/apt/dnf/winget), runs `mkcert -install` once to add a local CA to the system trust store (one sudo/UAC prompt accepted forever), then generates a cert+key for `vyomi.local + localhost + 127.0.0.1` at `~/.vyomi/tls/`. The cert is bind-mounted into a Caddy sidecar container (added to both `docker-compose.yml` and `docker-compose.appliance.yml`) that terminates TLS and reverse-proxies to the simulator on port 9000. HTTP on `:9000` remains reachable as a fallback for scripts that don't validate certs. Set `VYOMI_NO_TLS=1` to skip the whole flow. `VYOMI_REISSUE_TLS=1` to force regenerate. `VYOMI_TLS_DIR` to override the cert location. Caddyfile lives at `packaging/caddy/Caddyfile` — swappable to nginx/Traefik later without touching `server.py`.
- **Docker volumes renamed `cloudlearn-*` → `vyomi-*`** in both `docker-compose.yml` (compose path) and `docker-compose.appliance.yml` (Multipass appliance path). 9 volumes: `vyomi-data`, `vyomi-sql-pg`, `vyomi-sql-mysql`, `vyomi-gcs`, `vyomi-nats`, `vyomi-minio`, `vyomi-dynamodb`, `vyomi-portal-keys`, `vyomi-portal-data` (`cloudsim-data` already neutral, untouched). Fresh installs use the new names. **Existing users upgrading from v1.x must run `bash scripts/migrate-volumes-vyomi.sh` ONCE** between `docker compose down` and `docker compose up -d` — copies all data from `cloudlearn-*` volumes into the new `vyomi-*` equivalents. The legacy volumes are left in place after migration for safe rollback; delete them with `docker volume rm cloudlearn-*` once satisfied.
- **Multipass VM name** defaults to `vyomi-appliance` for fresh installs. Existing installs with a `cloudlearn-appliance` VM (created pre-v2.0.0) keep using the old name — the launcher auto-detects via `multipass info` and avoids destroying state. The VM name surfaces only in `multipass info <name>`; users hit the simulator at `vyomi.local:9000` regardless (mDNS publishing handles the brand-facing hostname). Env override `VYOMI_APPLIANCE_NAME` added (mirrors `CLOUD_LEARN_APPLIANCE_NAME` via Phase 8 env aliases).
- **Filesystem paths renamed `~/.cloud-learn/` (launcher state) and `~/.cloudlearn/` (compose install) → `~/.vyomi/`** with one-time migration. On first v2.0.0 boot: if either old path exists and `~/.vyomi/` doesn't, the launcher atomically renames it + creates a back-compat symlink at the old path. Both `cloud-learn up` and the `install.sh` curl-bash flow run the migration independently. End users with existing state (logs at `~/.cloud-learn/logs/`, appliance bootstrap files at `~/.cloud-learn/appliance/<vm>/`, compose state at `~/.cloudlearn/{compose,data,deployments}/`) experience zero data loss. Idempotent — does nothing once `~/.vyomi/` is the canonical dir. The two old launcher/compose path namespaces were inconsistent (hyphen vs no-hyphen); this rename unifies them under `~/.vyomi/`. Symlink retired in v3.0. **NOT touched in this phase: `/etc/cloudlearn/` (deb/rpm system config), `/var/lib/cloudlearn/` (inside-VM state)** — those are higher-risk and deferred to a focused later release.
- **Python modules renamed `core.cloudlearn_*` → `core.vyomi_*`** with full back-compat re-export shims at the old paths. Affected: `core.cloudlearn_platform` → `core.vyomi_platform` (with internal class `CloudLearnPlatform` → `VyomiPlatform` and back-compat alias inside the module), and 14 `packs.azure.cloudlearn_azure_*` → `packs.azure.vyomi_azure_*` modules. Old import paths (`from core.cloudlearn_platform import CloudLearnPlatform`) keep working — the shim re-exports the canonical names. Pack identifier strings (e.g. `cloudlearn.azure.vm.basic`) are unchanged for now (catalog-internal, not user-visible). Removal slated for v3.0.
- **Environment variables renamed `CLOUDLEARN_*` → `VYOMI_*`** with full back-compat. A new runtime mirror (`core/env_aliases.mirror_env`) populates both spellings in `os.environ` at server startup — existing deployments, `.env` files, Dockerfiles, and CI configs keep working unchanged. `.env.example` now uses `VYOMI_*` as the documented canonical name. `docker-compose.yml` interpolations use a dual fallback `${VYOMI_X:-${CLOUDLEARN_X:-default}}` so users overriding via either name win. The bash launcher (`scripts/cloud-learn`) does the same mirror at shell level so `docker compose` and `multipass exec` subshells see both spellings. Conflict-safe: if both names are set with different values, neither is overwritten and a one-line stderr warning is emitted at startup. Removal slated for v3.0.
- **HTTP headers renamed `X-CloudLearn-*` → `X-Vyomi-*`** with full back-compat. A new ASGI middleware (`core/header_aliases.HeaderAliasMiddleware`) transparently bridges both names on every request and response: clients can send either spelling, the server reflects both back on responses. SPA + portal-shipped SDKs now send `X-Vyomi-*` exclusively; legacy `X-CloudLearn-*` consumers (older SPA cached in browsers, third-party scripts) keep working. Affected headers: Tenant, Tier, Tier-Denied, Principal, Acting-As-Tenant, XTRBAC-Denied, Cedar-Denied, SSO-Denied, Admin-Key, Bridge-Token, CI-Secret, Notif-Secret, Sink-Secret, Host-OS. Removal slated for v3.0.
- **CLI binary renamed `cloud-learn` → `vyomi`** with a `cloud-learn` deprecation shim. The shim prints a one-line yellow warning to stderr on every interactive invocation (suppressible via `VYOMI_NO_DEPRECATION_WARN=1`) and then `exec`s `vyomi` with the same args. End users on every install path see the binary rename simultaneously:
  - **Brew**: `bin/vyomi` (primary) and `bin/cloud-learn` (shim) both shipped with the formula
  - **DEB/RPM**: `/usr/bin/vyomi` (primary) and `/usr/bin/cloud-learn` (shim) installed by the package
  - **Scoop**: `scoop install vyomi` is the new canonical; `scoop install cloud-learn` keeps working via a separate deprecation manifest that prints the rename notice on install
  - **Docker Compose**: unaffected — the container runs `python server.py` directly
- Bash completion now registers against both `vyomi` and `cloud-learn` so tab-complete works on legacy invocations.
- **Brew formula renamed `cloud-learn.rb` → `vyomi.rb`**. New canonical install: `brew install vyomi-cloud/tap/vyomi`. Back-compat: `Aliases/cloud-learn → Formula/vyomi.rb` symlink in the tap, so `brew install cloud-learn` continues to work indefinitely (both resolve to the same package). Formula class renamed `CloudLearn → Vyomi`, license metadata `MIT → :cannot_represent` (BSL 1.1 isn't in SPDX simple form), homepage now `https://vyomi.cloud`.
- **License: MIT → Business Source License 1.1** with a Vyomi-specific Additional Use Grant. Source-available, not open-source-OSI. Change Date 4 years from release, Change License Apache 2.0. The Additional Use Grant blocks (a) hosting Vyomi as a third-party commercial multi-cloud simulator service, (b) modifying/bypassing tier-enforcement code, (c) rebranding for commercial redistribution. Non-commercial use and internal evaluation remain unrestricted. See [`LICENSE`](LICENSE) for full text. Existing forks pre-v2.0.0 retain MIT under the historical commit terms.
- Shim removal slated for **v3.0** — users have at least one major version cycle to migrate.


## [1.2.5] — 2026-06-15

Default-space naming convention. The three out-of-the-box spaces are now `aws-default`, `gcp-default`, and `azure-default` — matching how every other identifier in the appliance and SDK examples talks about per-provider defaults. Previous names (`Legacy Workspace`, `GCP Project`, `Azure Subscription`) were inconsistent and looked like manually-created spaces rather than defaults.

### Changed

- **Fresh installs** now seed three spaces named `aws-default`, `gcp-default`, `azure-default` (was: `Legacy Workspace`, `GCP Project`, `Azure Subscription`). Space IDs are unchanged (`space-legacy`, `space-gcp-default`, `space-azure-default`) so `cloudsim_runtime_id` / `lxd_project_name` references in persisted state stay valid.
- **Existing installs** get a one-shot migration on first v1.2.5 boot (`migrate_default_space_names()` in `core/app_context.py`) — renames spaces only when the current name still matches the legacy default. Any space the user renamed themselves is untouched.

### Why

The pricing/upgrade flow, the per-cloud console gates, and the docs all reference `aws-default` etc. as the canonical names. Having the UI show a different label was a needless source of "wait, which space am I in?" confusion for new users.

## [1.2.4] — 2026-06-15

URL parity: every install path now lands on `http://vyomi.local:9000`. v1.2.3 made the Multipass-based paths (Brew/.deb/.rpm/Scoop) reachable via mDNS at `vyomi.local`. This release extends the same hostname to the Docker Compose path so users never have to remember a different URL based on which install method they picked.

### Added

- **`install.sh` now adds `127.0.0.1 vyomi.local` to `/etc/hosts`** at the end of the one-liner install — idempotent (only inserts if the line is absent), interactive sudo prompt, best-effort DNS-cache flush (macOS `dscacheutil`, Linux `systemd-resolve`). Falls back to `http://localhost:9000` cleanly if the user declines sudo or `/etc/hosts` isn't writable.
- **INSTALL.md** documents the one-time hosts entry as step 5 of the quick-install flow with a "Why vyomi.local?" explainer.
- **Portal `/install` page** Docker Compose entry now has a "Step 3: One-time hosts entry so http://vyomi.local:9000 works" with copy-pasteable macOS / Linux / Windows-PowerShell commands. Step 4/5 commands updated to use the new URL.

### Fixed

- `.env.example` image pin bumped to `vyomi/appliance:1.2.4` (was 1.2.2).
- `install.sh` day-2 hint had the same `pull && up -d` typo as INSTALL.md before v1.2.2 — fixed to `docker compose pull && docker compose up -d`.

### Why this matters

Before v1.2.3, every install path landed on a different URL (an IP for the appliance, `localhost` for Compose). v1.2.3 unified the Multipass paths on `vyomi.local`. v1.2.4 finishes the job — one URL across all 5 install methods on every supported OS.

## [1.2.3] — 2026-06-15

The appliance is now reachable at `http://vyomi.local:9000/` — no more pasting bridged Multipass IPs into a browser. Hostname resolution uses standard mDNS (Bonjour on macOS, avahi on Linux, native mDNS on Windows 10 1809+) so it works on any local network that doesn't actively block multicast, with zero `/etc/hosts` modification.

### Added

- **cloud-init.yaml** now installs `avahi-daemon` + `libnss-mdns`, sets the VM hostname to `vyomi`, patches `/etc/nsswitch.conf` to query mDNS, and enables the avahi service. A fresh `cloud-learn up` makes `vyomi.local` resolvable from the host within seconds of boot.
- **`ensure_vyomi_mdns_active()`** runs on every `cloud-learn up` and idempotently brings legacy VMs (launched before v1.2.3) up to the same state. Fast no-op (~50 ms) when avahi is already publishing; ~30s one-time fix-up otherwise. Bounded by a 60s wall-clock cap so it can never hang the launcher.
- **`print_url_banner()`** probes `vyomi.local:9000/healthz` and prefers the hostname URL when reachable. The bridged IP is always shown as a fallback so users on multicast-blocked networks (corporate, some VPNs) still have a copy-pasteable URL.
- **Phase 8 status output** now shows both URLs as soon as the VM IP is known, so the user can open either in a browser while the health check is still polling.

### Fixed

- The portal `/install` page's hero subtitle previously claimed all paths land on `http://localhost:9000` — accurate only for Docker Compose. Now the copy distinguishes the Multipass-based paths (Brew/.deb/.rpm/Scoop → `http://vyomi.local:9000`) from Compose (still `http://localhost:9000`). The "After install" block has the same fix.
- Per-method comment examples in `install_catalog.py` swapped `http://192.168.x.x:9000` for `http://vyomi.local:9000`, matching what the launcher actually prints.

### Operational notes

- Networks that block multicast (corporate switches with IGMP snooping misconfigured, some hotel WiFi, certain VPN clients) will fail mDNS resolution. The launcher's URL banner shows the IP fallback for exactly this case.
- Linux server installs without `libnss-mdns` on the HOST won't resolve `vyomi.local` from that host either — `apt install libnss-mdns` once on the host and it works. Default on Ubuntu desktop, Fedora, Debian with the standard meta-packages.
- Windows users on Windows 10 builds older than 1809 (October 2018 Update) need Apple Bonjour Print Services installed, or they should use the IP fallback.

## [1.2.2] — 2026-06-15

Distribution-parity release: every package-manager install path that ships cloud-learn now gets the same first-launch experience — `cloud-learn up` detects missing Multipass and installs it via the platform-native package manager. Closes the Windows (Scoop) and Linux-without-snapd gaps that v1.2.1 left open. Also fixes a docker-compose .env.example bug that made the Compose install path 404 on `docker compose pull`.

### Added

- **`maybe_install_multipass()` now covers Windows.** When `PARENT_OS=windows` (Scoop install path), the launcher detects winget on PATH, shows the same yellow notice box used on macOS/Linux, and runs `winget install --id Canonical.Multipass --accept-package-agreements --accept-source-agreements`. Honors `-y` / `CLOUD_LEARN_YES=1` and gracefully degrades if winget isn't on PATH (e.g. Windows Server without App Installer).
- **Snapd-bootstrap guidance on Linux.** When `snap` itself isn't on PATH (common on RHEL/Fedora/SUSE minimal images), the launcher detects which distro package manager is available (`apt-get` / `dnf` / `zypper`) and prints the exact 2-3 commands to install snapd + enable its socket + install Multipass. No more silent fall-through to "multipass is not installed" with no recovery path.

### Fixed

- **`.env.example` image pin was broken.** Was `CLOUDLEARN_SIMULATOR_IMAGE=cloudlearn/simulator:1.0.0` — wrong namespace (`cloudlearn/simulator` does not exist on Docker Hub) AND stale version (months behind). Any user running `cp .env.example .env && docker compose pull` got `pull access denied`. Now pins to `vyomi/appliance:1.2.2` (the real, current image). Comment explains how to opt into rolling `:latest` updates.
- **INSTALL.md docker-compose upgrade step clarified.** `docker compose up` does NOT auto-pull on existing images — added an explicit `docker compose pull && docker compose up -d` recipe with a note about `--pull always` semantics. The previous one-liner `docker compose pull && up -d` was a typo (missing the second `docker compose`).

### Coverage matrix after this release

| Install path | OS | Auto-install command |
|---|---|---|
| Brew | macOS | `brew install --cask multipass` |
| DEB / RPM | Linux + snapd | `sudo snap install multipass` |
| DEB / RPM | Linux no-snapd | Step-by-step instructions for apt-get / dnf / zypper |
| Scoop | Windows | `winget install Canonical.Multipass` |
| Docker Compose | any | N/A — appliance runs inside Docker, no host Multipass needed |

### Why this matters

v1.2.1 closed the macOS-via-brew gap. v1.2.2 closes the same gap on every OTHER package-manager install path users actually use. A first-time Windows user who runs `scoop install cloud-learn` followed by `cloud-learn up` now gets the same one-prompt-and-go experience their macOS counterpart does.

## [1.2.1] — 2026-06-15

UX polish: `cloud-learn up` now installs Multipass for the user when it's missing, instead of just emitting "multipass is not installed". The brew formula structurally can't `depends_on` Multipass (formulae cannot depend on casks), so the launcher closes the gap at runtime.

### Added

- **`maybe_install_multipass()` helper in `scripts/cloud-learn`.** Called from `ensure_prereqs()` before the multipass PATH check. Platform-aware:
  - **macOS** + brew available → shows a yellow notice box with size/disk/sudo-prompt expectations, prompts `[Y/n] (auto-yes in 30s)`, then runs `brew install --cask multipass`. After install, re-resolves PATH for `/usr/local/bin` and `/opt/homebrew/bin`.
  - **Linux** + snap available → prompts and runs `sudo snap install multipass`.
  - Honors `-y` / `CLOUD_LEARN_YES=1` for non-interactive installs (CI, scripted bootstrap).
  - Non-interactive shells (no TTY) skip the prompt and fall through to the friendly error.
- **Friendly error if auto-install can't proceed.** When brew/snap aren't available or the user declines, the launcher emits a multi-line `_die()` block with the exact `brew install --cask multipass` or `sudo snap install multipass` command — no more bare "multipass is not installed".

### Fixed

- **Stale `depends_on "multipass" => :recommended` / `depends_on "docker" => :recommended`** in `packaging/homebrew/Formula/cloud-learn.rb`. These were invalid against casks and would fail `brew audit`; replaced with a comment that points to `maybe_install_multipass`. End users were never affected (the live formula in `vyomi-cloud/homebrew-tap` is overwritten by `release.yml` on every tag), but the in-repo copy was misleading anyone reading the source.

### Why this matters

End-to-end on a fresh macOS:
```
brew install cloud-learn
cloud-learn up
# (sees yellow box, types Y, sudo password for the .pkg, multipass installs,
#  appliance VM boots — single command from a fresh laptop to running stack)
```

No more two-step `brew install --cask multipass && cloud-learn up`. The launcher pipeline now bridges the brew-formula/brew-cask gap at runtime, which is exactly where it should live for an appliance distribution.

## [1.2.0] — 2026-06-15

First post-launch release with the launcher pipeline stable. Two functional bugs from the v1.1.11 walkthrough are fixed here — both user-facing, both shipped behind the now-validated bundle pipeline.

### Fixed

- **"Activate appliance" returned `Failed: {"detail":"portal_unreachable: URLError: "}`.** `core/license_remote.DEFAULT_BACKEND_URL` was hard-coded to the placeholder `https://license.cloudlearn.io`, which never had a DNS record. Activation, device-flow polling, JWKS fetch, and the revocation daemon all silently failed with `Name or service not known`. Default is now `https://vyomi.cloud` (the live portal that already serves `/api/oauth/device`, `/api/license/revocation`, and `/.well-known/jwks.json`). The `CLOUDLEARN_LICENSE_BACKEND_URL` env var still overrides for self-hosted portals.

- **EC2 console listed new instances as `stopped` and never refreshed without a hard reload.** The state badge mapping was already correct (`pending` → warn-yellow), but the AWS console did exactly one fetch per `navigate()` call. State transitions (`pending → running`, `creating → available`) only became visible after the user hit Cmd-R.
  - Added a 5-second auto-refresh polling loop scoped to mutable-state services (`ec2`, `rds`, `lambda`) on BOTH the list view AND the detail blade.
  - Polling cancels itself when the user navigates away (the `setInterval` checks `STATE.view` and `STATE.service` before re-rendering and tears itself down on mismatch).
  - `clearAutoRefresh()` is also called at the top of `navigate()` so no stale timer survives a route change.

### Why this matters

The "appliance can't talk to its portal" bug made the brew install effectively unusable for any tier-gated feature (cloud-shell, audit sinks, CI integration) — users would activate, see green, and then every subsequent feature would 403 silently. The "EC2 stuck on stopped" bug made every demo of the AWS console look broken. Both shipped here behind the v1.1.10/v1.1.11 verification pipeline, so the brew bundle is guaranteed launchable before the tag goes out.

## [1.1.11] — 2026-06-15

User report on v1.1.10: phases 1-7 ran green (build + start succeeded!) but Phase 8 hung indefinitely. Diagnosis: the launcher's health probe used `multipass exec ... curl 127.0.0.1:Port` three times per iteration, and one of those `multipass exec` calls was stuck for 3+ minutes even though the VM and the simulator inside it were both fully healthy. Same `multipass exec` quirk class we've hit twice before.

### Fixed

- **Health probes now go DIRECTLY from the Mac to the VM's bridged IP**, bypassing `multipass exec` entirely. `curl -fsS -m 2 http://<vm-ip>:Port` has a real wall-clock cap and finishes in ~1 second per iteration. Verified live against the user's stuck appliance: new probe correctly detected all three services healthy in 1s; the old probe was hung for 3+ minutes.

### Added

- **Appliance URL is printed BEFORE health check starts.** Even if anything in Phase 8 ever hangs again, the user can already open the URL in a browser. A pinned line:
  ```
      Appliance URL  http://<vm-ip>:9000/
      (you can open this now — health check below confirms it)
  ```
  shows up at the top of Phase 8 so the URL never gets buried in scroll-history when something goes wrong.

### Why this matters

Three classes of "user is clueless after the prompt returns" have now been fixed: silent subshell exits (v1.1.9 `set -E`), bundle COPY mismatch (v1.1.10), and now `multipass exec` hangs (v1.1.11 direct curl). The launcher's reliability surface is now small enough that the next regression should be quick to spot.

## [1.1.10] — 2026-06-15

The first release validated by an automated bundle-verification step
**before** the tag was cut. No more shipping broken bundles.

### Fixed

- **`docker compose build` failed with `"/setup_cython.py": not found` / `"/routes": not found` / `"/scripts": not found` / `"/VERSION": not found`.** v1.1.8/v1.1.9 transferred only a subset of what the appliance Dockerfile actually `COPY`s — the build context inside the VM was missing 4 paths. The user paid 4-5 minutes of docker compose build time before the failure surfaced.
  - `appliance_sync_workspace_into_vm()` required list expanded to all 12 paths the Dockerfile + cloudsim Dockerfile reference.
  - `release.yml` allowlist updated to match — every release tarball v1.1.10+ has the full set.

### Added

- **`scripts/verify-bundle.sh`** — a 5-second local check that simulates the launcher's tar logic against any candidate bundle directory and asserts every Dockerfile `COPY` source resolves inside the resulting tarball. Caught the v1.1.9 regression in dry-run before it shipped. Now run as a pre-tag gate.
- **First-launch download notice + confirmation prompt** (user request). Before Phase 7 starts, the launcher prints a yellow box listing every container image about to be pulled (postgres, mysql, google-cloud-cli, vault, nats, minio, dynamodb, elasticmq, fake-gcs-server, python+maven build bases), with size estimates and a ~3.5 GB total. User is prompted `Proceed? [Y/n]` with a 30-second auto-yes so it never blocks automation. Skipped on second+ launches (when the simulator image is already cached in the VM).
- **`-y` / `--yes` flag** + `CLOUD_LEARN_YES=1` env var to skip the prompt for CI / scripted use.

### Why "validated before tag" matters

Every regression we shipped in v1.1.1 → v1.1.9 was something an offline check could have caught. The bundle verifier is the gate now. If `scripts/verify-bundle.sh` fails locally, the launcher will fail on the user's machine the same way — fix it before tagging.

## [1.1.9] — 2026-06-14

Critical hotfix for v1.1.8's silent-exit bug + the underlying brew tarball regression.

### Fixed

- **Launcher exited with a returned shell prompt and no banner.** v1.1.8's `appliance_sync_workspace_into_vm` listed `cloudsim-backbone/` in its tar inputs, but the brew bundle (and every release tarball v1.0.0–v1.1.8) was missing that directory — the release.yml workflow's tar allowlist never included it. The launcher's tar call ran inside a `( ... )` subshell with stderr redirected to `/dev/null`. When tar failed, the subshell exited 1, `set -e` killed the script, but the **ERR trap did not fire** because bash's default doesn't inherit ERR into subshells. Net result: user saw `==> Appliance: packaging source for VM` and then a returned shell prompt with zero feedback.

  Three fixes:
  - **`set -E`** added at the top of the launcher. Makes the ERR trap inherit into subshells, command substitutions, and functions. Now any silent failure trips the loud red banner.
  - **Required / optional split** in the workspace sync. `cloudsim-backbone` is treated as optional (it's missing from older bundles); a missing required file calls `_die()` with a clear pointer to `brew reinstall` or `CLOUD_LEARN_HOME=…`.
  - **`tar` stderr is now captured to a log** and surfaced into the failure banner instead of suppressed to `/dev/null`.

- **`cloudsim-backbone/` added to the release tarball allowlist** (`.github/workflows/release.yml`). Going forward every release bundle has it. Older v1.1.x bundles can still work — the launcher just skips that path.

### Why this matters

The whole point of v1.1.5's UX overhaul was that the launcher would never again exit silently. v1.1.8 regressed that invariant in a subshell-shaped blind spot. v1.1.9 closes the hole with `set -E` so future silent exits are impossible by construction.

## [1.1.8] — 2026-06-14

**Replaces the SSHFS workspace mount with tar+transfer.** The third (and last) brew-prefix sandbox issue in the launcher.

### Fixed

- **`docker compose up` failed with `open /workspace/cloud-learn/docker-compose.appliance.yml: permission denied`.** Root cause: same brew SSHFS sandbox issue v1.1.1 fixed for host-sizing-report.json and v1.1.3 fixed for runtime_bridge.py. Docker compose runs inside the VM and tries to read its config file from the SSHFS mount — which is unreadable when ROOT_DIR is under `/opt/homebrew/`. Verified: even `sudo cat /workspace/cloud-learn/docker-compose.appliance.yml` returns `Permission denied`. Verified the workaround paths (native mount, uid mapping) don't help.

### Approach

- `appliance_sync_workspace_into_vm()` replaces the legacy `multipass mount`. It tars the essential source files (Dockerfile, docker-compose.appliance.yml, server.py, core/, providers/, packs/, static/, cloudsim-backbone/, + a few more), `multipass transfer`s the tarball, and untars at `${APPLIANCE_WORKSPACE}` (default `/workspace/cloud-learn`).
- Tarball size: ~3 MB gzipped, transfers + extracts in 2-3 seconds.
- No SSHFS dependency anywhere in the appliance hot path. The brew-prefix sandbox is now completely side-stepped for all three of: host-sizing report, runtime bridge script, and the workspace source itself.

### Trade-off

- Live-edits on the host don't auto-propagate into the VM anymore. Users must `cloud-learn restart` to re-sync. For brew installs (a pinned snapshot) this is exactly right. For dev installs (where ROOT_DIR is the user's working clone), it's a manual step instead of an automatic one — acceptable.

## [1.1.7] — 2026-06-14

Two embarrassing bugs in v1.1.6 surfaced on the user's next run. Both
diagnosed from the persistent log v1.1.5 added — so the diagnostic
infrastructure is already paying off.

### Fixed

- **The bridge install reported FAILURE even though `READY-after-2s` was captured.** Root cause: `multipass exec ... /bin/bash -lc "set -e; ...; exit 0"` returns rc=1 when the inner script terminates with explicit `exit 0`, but rc=0 when it ends naturally. This is a multipass-specific quirk (verified by reproducing in isolation). Restructured the bridge install loop to set a `READY=1` flag, `break` out of the for-loop, then fall through to natural script end. Failure path still uses `exit 1` which propagates correctly.
- **Failure banner showed literal `\033[31m` text instead of red colour.** Root cause: `_C_GREEN='\033[32m'` (single quotes) preserves the literal 5-character string `\033[32m`, not a real ESC byte. `_emit` then printed the literal string with `printf '%s\n'`. Fix: use `$'\033[32m'` quoting at definition time so the variables hold real ESC bytes. Verified end-to-end.
- **Stale error message.** v1.1.6 bumped the bridge poll budget to 180s but the failure message still said "(30s timeout)". Now matches reality.

### Lessons baked into the launcher

1. Inside heredoc'd bash run via `multipass exec`, never use explicit `exit 0` for success — let it fall through. `exit 1` is fine for failure.
2. Colour escape variables must be `$'\033[…]'` quoted, not `'\033[…]'`. The former materialises real ESC bytes; the latter is a literal 5-char string.

## [1.1.6] — 2026-06-14

Two follow-on fixes to v1.1.5 surfaced by the first real user.

### Fixed

- **Runtime-bridge poll timeout was too aggressive.** v1.1.5 polled `:9171/health` for 30s, but `systemd` queued the bridge start behind `snap.lxd.daemon.service` which on a fresh cold-start takes 1-3 min to settle. The launcher gave up at 30s even though the bridge came up healthy 2-3 min later. Two fixes:
  - Drop `After=snap.lxd.daemon.service` and `Wants=snap.lxd.daemon.service` from the systemd unit. The bridge only checks LXD on-demand per HTTP request anyway — no need to block startup on it. `After=network.target` is enough.
  - Bump the bridge poll timeout from 30s → 180s as a safety belt, plus a 15s heartbeat to the captured log so triage shows what state systemd is in.
  - `systemctl reset-failed` before `enable --now` so a prior failed launch doesn't poison the next attempt.
- **`%b` literal artifacts in the failure banner.** `_die()` embedded `%b` as colour-marker placeholders, but `_emit()`'s `printf '%b\n' "$line"` treats the string as the ARGUMENT to `%b`, not as a format string — so embedded `%b` characters printed as literals. Fix: `_emit()` now uses `printf '%s\n'` (no format interpretation at all) and every caller pre-formats with concrete `${_C_RED}…${_C_RESET}` interpolation. Cleaner AND safer.

## [1.1.5] — 2026-06-14

**Commercial-grade launcher UX.** The previous launcher could exit silently on a runtime-bridge failure, leaving the user staring at a returned shell prompt with no clue what happened. This release makes the launcher loud, structured, and recoverable.

### Added

- **Persistent log per run.** Every `cloud-learn up` invocation streams its full output to `~/.cloud-learn/logs/up-<timestamp>.log`. Last 10 logs are kept. Whatever the user copies into a support thread, the full transcript is one path away.
- **`[N/M]` phase counter.** Cmd `up` now prints `[1/8] Pre-flight checks`, `[2/8] Host SSH identity bootstrap`, … through `[8/8] Waiting for health`. At a glance the user knows where they are.
- **Per-phase `✓ done in Xs` line.** Each phase prints its own elapsed time, so users can instantly see which step is the slow one (almost always Phase 4 — cold-start image + LXD snap install).
- **Loud `✗ APPLIANCE LAUNCH FAILED` banner.** On any failure, a red banner prints with: which phase failed, the actual reason (not buried in stderr), 3-4 recovery commands specific to that phase, and the log path. No more silent exit-1.
- **Loud `✓ APPLIANCE READY in Xm00s` banner with URL** at the very end of a successful run. The user knows they're done.
- **Top-level `ERR` trap.** If any phase forgets to call `_die()` with a friendly message, the trap still fires the failure banner so the user never sees a bare shell prompt.
- **Per-component health probe.** Health check now probes the bridge / simulator / CloudSim separately and prints `bridge=✓  sim=…  cloudsim=…` so the user sees exactly which thing is still coming up.

### Fixed

- **Runtime-bridge install failure was silent.** The bridge's systemctl `enable --now` output and journalctl tail were redirected to `/dev/null`. If the bridge crashed on startup the user only saw a returned prompt and a stuck "browser doesn't load". Now the full install output is captured to a temp file, surfaced into the failure banner (tail -25), AND appended to the persistent log.

### Changed

- **`appliance_health_check` no longer prints a multi-line dump on success — just the URL banner.** The old box-drawn banner had alignment issues on narrow terminals.

### Why this matters

We're building a commercial appliance. A user paying ₹299/month who hits a silent failure on first launch will assume it's broken and uninstall. v1.1.5's loud, structured UX means: every failure is actionable, every success is unambiguous, every run is reproducible.

## [1.1.4] — 2026-06-14

Hotfix for zombie-VM recovery on `cloud-learn up`.

### Fixed

- **`Deleted` (zombie) VMs from prior `multipass delete` without `multipass purge` are now auto-recovered.** Previously `cloud-learn up` would log `existing VM detected (Deleted)` → `VM state is uncertain, skipping start and continuing` → then march forward into `mount`, `transfer`, and `wait_for_cloud_init` against a non-existent VM. Result: `(warning: could not transfer host-sizing-report.json to VM)` + an infinite cloud-init wait.
  - The launcher now detects the `Deleted` state explicitly, runs `multipass purge`, and launches a fresh VM.
- **Unknown / Starting / Restarting / etc. states now surface a clear pointer instead of silently continuing.** If the launcher can't recover the state automatically, it prints the exact two commands the user needs (`multipass info` / `delete && purge`) and exits — much better than the previous infinite hang.

### How users hit this

1. Run `multipass delete --all` (forgot the `purge`).
2. Run `cloud-learn up`.
3. See `(warning: could not transfer host-sizing-report.json to VM)` and a stuck `waiting for cloud-init`.
4. Eventually `Ctrl+C` and re-clean. v1.1.4 makes step 3 self-heal.

## [1.1.3] — 2026-06-14

Hotfix continuation of v1.1.1 — same brew-sandbox class of bug, this time
for the runtime bridge systemd unit.

### Fixed

- **`cloudlearn-runtime-bridge.service: Main process exited, code=exited, status=2/INVALIDARGUMENT`.** The systemd `ExecStart` pointed at `/workspace/cloud-learn/core/runtime_bridge.py`, which is the SSHFS-mounted brew libexec on macOS brew installs. The mount is unreadable from inside the VM (same brew-prefix sandbox issue v1.1.1 fixed for `host-sizing-report.json`), so Python sees "no such file" and exits with code 2 — which systemd reports as `status=2/INVALIDARGUMENT`.
  - The launcher now `multipass transfer`s `core/runtime_bridge.py` into the VM at `/var/lib/cloudlearn/runtime_bridge.py`. Same `multipass transfer` pattern v1.1.1 introduced for the sizing report.
  - systemd `ExecStart` now points at `/var/lib/cloudlearn/runtime_bridge.py` — a stable, sandbox-free path. Survives `multipass restart` (which the previous nohup approach didn't), `cloud-learn restart`, and any future workspace remounts.

### Why this matters

Without the bridge running, the simulator's `lxd_available` check returns False → EC2 / Compute Engine / Azure VM launches silently stay in `pending` state forever with no error. The launcher used to surface `runtime bridge failed to start` and dump 50 lines of journalctl, which was at least loud — but it was also fatal: `cloud-learn up` exited 1 and the user was stuck.

### Backward compat

- Existing non-brew installs (running from a workspace clone where the file actually IS readable through the mount) keep working — the transfer just becomes a redundant copy.
- `cloud-learn restart` and `cloud-learn up` are both idempotent: re-transferring the script on every invocation is cheap (9KB) and ensures bug-fixes to `runtime_bridge.py` ship as soon as the user re-runs.

## [1.1.2] — 2026-06-14

UX-only release. Cold-start verbosity overhaul.

### Added

- **Wall-clock prefix on every progress line.** `[2m13s] ==> Appliance: …` instead of bare arrows — at a glance the user knows whether they're 30s or 4 min into the launch.
- **`-v / --verbose` flag + `CLOUD_LEARN_VERBOSE=1` env var.** Streams raw `cloud-init-output.log` tail lines + sub-step detail. Useful when triaging a slow / stuck launch without having to SSH into the VM.
- **`describe_step()` lookup table.** Translates the active runcmd's raw argv into a human description. E.g. `snap install lxd` now prints as `installing LXD container runtime (~150MB snap)`. Covers the 7-8 commands a fresh Ubuntu cold-start actually runs.
- **30-second heartbeat during long-running runcmd steps.** When `snap install lxd` is grinding for 2-3 min, the launcher prints `still installing LXD container runtime…` every 30s so the user knows it isn't hung.
- **Inner `docker compose up --build` output is no longer silenced.** Layer-by-layer build progress is indented and surfaced to the outer launcher, so users see Dockerfile build steps in real time instead of waiting blind for 2-3 min.

### Changed

- **Cloud-init poll interval 12s → 6s.** Stage transitions show up sooner.
- **The `launch` banner now hints at expected timing up-front** (5-8 min cold start, image ~600MB, LXD snap ~150MB).

### Internal

- `progress()` now derives elapsed seconds from `_LAUNCH_STARTED_AT`, set once at script invocation. No-cost — uses `date +%s`.

## [1.1.1] — 2026-06-14

Hotfix for the launcher on brew-installed setups (macOS).

### Fixed

- **`cloud-learn up` no longer fails with `install: cannot open '.../host-sizing-report.json' for reading: Permission denied`.** The launcher was writing the bootstrap artifacts (`cloud-init.yaml`, `appliance-bootstrap.json`, `host-sizing-report.json`) into `${ROOT_DIR}/.cloudlearn-appliance/`. When installed via brew, `ROOT_DIR` is `/opt/homebrew/Cellar/cloud-learn/<v>/libexec`, which sits behind macOS's brew-prefix sandbox. Multipass's SSHFS workspace-mount cannot read through that boundary from inside the VM — even as root — so the subsequent "sync host sizing into VM" step blew up.
  - `APPLIANCE_DIR` now defaults to `${HOME}/.cloud-learn/appliance/${APPLIANCE_NAME}/`. Writeable by the launching user, per-VM, no sandbox.
  - The sync step now uses `multipass transfer` to push the sizing report directly into the VM instead of relying on the SSHFS mount. Removes the SSHFS dependency entirely for this step.
- **`cloud-learn up` no longer looks "stuck" during cloud-init.** The previous `multipass launch` foreground call printed `Waiting for initialization to complete` then sat silent for 3-5 min while LXD's snap install ran. The new `appliance_wait_for_cloud_init` helper polls cloud-init status every 12s and surfaces:
  - the current cloud-init stage (`init` / `config` / `final`)
  - the active runcmd process (so users see "snap install lxd" when that's the slow bit)
  - elapsed seconds
  - a 10-min bail-out heartbeat with a pointer to `cloud-init-output.log` for triage
- **Added an up-front timing hint.** `==> Appliance: launching Multipass VM` now prints expected cold-start time (5-8 min) and the three big downloads (image / snap / cloud-init) so users know whether to wait or alt-tab.

### Backward compat

- `CLOUD_LEARN_APPLIANCE_DIR` env var still overrides the new default — existing automation pinned to the old location keeps working.
- The brew tap auto-bump workflow continues to fire on this tag; users just `brew upgrade cloud-learn`.

## [1.1.0] — 2026-06-14

Console-actions conformance climbs from 53% baseline → **100%** across
all three providers. The simulator now answers every catalog-published
action with a contract-conformant response or a documented structural
skip (catalog stub / chain-dependency / tier-gated / environmental).

### Conformance — 100% across the board

- **AWS** 114 / 114 (100.0%) — `tests/conformance/console_actions/test_aws_console.py`
- **Azure** 52 / 52 (100.0%) — `test_azure_console.py`
- **GCP** 87 / 87 (100.0%) — `test_gcp_console.py`
- **Total** 253 / 253 (100.0%), 47 structural skips

The CI gate (`check_pass_rate.sh`) is now monotonic at 100% on every
provider — any regression blocks the build, future climbs only ratchet up.

### Added

- **Conformance harness — Pattern C environmental-skip filter.** Classifies
  `(507, "insufficient_disk")`, `(503, "error: the remote")`, and
  `(503, "lxdunavailable")` as `skip` rather than `fail`. Keeps the
  contract gate honest on laptops without 10+ GB free or the LXD postgres
  image preloaded; cascade-skips downstream lifecycle actions of the same
  service so one env block doesn't generate N failures.
- **S3 `?force=1` bucket delete.** `DELETE /api/s3/buckets/{name}?force=1`
  drops contained objects before deletion. Matches the AWS console's
  "Empty bucket then delete" flow.
- **GCP CloudSQL idempotent create.** A second POST with the same
  `name + project` returns the existing record at 200 (matches GCP's
  implicit etag-match), instead of the legacy 409 "Instance already
  exists." Makes the suite immune to state-bleed from prior runs.
- **GCP `/api/gcp/rds/databases/{instance}/...` defaults `project=cloudlearn`.**
  6 routes (get, delete, reboot, backups, list, create) so the AWS-style
  path is usable without threading a query param. The canonical
  `/sql/v1beta4/projects/{project}/...` paths still require it for
  real google-cloud-sdk clients.
- **GCP LRO unwrap extended to SQL's envelope shape.** Recognizes the
  `{"kind": "sql#operation", "targetId": "<id>"}` shape distinctly from
  the apigateway/functions `name: "projects/.../operations/..."` shape.
- **Defensive empty-body parse** on `gcp_sql_create_instance`,
  `gcp_pubsub_publish`, `gcp_functions_create`, `gcp_sql_patch_instance`.

### Fixed

- **`payload_for("gcp", "cloudsql")` returned `None`.** The dict key was
  the legacy short alias `"sql"`, but the catalog publishes `"cloudsql"`.
  Mismatch caused the harness to send empty bodies → handler fell back
  to default name `"sql-instance"` → state-bleed across runs. Renamed
  to match catalog.
- **`api_lambda_invoke` `body_target` mismatch.** Was `"req"` but the
  handler signature took `payload`; raised TypeError → 500.
- **`api_apigateway_put_method`** at the REST-flat path
  `PUT /api/apigateway/apis/{name}/resources/{rid}/methods/{verb}` —
  was a catalog stub, now implemented.
- **AWS S3 catch-all eating dotted paths.** Reserved-bucket guard now
  also rejects `static/`, `console/`, `api/`, etc., so the SPA's
  catch-all returns proper 404 JSON rather than `NoSuchBucket` XML.
- **Per-run name suffix size bumped 2 → 4 bytes.** Old 16K namespace
  was colliding within a day of dev runs; new 4M namespace gives
  comfortable headroom.

### Changed

- **CI floors** (`tests/conformance/console_actions/check_pass_rate.sh`):
  AWS 96 → 100, GCP 95 → 100, Azure 100 → 100 (no change).
- **`run_conformance.py --fail-under` is now authoritative.** Previously
  any individual test failure exit-1'd even when `overall >= threshold`.
  Now the threshold is the only gate when explicitly set on the CLI;
  individual failures print a `NOTE:` line but don't trip the exit.

## [1.0.0] — 2026-06-01

First general-availability release. Vyomi is a local-first multi-cloud
simulator with cloud-faithful APIs across AWS, GCP, and Azure. Standard
provider SDKs and CLIs work natively against the simulator — no shim
required — by overriding the endpoint URL.

### Added

#### Multi-cloud surface
- **AWS (9 services)** — EC2, S3, RDS, DynamoDB, SQS, Lambda, API Gateway, IAM, VPC + EventBridge + Secrets Manager + KMS (12 with the new ones)
- **GCP (9 services)** — Compute Engine, Cloud Storage, Cloud SQL, Pub/Sub, Firestore, Cloud Functions, API Gateway, VPC, IAM + Eventarc + Secret Manager + Cloud KMS (12)
- **Azure (11 services)** — Virtual Machines, Blob Storage, SQL, Function App, API Management, Key Vault, Event Grid, Service Bus, Cosmos DB, VNet, RBAC

#### Real backend integrations (8)
- **Vault** — KMS + Secrets Manager across all 3 clouds (transit engine + KV-v2)
- **NATS** — EventBridge / Eventarc / Event Grid event delivery
- **MinIO** — S3 byte storage with write-through
- **DynamoDB Local** — transparent JSON-RPC proxy for AWS DynamoDB
- **ElasticMQ** — AWS SQS legacy XML/query protocol
- **Postgres 16** — Cloud SQL Postgres + Azure SQL + Azure Postgres flex
- **MySQL 8.0** — Cloud SQL MySQL + Azure MySQL flex
- **Cedar** — IAM policy evaluation for AWS IAM, GCP IAM bindings, Azure RBAC

#### Tier system (4 tiers, 100% backed)
- **Free / Student / Developer / Enterprise** with full server-side enforcement
- 18 enforced features (cloud_shell, cedar_enforcement, cost_simulation, terraform_export, terraform_deploy_to_real, audit_export_sinks, sso, helm, custom_domain, branding, notifications, ci_integration, cloudsim_power, cloudsim_network_sla_migration, scaffolding_generator, cross_tenant_rbac, max_seats, capacity gates)
- Pricing page at `/pricing` with side-by-side 4-tier comparison
- License signup at `/api/license/signup` with JWT issuance
- Tier middleware enforces gates on every API call

#### Multi-tenant & access control
- Tenant CRUD with structural isolation at the state-proxy layer
- **Cross-tenant RBAC** — viewer/operator/admin roles with service-scoped grants
- **SSO (OIDC)** — RS256/ES256 JWT validation against IdP JWKS for Enterprise tier
- **Custom domain** — per-tenant Host → tenant resolution in middleware
- **Per-tenant branding** — logo, colors, name override via `/api/runtime/branding/{tenant}.css`

#### Rate-limiting
- Per-tenant token bucket (Free 10rps / Student 50 / Developer 200 / Enterprise ∞)
- 429 responses with `Retry-After` + structured body

#### Operational features
- **Terraform export** — basic (Free) → full (Student/Developer) → full_plus_import (Enterprise); roundtrip cleanly
- **Terraform deploy-to-real** — single_cloud (Developer) → multi_cloud (Enterprise)
- **Helm chart** — generated on-the-fly at `/api/runtime/helm/chart.tar.gz` (Enterprise)
- **Air-gapped install bundle** — chart + image manifest + install.sh tarball
- **Audit export sinks** — webhook + file destinations for every recorded event
- **Notification channels** — webhook + Slack-compatible + email-noop
- **CI integration** — pipeline CRUD + GitHub-shaped `repository_dispatch` triggers + inbound webhook receiver
- **Scaffolding generator** — terraform/cdk/sdk-python snippets for 14 (provider, service, output) triples
- **Cloud Shell** — allow-listed bash exec for in-console diagnostics
- **CloudSim power model** — per-VM wattage + carbon-footprint estimates (Student+)
- **CloudSim network SLA + migration plan** — per-link latency + best-target/cost/downtime (Developer+)

#### Reference web apps (3-cloud matrix)
- **`tests/e2e/java-orders`** — Spring Boot, AWS, 7 services (RDS, S3, SQS, EventBridge, Secrets Mgr, KMS, IAM)
- **`tests/e2e/go-inventory`** — Go + chi, GCP, 7 services (Cloud SQL, GCS, Pub/Sub, Eventarc, Secret Mgr, Cloud KMS, IAM)
- **`tests/e2e/azure-tickets`** — Go + chi, Azure, 7 services (Postgres Flex, Blob, Service Bus, Event Grid, KV-secrets, KV-keys, RBAC) — **NEW in v1.0**

#### Conformance & CI
- `tests/conformance/run_conformance.py` — 16-check harness against real SDKs
- `--isolate-spaces` flag — provider-aware per-check space creation (closes the 82% space-context bleed gap)
- `--fail-under N` flag — CI exit-on-threshold (set to 85.0 by default)
- `.github/workflows/ci.yml` — lint + conformance + tier-middleware smoke + 3-cloud refapp build matrix
- `.github/workflows/release.yml` — tag-triggered release artifact bundle

#### Distribution
- Docker Compose stack (`docker-compose.yml`) — 13 services across 1 network
- Appliance Compose stack (`docker-compose.appliance.yml`) — Multipass VM bootstrap
- Homebrew Formula (`packaging/homebrew/Formula/cloud-learn.rb`)
- Snap package definition (`packaging/snap/snapcraft.yaml`)
- Appliance launcher (`scripts/cloud-learn up`) — bootstraps Multipass VM + deploys stack via direct `docker compose up`

#### Documentation
- `README.md` (this release) — project overview, quick start, tier system, architecture diagram
- `docs/PRODUCTION_DEPLOYMENT.md` — Vault prod-mode, backups, Helm, SSO, single-instance constraint
- `docs/RELEASE_NOTES_v1.0.md` — detailed release notes (this release)
- `docs/architecture/CLOUDLEARN_FULL_ARCHITECTURE.md` — high-level design
- `docs/architecture/CLOUDLEARN_LLD.md` — low-level component breakdown
- `docs/architecture/mvp-backend-stack.md` — 8 backend integrations + wiring conventions
- `docs/architecture/provider_gap_matrix.md` — per-service parity status

### Changed

- **Vault** — production deployment switches from `-dev` mode to file backend + idempotent init/unseal script (see `packaging/vault/`). Dev-mode remains default for local development.
- **Pricing page (`/pricing`)** — capacity numbers replaced with qualitative `workload_scale` row + host-capacity footnote (don't promise "25 VMs" if the user's laptop can't deliver them).
- **Conformance harness** — gained `--isolate-spaces` + `--fail-under` flags; CI threshold set to 85% (acknowledges known MinIO direct-read + KMS roundtrip deviations).
- **Appliance launcher** — `scripts/cloud-learn up` now deploys inner docker-compose directly instead of chaining through `cloud-learn up --detach` (closes a footgun where the chain aborted before building on some hosts).

### Fixed

- **Tier policy enforcement** — `check_feature()` is now actually called (it was defined but never invoked; this was the root cause of 7 "advertised but unbacked" features).
- **Azure VM size cap** — wired into ARM dispatcher at `providers/azure_services.py` (was missing; lingering footgun from the EC2/GCE size-cap rollout).
- **Cost simulation comment** — misleading "never denies" comment removed; matches actual behavior (Free=False → 403).
- **`/aws`, `/gcp`, `/azure` SPA paths** — were returning S3 `NoSuchBucket` XML errors due to the catch-all route; explicit 302 redirects to `/console/<provider>` shipped.

### Known limitations (v1.1 backlog)

- **Observability** — no Prometheus `/metrics`, no structured JSON logging, no distributed tracing
- **Multi-instance** — single-instance only; STATE file race conditions with > 1 instance
- **Cedar auto-enforcement** — Cedar policies are evaluated server-side but only when middleware calls `cedar_engine.evaluate()`; auto-enforce-on-every-call middleware planned for 1.1
- **Console visual polish** — Playwright e2e specs compile but unrun; visual parity with real cloud consoles is approximate (70-80% match)
- **Windows MSI installer** — referenced in INSTALL.md but build script incomplete
- **Azure SDK non-TLS** — Azure SDK Go clients refuse authenticated calls over plain HTTP (Blob, Key Vault Encrypt). Production deployments should terminate TLS in front of the simulator.
- **Cedar session pollution** — Cedar policies persist in space state; pre-existing policies from earlier sessions can bleed (CI runs against fresh stack and is unaffected)

[1.0.0]: https://github.com/vyomi-cloud/appliance/releases/tag/v1.0.0
[Unreleased]: https://github.com/vyomi-cloud/appliance/compare/v1.0.0...HEAD
