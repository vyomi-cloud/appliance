# vyomi — compiled launcher CLI

The single native binary that replaces `scripts/cloud-learn.ps1` (and the shell
launchers). It orchestrates the local multi-cloud simulator over two substrates:

- **Docker** (Free / Lite / Pro tiers) — `docker compose … -p vyomi`
- **Multipass VM** (Max tier) — an Ubuntu VM running the docker-compose stack

## Why compiled

winget rejects "scripted applications" (a wrapper that shells into an on-disk,
modifiable `.ps1` is a security risk — see PR microsoft/winget-pkgs#392224). Porting
the launcher into a compiled Go binary makes the shipped program genuine machine code
with nothing to tamper with — which satisfies the policy. Go was chosen for a single
static `.exe` (no runtime dependency), trivial `GOOS=windows GOARCH=amd64`
cross-compile, and a stdlib that maps cleanly to the launcher's work (`os/exec`,
`net/http`, `text/template`, `encoding/json`, `go:embed`).

## Build

```sh
# host
go build -o vyomi .
# the winget target
GOOS=windows GOARCH=amd64 go build -o vyomi.exe .
```

Stdlib only — no external modules.

## Status (port progress)

| Area | Status |
|---|---|
| Config / env mirroring (VYOMI_* ↔ CLOUD_LEARN_*) | ✅ |
| Substrate resolution (tier/substrate files, auto-detect) + persistence | ✅ |
| **Docker substrate** (up/down/restart/status/logs/update) | ✅ tested on real Docker |
| Inner-context compose path | ✅ |
| doctor / usage / dispatch / exit codes | ✅ |
| Host-aware VM sizing formula (+ Windows GlobalMemoryStatusEx / GetDiskFreeSpaceEx) | ✅ |
| **Multipass provisioning** (`up`/`restart`/`upgrade`): winget install, VM launch, cloud-init, manifests, ssh key, workspace tar-sync, runtime bridge systemd unit, launcher, health poll | ✅ |
| netsh localhost bridge + VBox NAT forward (user-context) + URL banner / browser open | ✅ |
| Unit tests: sizing tiers, IP selection, list parse, cloud-init + manifest generation | ✅ (6 tests) |
| VBox NAT **auto-elevation** for SYSTEM-owned VMs (Windows-Home edge) | ⏳ prints manual fallback for now |
| WiX MSI: ship `vyomi.exe` instead of `.ps1`+`.cmd`; shortcut → `vyomi.exe up` | ⏳ |
| Release pipeline: Go cross-compile → stage `vyomi.exe`; drop the PS1 | ⏳ |

## Files
- `main.go` — entry, usage, doctor, flag parsing
- `config.go` — resolved settings from env / exe location
- `substrate.go` — Docker-vs-Multipass resolution + persistence
- `docker.go` — the Docker substrate (fully ported)
- `dispatch.go` — inner/outer/multipass command routing
- `sizing.go` / `sysinfo.go` — host-aware VM sizing
- `exec.go` — external-command helpers
