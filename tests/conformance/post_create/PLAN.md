# Post-create "use it" checks (offline + Nano)

Status: PLAN (nothing below is built yet). Owner: conformance cycle. Drafted 2026-11-02.

## Why
The crawler's create-with-defaults only proves a row appears, no cell is a placeholder and the
cost-savings counter moved. It never proves the resource WORKS. Found by hand on 2026-11-01: an
EC2 instance showed "running", yet SSH from the user's machine failed (no key pair, and the console's
`ssh_command` pointed at a Docker-internal IP `172.18.0.21` and an in-container key path). The crawler passed it.
Rule: **a created resource must be usable through the access path the console shows the user.**
A failed probe is a PRODUCT bug (fix console/API/backend), never the test.

## What a probe is
One per service+cloud, run against the resource the crawler just created (or created by the SDK/CLI
in the probe itself), using ONLY what a user sees: the endpoint/host/port/credentials/command the
console displays, and the official native client. Steps: connect -> do one real operation -> read it back -> delete.
A probe that needs a value the console does not show is a finding ("CONNECT_INFO_MISSING"). A shown value
that does not work from the user's machine (internal IPs, container-only paths) is "CONNECT_INFO_UNREACHABLE".

## Probe catalogue (first slice in bold)
| Service | Offline probe | Nano probe |
|---|---|---|
| **EC2 / GCE / Azure VM** | SSH from the HOST using the console's command (host:published port, key the user can obtain); `whoami` + write/read a file; with a launch-time key pair, that key must work | REQUIRED: the Nano console's Connect/terminal into the instance VM (v86) runs `whoami` + write/read a file, using the connect info Nano shows. Until in-browser compute exists the probe is PENDING (red), not N/A |
| **RDS / Cloud SQL / Azure SQL** | connect with shown endpoint+creds via native driver; create table, insert, select | PGlite/in-browser engine: same SQL via the Nano endpoint |
| **S3 / GCS / Blob** | put, get, list, delete via native SDK at the shown endpoint | same via the relay endpoint |
| **Lambda / Functions** | invoke, assert payload + log line | REQUIRED: invoke through the Nano endpoint, assert payload + log line (in-browser runtime; PENDING until it exists) |
| DynamoDB / Firestore / Cosmos | write item, read back, query | same |
| SQS+SNS / Pub/Sub / Service Bus-Queue | publish, receive, ack | same |
| KMS / Secrets / Key Vault | encrypt-decrypt round trip / put-get secret | same |
| (rest) | add as services are touched; the expansion gate requires a probe for every new service | |

## Where it lives
- `tests/conformance/post_create/probes/<cloud>/<service>.{py,mjs}` + `probes.json` (service -> probe, target support, N/A reason).
- Runner `post_create.mjs`: reuses the crawler's create-with-defaults to make the resource, reads the connect
  info FROM THE PAGE, runs the probe, prints one `[PASS]/[FAIL]` line per step, exits 1 on any failure.
- Both targets are mandatory per probe: `probes.json` has `offline` and `nano` entries for every service, each `ready`, `pending` (with dependency) or `na` (with `why`). A service with a missing entry fails the expansion gate.
- Suites (added to `suites.json` only when they exist and pass locally): `offline-post-create`, `nano-post-create`
  (per cloud; the Nano suite is added in the same change as its offline twin, with PENDING probes listed in the report). Nano twin built on `wasm/ui-tests/lib.mjs` (`bootConsole`).
- New findings types surfaced into ui-findings.json: `POST_CREATE_UNUSABLE`, `CONNECT_INFO_MISSING`, `CONNECT_INFO_UNREACHABLE`.
- Expansion gate (`tests/conformance/expansion/gate.py`): a new service must declare a probe or an explicit N/A with a `why`.

## Cadence: these run in the cycle, over and over
Not a one-off. Post-create probes are ordinary suites in `tests/conformance/hourly/suites.json`, so they run in
EVERY conformance cycle (`conformance-hourly.yml`, restarted back-to-back by `conformance-watchdog.yml` after
`CONFORMANCE_COOLDOWN_MIN`), on both targets, split across the 6 detect shards like the crawler.
- **Every cycle:** the full probe set for the shard's services (create -> use -> read back -> delete), so a regression
  in any service's usability shows up within one cycle, not at release.
- **Daily:** the same probes in the 23:45 IST daily-PR window plus the slow ones (EC2 SSH with a launch-time key pair,
  RDS restart-then-reconnect, Lambda cold start), and the release gate (`release-checks.yml`) must see them green
  or explicitly `pending`/`na` with a reason.
- **Over time:** results append to `history.json`; a probe that was green and goes red is a regression finding
  (like a `removed` feature), and `pending` probes are listed in every report until they turn green, so nothing hides.
- Probes clean up after themselves (delete what they created) so repeated cycles do not leak containers or disk.

## Phases
1. **EC2 SSH (offline, AWS)** - DONE 2026-11-02 (probe `probes/vm_ssh.py`, suite `offline-post-create-aws-ec2-ssh`; failed on v3.0.38 with `ssh ... ubuntu@172.18.0.x`, passes with the server.py fix; Nano twin `wasm/ui-tests/validate-aws-post-create-ec2.mjs` written and registered `pending` - fails today: connect-info 409 NoRuntime, /exec 501). Was: known failing today. Fix: console shows a host-reachable command
   (`127.0.0.1:<ssh_host_port>`), a way to get the key, and key-pair public keys injected at launch. Probe + suite.
2. **S3 put/get, RDS connect/CRUD, Lambda invoke (offline, AWS)**.
3. **Same slice on GCP and Azure.** VM SSH DONE 2026-11-02 (`vm_ssh.py gcp|azure`, suites `offline-post-create-gcp-gce-ssh` / `-azure-vm-ssh`). Found + fixed: GCE connect-info 404, GCE Connect tab showing `ssh $USER@localhost`, GCE delete leaking the container, Azure ARM VMs having no runtime at all (now Docker-backed). Nano twins for GCE/Azure still to write (pending). Managed SQL DONE 2026-11-02 for RDS + Cloud SQL (`db_connect.py aws|gcp`): the shipped compose did not publish the SQL ports, so every endpoint was unreachable from the user's machine; now published on loopback (15432/13306, override VYOMI_PG_PORT/VYOMI_MYSQL_PORT). KNOWN GAP: Azure SQL (`Microsoft.Sql/servers`) only has an HTTP endpoint (`/azure-data/sql/<server>`), no TDS/wire protocol, so sqlcmd/JDBC/ODBC cannot connect; needs a SQL Server-compatible engine (decision pending: the amd64-only SQL Server image was rejected before). Still open here: GCS, Blob, MySQL engines.
4. **Nano twin, built alongside each offline probe (not after):** the same probe against the Nano endpoint for everything Nano runs (S3, DynamoDB, KMS, Secrets, SQS/SNS, RDS->PGlite). Compute/Lambda probes are written now and stay PENDING until the in-browser runtime lands; that dependency is a tracked backlog item, not a skip.
5. Remaining services; make "has a probe or a justified N/A" a hard gate for the nightly report.

## Honest limits
- Both targets are REQUIRED for every probe. Nano cannot do real SSH/ports yet, so those probes are PENDING: reported as failing-by-design with the missing dependency named, and picked up by the fixers. N/A is allowed only where the real cloud has no equivalent, with a `why` that a reviewer can check. Never silently green.
- Probes must not seed data the user could not create through the console/SDK, and never relax a check to pass.
- Disk/time: probes create+delete their own resources; sharded like the crawler so the hourly budget holds.
