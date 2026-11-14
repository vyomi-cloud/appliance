# v4/integrate-help-creds

Owner: Azure session (Sudhir) - Started: 2026-11-14 - Base: origin/v4-on-main (e140a833e) - Status: ready for review, not released

## Purpose
Developer access to Mesh and Nano resources: exact connection strings, a friendlier tunnel and Mesh, and a terminal guard for Mesh Codespaces.

## What is in it
| Change | Where |
|---|---|
| "Models are still being deployed" (503 + retry-after) while the Mesh model loads or is unreachable | `core/mesh_llm_gateway.py` |
| Mesh VMs show one line, `ssh <instance>.vyomi`; the tunnel fetches the Mesh VM key on first connect and its ssh config sets `User ubuntu` + that key | `wasm/vm/nano-vm-host.js`, `packaging/tunnel/bin/mesh-cli.mjs` |
| tunnel never prints a stack trace (unknown option, port in use, bad RELAY_PORT); `VYOMI_DEBUG=1` shows it | `packaging/tunnel/bin/vyomi-tunnel.mjs` |
| RDS / Cloud SQL (Postgres, MySQL) show a full connection string with the real user, password and the local port the tunnel opened | `core/db_endpoints.py` (`connection_list`), `/_vyomi/db-connect` in `core/aws_wire_router.py`, `consoles/src/common/DbConnect.jsx` |
| Non-admin Mesh Codespaces get a devcontainer with no integrated terminal; admins get `mesh-admin` (UI guard, not a security boundary) | `codespace/.devcontainer/mesh*/` (portal picks the path) |
| Account linking / reporting discussion draft | `docs/architecture/v4.0/ACCOUNT-LINKING-AND-REPORTING.md` |

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| The tunnel's existing `db-tcp` ports back the DB string; no new listeners | Opening a second set of ports | The tunnel already opens 5432/3306 (or the next free port) per database and reports it on `/health` |
| Passwords are shown | Placeholder password | Owner decision 2026-11-14: simulator credentials on the user's own sandbox; the loopback bridge does not check them |
| No string for Azure SQL and Redis/Memorystore | A string that cannot connect | Azure SQL is SQL Server behind a translator (no TDS listener); Memorystore is config-only (no Redis listener) |
| VM SSH in `nano-vm-host.js` | React offline branch | Headless 4.0 consoles are all `vyomi-substrate=nano` |

## Open issues
- [ ] Mesh `ssh <instance>.vyomi` not run against a real Mesh Codespace (key path from the tunnel help: `/root/.vyomi/instance-keys/id_ed25519` in `vyomi-mesh-simulator-1`)
- [ ] DB string not run through the real tunnel bridge to an in-browser database; psql/mysql credentials were verified on local containers
- [ ] Needs a `tunnel-v1.2.4` tag (owner) and a Mesh image release for the gateway message and devcontainers
- [ ] Redis and SQL Server would each need a wire front end in the tunnel bridge before a string can be shown

## Testing
`node wasm/relay/test-tunnel-instance-key.mjs`, `test-mesh-ssh.mjs`, `test-tunnel-k3s.mjs`, `test-tunnel-creds-sync.mjs`; `pytest tests/test_db_connect_route.py`.
