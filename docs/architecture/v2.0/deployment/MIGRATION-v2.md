# Migrating to Vyomi v2.0.0

v2.0.0 is the full vyomi-branded release. Every user-facing surface that previously said `cloudlearn` or `cloud-learn` now says `vyomi`. We shipped this as a single major version (rather than a long migration window) to draw a clean line — but with **runtime back-compat at every layer** so existing v1.x users upgrade transparently.

This guide walks through what changed, what you have to do, and what auto-migrates.

## TL;DR — what you must do

| If you're on… | Run this |
|---|---|
| Brew (existing user) | `brew upgrade cloud-learn` — keeps working forever, alias resolves to `vyomi.rb` |
| Brew (clean install) | `brew install vyomi-cloud/tap/vyomi` |
| Docker Compose (existing volumes) | `docker compose down && bash scripts/migrate-volumes-vyomi.sh && docker compose up -d` — **state preserved** |
| Multipass appliance (existing VM) | `vyomi up` or `cloud-learn up` — launcher auto-detects the old VM and reuses it |
| Scripts hard-coded to `cloud-learn ...` | Keep working unchanged via the deprecation shim through v2.x |
| Scripts reading `X-CloudLearn-*` headers | Keep working — server sends both spellings |
| Scripts reading `CLOUDLEARN_*` env vars | Keep working — runtime mirror populates both |

If you skip everything above and just do `brew upgrade cloud-learn && cloud-learn up`, the upgrade still works — you'll just see a one-line yellow deprecation warning the first time the shim fires.

## What changed, layer by layer

### 1. CLI binary — `cloud-learn` → `vyomi`

The user-typed command is now `vyomi`. The old `cloud-learn` binary still ships in every package (brew/deb/rpm/scoop) as a shim that prints a one-line yellow warning to stderr and `exec`s `vyomi` with the same args.

```bash
$ vyomi up
# (no warning, runs normally)

$ cloud-learn up
Note: `cloud-learn` is deprecated. Use `vyomi` instead. Suppress: VYOMI_NO_DEPRECATION_WARN=1
# (still runs)
```

**Action:** swap your muscle memory + scripts. Suppress the warning during the transition with `export VYOMI_NO_DEPRECATION_WARN=1`. **Removal: v3.0.**

### 2. License — MIT → BSL 1.1

v2.0.0 ships under the [Business Source License 1.1](../LICENSE) with a Vyomi-specific Additional Use Grant. **Source-available, not OSI open-source.** Auto-converts to Apache 2.0 four years after each release.

The Additional Use Grant blocks three commercial patterns:

1. Offering Vyomi as a commercial multi-cloud simulator service
2. Modifying / removing / bypassing tier-enforcement code
3. Repackaging or rebranding for commercial distribution

**Non-commercial use, internal evaluation, security review, and contributions are always permitted.** Existing forks from before v2.0.0 retain MIT under the historical commit terms.

### 3. Distribution channels — new namespaces

| Channel | Before | After |
|---|---|---|
| GitHub | `github.com/sudhirkumarganti/cloud-learn` | `github.com/vyomi-cloud/appliance` |
| Docker Hub | `gansudkum/cloud-learn` | `vyomi/appliance` |
| Brew tap | `sudhirkumarganti/tap` / formula `cloud-learn.rb` | `vyomi-cloud/tap` / formula `vyomi.rb` |
| Scoop bucket | `sudhirkumarganti/scoop-bucket` / `cloud-learn.json` | `vyomi-cloud/scoop-bucket` / `vyomi.json` (`cloud-learn.json` kept as deprecation manifest) |
| Portal | `vyomi.cloud` (unchanged) | `vyomi.cloud` |

**Action:** GitHub auto-redirects old URLs for 1+ year. Docker Hub does NOT redirect — old `gansudkum/cloud-learn:*` images keep being pulled until you switch. Brew formula `Aliases/cloud-learn` symlink means `brew install cloud-learn` works indefinitely.

### 4. HTTP headers — `X-CloudLearn-*` → `X-Vyomi-*`

14 headers renamed: `Tenant`, `Tier`, `Tier-Denied`, `Principal`, `Acting-As-Tenant`, `XTRBAC-Denied`, `Cedar-Denied`, `SSO-Denied`, `Admin-Key`, `Bridge-Token`, `CI-Secret`, `Notif-Secret`, `Sink-Secret`, `Host-OS`.

The server's ASGI middleware (`core/header_aliases.py`) bridges both spellings on every request and response. Your existing clients keep working.

**Action:** update new code to use `X-Vyomi-*`. **Removal: v3.0.**

### 5. Environment variables — `CLOUDLEARN_*` → `VYOMI_*`

