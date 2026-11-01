#!/usr/bin/env python3
"""Post-create probe (offline): a managed SQL instance (RDS / Cloud SQL) must be usable from the
USER'S machine with the connection details the API/console shows.

  python3 db_connect.py aws|gcp http://localhost:9000

Create -> read the shown connection (host/port/db/user/password) -> TCP-reach it from this machine ->
connect with a real client (psql; falls back to a docker-run psql on Linux) -> create table, insert, select ->
delete -> the credentials must stop working.
One [PASS]/[FAIL] line per check, exit 1 on any failure. Findings: CONNECT_INFO_UNREACHABLE, POST_CREATE_UNUSABLE.
Run it on the machine a user would use (not inside the appliance container).
"""
import json, os, shutil, socket, subprocess, sys, time, urllib.error, urllib.request

CLOUD = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("aws", "gcp") else "aws"
BASE = (sys.argv[-1] if sys.argv[-1].startswith("http") else os.environ.get("VYOMI_ENDPOINT", "http://localhost:9000")).rstrip("/")
fails = 0


def check(ok, name, why=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {why}"), flush=True)
    fails += 0 if ok else 1
    return ok


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = r.read()
        return json.loads(d) if d else {}


def psql(conn, sql):
    env = dict(os.environ, PGPASSWORD=conn["password"], PGCONNECT_TIMEOUT="8")
    args = ["-h", conn["host"], "-p", str(conn["port"]), "-U", conn["user"], "-d", conn["database"], "-tA", "-c", sql]
    if shutil.which("psql"):
        cmd = ["psql", *args]
    elif shutil.which("docker") and sys.platform.startswith("linux"):
        cmd = ["docker", "run", "--rm", "--network", "host", "-e", "PGPASSWORD", "-e", "PGCONNECT_TIMEOUT",
               "postgres:16-alpine", "psql", *args]
    else:
        return 127, "", "no psql client available on this machine"
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def main():
    name = f"pc-db-{int(time.time()) % 100000}"
    delete = conn = None
    try:
        if CLOUD == "aws":
            call("POST", "/api/rds/databases", {"db_instance_identifier": name, "engine": "postgres", "db_instance_class": "db.t3.micro",
                                                "master_username": "admin", "master_user_password": "Passw0rd123", "allocated_storage": 20})
            delete = lambda: call("DELETE", f"/api/rds/databases/{name}")
            for _ in range(60):
                d = call("GET", f"/api/rds/databases/{name}"); d = d.get("db") or d
                if d.get("status") == "available":
                    break
                time.sleep(2)
            check(d.get("status") == "available", "RDS instance becomes available", f"status={d.get('status')}")
            check(d.get("runtime_backend") in ("real-pg", "real-mysql"), "backed by a real engine, not a simulated record (POST_CREATE_UNUSABLE)",
                  f"runtime_backend={d.get('runtime_backend')} endpoint={d.get('endpoint_address')}")
            conn = d.get("connection")
        else:
            proj = call("GET", "/v1/projects")["projects"][0]["projectId"]
            base = f"/sql/v1beta4/projects/{proj}/instances"
            call("POST", base, {"name": name, "databaseVersion": "POSTGRES_15", "region": "us-central1",
                                "settings": {"tier": "db-f1-micro"}, "rootPassword": "Passw0rd123"})
            delete = lambda: call("DELETE", f"{base}/{name}")
            for _ in range(60):
                d = call("GET", f"{base}/{name}")
                if d.get("state") == "RUNNABLE":
                    break
                time.sleep(2)
            check(d.get("state") == "RUNNABLE", "Cloud SQL instance becomes RUNNABLE", f"state={d.get('state')}")
            conn = d.get("connection")
        if not check(bool(conn and conn.get("host") and conn.get("port")), "connection details are shown (CONNECT_INFO_MISSING)", f"connection={conn}"):
            return
        try:
            socket.create_connection((conn["host"], int(conn["port"])), timeout=6).close(); ok, why = True, ""
        except OSError as e:
            ok, why = False, f"{conn['host']}:{conn['port']} -> {e}"
        if not check(ok, "shown host:port reachable from the user's machine (CONNECT_INFO_UNREACHABLE)", why):
            return
        rc, out, err = psql(conn, "create table pc(x int); insert into pc values (42); select x from pc;")
        check(rc == 0 and out.splitlines()[-1:] == ["42"], "real client: create table, insert, select (POST_CREATE_UNUSABLE)", f"rc={rc} {err[-160:]} out={out[-60:]}")
    finally:
        if delete:
            try:
                delete()
            except Exception as e:
                print(f"[note] cleanup failed: {e}", flush=True)
            if conn:
                time.sleep(3)
                rc, out, err = psql(conn, "select 1")
                check(rc != 0, "after delete the credentials stop working (no leaked database)", f"still connects: {out}")


try:
    main()
except Exception as e:  # noqa: BLE001
    check(False, "probe ran without error", repr(e)[:300])
sys.exit(1 if fails else 0)
