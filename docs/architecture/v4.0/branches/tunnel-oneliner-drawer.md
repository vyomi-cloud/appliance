# Branch: v4/tunnel-oneliner-drawer

**Goal:** a brand-new user can set up the local `vyomi-tunnel` (required by Mesh) without npm, Homebrew, a terminal-savvy setup, or copying a key.

## Architecture
- Portal (`vyomi-cloud/portal`, branch `feat/tunnel-oneliner-mac`): `app/tunnel_pair.py` issues a single-use, 15-minute pairing code bound to the signed-in account (stored as a SHA-256 hash). `GET /i/<code>` serves `app/install/mac.sh`; `POST /api/tunnel/pair/redeem` creates the access key FOR THE CODE'S ACCOUNT; `progress`/`status` endpoints feed the UI.
- Installer (macOS): private Node (SHA-256 verified against nodejs.org) + `npm i vyomi-tunnel` into `~/.vyomi`; writes `~/.vyomi/credentials` (600); LaunchAgent `cloud.vyomi.tunnel` (RunAtLoad + KeepAlive); `~/.vyomi/uninstall.sh`. No admin rights, no signing (curl-fetched files carry no quarantine flag).
- This repo: `wasm/mesh-widget.js`. The Mesh card shows only a **Setup Tunnel** button when the tunnel is down; the dialog generates the command and follows the installer's steps. Close is available at all times (X, footer button, Esc, click outside); closing mid-install keeps the install and its progress polling going and reopening resumes it, while closing after success/failure/expiry resets so the next open gets a fresh single-use command. Non-Mac systems get the brew/npm commands in the same dialog. Vendored one-way to the portal (`app/nano/mesh-widget.js`).

## Decisions
- Wrong-account tunnel keys (the 2026-11-14 HTTP 502 root cause) are impossible by construction: the key is minted for whoever created the link.
- A native signed app/supervisor is a later phase (Apple $99/yr; Windows Artifact Signing or SSL.com eSigner); the one-liner needs no signing.
- At the 2-key limit only a previous "installer" key is rotated; the user's own keys are never revoked.

## Open issues
- Windows (PowerShell) and Linux installers are not built; only macOS shows the dialog's one-command flow.
- Start/Stop/Restart controls in the drawer (local relay endpoints) are not built.
- Not yet tested in a real browser on a Mac with no Node/Homebrew; the "stop an already-running tunnel on :8090" branch of the script is untested.


## Windows and Linux (added 2026-11-14)
- Widget `osKind()` picks mac|windows|linux (phones/ChromeOS keep the brew/npm steps); requests `platform` accordingly; dialog says PowerShell / Terminal / a terminal.
- Portal serves `linux.sh` (systemd user service, nohup fallback) and `win.ps1` (`irm <portal>/i/<code> | iex`; Scheduled Task at logon + hidden run.cmd restart loop; never calls `exit`, since iex would close the window). Refusals are PowerShell-valid when the User-Agent says PowerShell.
- Verified: Linux e2e in a clean Debian container (nohup path). NOT verified: Linux systemd path, any Windows run (script only reviewed, no PowerShell available here).
