# Changelog

All notable changes to CloudLearn will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.4] — 2026-06-15

URL parity: every install path now lands on `http://vyomi.local:9000`. v1.2.3 made the Multipass-based paths (Brew/.deb/.rpm/Scoop) reachable via mDNS at `vyomi.local`. This release extends the same hostname to the Docker Compose path so users never have to remember a different URL based on which install method they picked.

### Added

- **`install.sh` now adds `127.0.0.1 vyomi.local` to `/etc/hosts`** at the end of the one-liner install — idempotent (only inserts if the line is absent), interactive sudo prompt, best-effort DNS-cache flush (macOS `dscacheutil`, Linux `systemd-resolve`). Falls back to `http://localhost:9000` cleanly if the user declines sudo or `/etc/hosts` isn't writable.
- **INSTALL.md** documents the one-time hosts entry as step 5 of the quick-install flow with a "Why vyomi.local?" explainer.
- **Portal `/install` page** Docker Compose entry now has a "Step 3: One-time hosts entry so http://vyomi.local:9000 works" with copy-pasteable macOS / Linux / Windows-PowerShell commands. Step 4/5 commands updated to use the new URL.

### Fixed

- `.env.example` image pin bumped to `gansudkum/cloud-learn:1.2.4` (was 1.2.2).
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

- **`.env.example` image pin was broken.** Was `CLOUDLEARN_SIMULATOR_IMAGE=cloudlearn/simulator:1.0.0` — wrong namespace (`cloudlearn/simulator` does not exist on Docker Hub) AND stale version (months behind). Any user running `cp .env.example .env && docker compose pull` got `pull access denied`. Now pins to `gansudkum/cloud-learn:1.2.2` (the real, current image). Comment explains how to opt into rolling `:latest` updates.
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

- **Stale `depends_on "multipass" => :recommended` / `depends_on "docker" => :recommended`** in `packaging/homebrew/Formula/cloud-learn.rb`. These were invalid against casks and would fail `brew audit`; replaced with a comment that points to `maybe_install_multipass`. End users were never affected (the live formula in `sudhirkumarganti/homebrew-tap` is overwritten by `release.yml` on every tag), but the in-repo copy was misleading anyone reading the source.

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

First general-availability release. CloudLearn is a local-first multi-cloud
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

[1.0.0]: https://github.com/cloudlearn/cloud-learn/releases/tag/v1.0.0
[Unreleased]: https://github.com/cloudlearn/cloud-learn/compare/v1.0.0...HEAD
