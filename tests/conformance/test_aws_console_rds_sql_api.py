"""AWS console RDS SQL routes (/api/console/rds/*): database list, execute (DDL/DML/SELECT/errors), schema."""
import os
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def J(r):
    try:
        return r.json()
    except Exception:
        return {}


def main():
    u = BASE + "/api/console/rds"
    tbl = "cm_" + uuid.uuid4().hex[:6]

    def run(sql, db=None):
        body = {"sql": sql}
        if db:
            body["db"] = db
        return requests.post(f"{u}/execute", json=body, timeout=60)

    r = requests.get(f"{u}/databases", timeout=60)
    j = J(r)
    dbs = [d.get("db_instance_identifier") for d in j.get("databases", [])]
    check("list databases has default", r.status_code == 200 and j.get("default") in dbs and j.get("count") == len(dbs), j)
    db = j.get("default", "console-db")
    d0 = j["databases"][0]
    check("database row has engine/status/endpoint", all(d0.get(k) for k in ("engine", "status", "endpoint")), d0)

    r = run(f"create table {tbl} (id integer primary key, name text)", db)
    check("execute DDL ok", r.status_code == 200 and J(r).get("ok") is True, r.text[:200])
    r = run(f"insert into {tbl} values (1,'a'),(2,'b')", db)
    check("execute insert affects 2 rows", J(r).get("ok") is True and J(r).get("rowcount") == 2, r.text[:200])
    r = run(f"select id, name from {tbl} order by id", db)
    j = J(r)
    check("select returns columns and rows", j.get("is_select") is True and j.get("columns") == ["id", "name"]
          and j.get("rows") == [[1, "a"], [2, "b"]], j)
    r = run(f"insert into {tbl} values (1,'dup')", db)
    check("constraint violation reported ok=false", J(r).get("ok") is False and "UNIQUE" in J(r).get("error", ""), r.text[:200])
    r = run("selec bad", db)
    check("syntax error reported ok=false", J(r).get("ok") is False and J(r).get("error"), r.text[:200])

    r = requests.get(f"{u}/databases/{db}/schema", timeout=60)
    j = J(r)
    t = next((t for t in j.get("tables", []) if t.get("name") == tbl), {})
    cols = {c["name"]: c for c in t.get("columns", [])}
    check("schema lists the new table and columns", r.status_code == 200 and set(cols) == {"id", "name"}, j)
    check("schema marks primary key", cols.get("id", {}).get("pk") is True and cols.get("name", {}).get("pk") is False, cols)

    run(f"drop table {tbl}", db)
    r = requests.get(f"{u}/databases/{db}/schema", timeout=60)
    check("dropped table leaves schema", tbl not in r.text, r.text[:200])

    r = requests.post(f"{u}/execute", json={}, timeout=60)
    check("execute without sql is 400", r.status_code == 400, r.status_code)
    r = requests.post(f"{u}/execute", json={"sql": "   "}, timeout=60)
    check("execute with blank sql is 400", r.status_code == 400, r.status_code)


main()
raise SystemExit(1 if failed else 0)
