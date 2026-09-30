"""Codespaces bastion helpers — SSH jump-host + DB port-forward command builders.

When the appliance runs inside a GitHub Codespace, its container ports (a compute
instance's sshd, the shared SQL engine) are NOT reachable by a remote dev's laptop
except through the Codespace acting as a jump host. These helpers build the exact
laptop-side commands the console surfaces for that.

The dev sets the jump host up ONCE per laptop:
    gh codespace ssh --config -c <codespace> >> ~/.ssh/config      # installs `cs.<name>`
Then:
  • compute  → ssh -J cs.<name> ubuntu@<instance-private-ip>       (per instance, no fwd)
  • database → ssh -fN -L <lport>:localhost:<engine-port> cs.<name>  (ONE tunnel / engine)

Substrate-free (reads only os.environ) so it's safe to import anywhere — never pulls
fastapi/boto3/psycopg2. Returns {}/None off-Codespace so callers add nothing there.
"""
from __future__ import annotations

import os


def codespace_name() -> str:
    """The GitHub-set Codespace name, or '' when not in a Codespace."""
    return (os.environ.get("CODESPACE_NAME") or "").strip()


def jump_host() -> str:
    """The SSH alias `gh codespace ssh --config` installs (empty off-Codespace)."""
    cs = codespace_name()
    return f"cs.{cs}" if cs else ""


def ssh_setup_command() -> str:
    """The one-time `gh` command that installs the jump-host alias on the laptop."""
    cs = codespace_name()
    return f"gh codespace ssh --config -c {cs} >> ~/.ssh/config" if cs else ""


# Stable, distinct local ports so a dev's own local Postgres/MySQL on 5432/3306
# isn't shadowed by the tunnel.
_LOCAL_PORT = {"postgres": 15432, "mysql": 13306}


def _is_mysql(engine: str) -> bool:
    e = (engine or "").lower()
    return e.startswith("mysql") or e.startswith("maria")


def db_tunnel(engine: str, port: int, database: str = "", user: str = "",
              password: str = "", *, target_host: str = "localhost") -> dict | None:
    """Laptop-side commands to reach a sandbox DB through the Codespace jump host.

    None off-Codespace (or when `port` is unknown). ONE tunnel per engine covers
    EVERY database on the shared SQL engine — they differ only by db/user — and it
    reuses the SAME jump host the SSH-setup banner installs, so there's no per-DB
    setup. `target_host` is resolved on the Codespace side (the shared engine
    publishes its port on the Codespace host's localhost)."""
    cs = codespace_name()
    if not cs or not port:
        return None
    jh = f"cs.{cs}"
    mysql = _is_mysql(engine)
    lport = _LOCAL_PORT["mysql" if mysql else "postgres"]
    tunnel = f"ssh -fN -L {lport}:{target_host}:{int(port)} {jh}"
    if mysql:
        client = f"mysql -h 127.0.0.1 -P {lport} -u {user} -p'{password}' {database}".rstrip()
    else:
        client = (f'psql "host=localhost port={lport} dbname={database} '
                  f'user={user} password={password}"')
    return {
        "jump_host": jh,
        "engine": "mysql" if mysql else "postgres",
        "engine_port": int(port),
        "local_port": lport,
        "tunnel_command": tunnel,
        "client_command": client,
        "note": (
            f"From your laptop: after the one-time SSH setup (installs {jh} — see the "
            f"console's “One-time SSH setup” banner), run the tunnel command and keep "
            f"it open, then connect with the client command. ONE tunnel per engine "
            f"covers every database on it — no per-database setup."
        ),
    }