69 environment variables renamed. Runtime mirror in `core/env_aliases.py` populates both spellings at server start. `docker-compose.yml` interpolations use dual fallback `${VYOMI_X:-${CLOUDLEARN_X:-default}}`. Bash launcher does the same shell-level mirror.

**Action:** rename in your `.env` files at leisure. Keep both spellings set with conflicting values? Don't — you'll get a one-line stderr warning at startup. **Removal: v3.0.**

### 6. Python modules — `core.cloudlearn_*` → `core.vyomi_*`

`core/cloudlearn_platform.py` → `core/vyomi_platform.py`. Class `CloudLearnPlatform` → `VyomiPlatform`. 14 `packs/azure/cloudlearn_azure_*_basic.py` → `packs/azure/vyomi_azure_*_basic.py`.

Back-compat re-export shims at every old import path. Class aliases `CloudLearnPlatform = VyomiPlatform`. Your existing imports work unchanged.

**Action:** update import statements when convenient. **Removal: v3.0.**

### 7. Filesystem paths — `~/.cloud-learn/` and `~/.cloudlearn/` → `~/.vyomi/`

The two legacy spellings (hyphen vs no-hyphen, used by different code paths) are unified under `~/.vyomi/`.

On first v2.0.0 boot:
1. If `~/.cloud-learn/` exists and `~/.vyomi/` doesn't → atomic `mv` + back-compat symlink
2. If `~/.cloudlearn/` exists and `~/.vyomi/` doesn't → same

**Action:** none. State migrates automatically, zero data loss. **Symlink removal: v3.0.**

### 8. Docker volumes — `cloudlearn-*` → `vyomi-*`

9 volumes renamed: `vyomi-data`, `vyomi-sql-pg`, `vyomi-sql-mysql`, `vyomi-gcs`, `vyomi-nats`, `vyomi-minio`, `vyomi-dynamodb`, `vyomi-portal-keys`, `vyomi-portal-data`. (`cloudsim-data` stays neutral.)

Docker doesn't have a `volume rename` command. **Existing users must run the migration script ONCE.**

```bash
docker compose down                          # stop the stack but keep volumes
bash scripts/migrate-volumes-vyomi.sh        # copies cloudlearn-* → vyomi-*
docker compose up -d                         # uses new vyomi-* volumes

# When happy with your data, clean up the legacy volumes:
docker volume rm cloudlearn-data cloudlearn-sql-pg cloudlearn-sql-mysql \
                 cloudlearn-gcs cloudlearn-nats cloudlearn-minio \
                 cloudlearn-dynamodb cloudlearn-portal-keys cloudlearn-portal-data
```

The migration script is idempotent + zero-loss. Legacy volumes are LEFT IN PLACE for safe rollback.

### 9. Multipass VM name — `cloudlearn-appliance` → `vyomi-appliance`

Fresh installs create a VM named `vyomi-appliance`. **Existing installs with a `cloudlearn-appliance` VM keep using the old name** — the launcher detects it via `multipass info` and avoids destroying state.

The VM name only surfaces in `multipass info <name>`. Users hit the simulator at `vyomi.local:9000` via mDNS regardless of the underlying VM identifier.

**Action:** none. State preserved.

### 10. HTTPS by default — `https://vyomi.local:9443`

First `vyomi up` (or `install.sh` curl-bash) detects missing `mkcert`, offers to install it, runs `mkcert -install` once to add a local CA to your system trust store (one sudo/UAC prompt), then generates a cert at `~/.vyomi/tls/`. A Caddy sidecar terminates TLS at `:9443` and reverse-proxies to the simulator on `:9000`.

**Result:** browser green padlock at `https://vyomi.local:9443`. No more "Not Secure" warning.

```bash
# Opt-out (HTTP only)
export VYOMI_NO_TLS=1

# Force re-issue
export VYOMI_REISSUE_TLS=1
```

HTTP on `:9000` remains reachable as a fallback for scripts that don't validate certs.

## Rollback to v1.x

If something breaks, downgrade:

```bash
brew install vyomi-cloud/tap/cloud-learn@1.2.5
# or
docker pull gansudkum/cloud-learn:1.2.5
```

Existing Docker volumes (`cloudlearn-*`) are still in place after the v2.0 migration ran — the script doesn't delete them. The launcher's path migration created a symlink at `~/.cloud-learn/` so any v1.x scripts still resolve. The biggest reversibility risk is the BSL 1.1 license change — that's irreversible going forward but doesn't affect existing forks.

## Reporting issues

Vyomi v2.0.0 issues: [github.com/vyomi-cloud/appliance/issues](https://github.com/vyomi-cloud/appliance/issues)
