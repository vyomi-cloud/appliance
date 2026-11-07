# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure SQL security features run against the REAL SQL engine behind the database (sqlite3 in Nano; Postgres
behind the same SqlStore seam offline).  Substrate-free (stdlib only -> loads under Pyodide).  Called from
core/azure_sql_core._query / dispatch, which hands over the ARM state snapshot (masking policy + rules, sensitivity
labels, isLedgerOn) and the Key Vault keys store.

Data Discovery & Classification   ``discover`` scans the database's REAL tables: a column-NAME pattern engine plus a
                                  sample-DATA engine (email / phone / SSN / credit-card-with-Luhn / IPv4 over up to 200
                                  real rows).  Labels persist as ARM sensitivityLabels children; every SELECT that reads a
                                  labelled column writes ``dataSensitivityInformation`` into the audit record (what real
                                  SQL Audit's ``data_sensitivity_information`` carries).
Dynamic Data Masking              the dataMaskingPolicies/Default rules are APPLIED to result sets for any login that is
                                  not the server admin, not in exemptPrincipals and has not been granted UNMASK
                                  (``GRANT UNMASK TO user`` / ``REVOKE UNMASK FROM user`` are real statements here).
                                  Functions: Default, Email, Number (random in range), Text/Custom (partial), CCN, SSN.
                                  Like the real feature only DIRECT column references are masked (not expressions), and the
                                  stored data is untouched.  Login = ``x-vyomi-sql-login`` header (absent = admin).
Ledger                            ``CREATE TABLE ... WITH (LEDGER = ON [(APPEND_ONLY = ON)])`` (every table when the
                                  database was created with isLedgerOn).  Append-only tables reject UPDATE / DELETE /
                                  TRUNCATE (error 37359).  Every write appends a block to a SHA-256 hash chain
                                  (stored IN the database) carrying the table-state hash; row versions go to a ledger
                                  history; ``digest`` captures the chain head and ``verify`` recomputes the chain, the
                                  digests and each table's current state - tampering outside the ledger path is detected.
                                  Digests are returned/stored in the database, not uploaded to immutable blob storage.
Always Encrypted                  column master key (an Azure Key Vault key, validated + used through the Key Vault keys
                                  core) -> column encryption key (CEK, wrapped by Key Vault wrapKey) -> encrypted columns,
                                  Deterministic (equality works) or Randomized.  The server stores CIPHERTEXT only.  The
                                  client-side driver is EMULATED in the simulator's query path: with
                                  ``columnEncryptionSetting: Enabled`` (body field) it encrypts parameters bound to
                                  encrypted columns and decrypts result columns (unwrapping the CEK through Key Vault, so a
                                  disabled CMK stops decryption); without it the server sees/returns ciphertext and
                                  plaintext writes are rejected.  Server-side LIKE / range / randomized equality on an
                                  encrypted column is rejected as real SQL Server does.  Enclaves are not modelled.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import re
import time

HIDDEN_PREFIX = "__vyomi_"
GENESIS = "0" * 64
_SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SecError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ═════════════════════════ engine helpers ═════════════════════════
def _x(store, db_id, sql, params=None):
    return store.execute_sql(db_id, sql, params)


def user_tables(store, db_id):
    try:
        r = _x(store, db_id, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        names = [row[0] for row in r["rows"]]
    except Exception:
        r = _x(store, db_id, "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1")
        names = [row[0] for row in r["rows"]]
    return [n for n in names if not n.startswith(HIDDEN_PREFIX)]


def table_columns(store, db_id, table):
    if not _SAFE.match(table or ""):
        return []
    try:
        r = _x(store, db_id, f'PRAGMA table_info("{table}")')
        cols = [row[1] for row in r["rows"]]
        if cols:
            return cols
    except Exception:
        pass
    try:
        r = _x(store, db_id, "SELECT column_name FROM information_schema.columns WHERE table_name=? ORDER BY ordinal_position", [table])
        return [row[0] for row in r["rows"]]
    except Exception:
        return []


def _ensure(store, db_id, name, ddl):
    flag = getattr(store, "_azure_sql_sec_init", None)
    if flag is None:
        flag = store._azure_sql_sec_init = set()
    if (db_id, name) in flag:
        return
    _x(store, db_id, ddl)
    flag.add((db_id, name))


def _hidden_exists(store, db_id, name):
    flag = getattr(store, "_azure_sql_sec_init", None)
    if flag is not None and (db_id, name) in flag:
        return True
    full = HIDDEN_PREFIX + name
    try:
        r = _x(store, db_id, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [full])
    except Exception:
        r = _x(store, db_id, "SELECT 1 FROM information_schema.tables WHERE table_name=?", [full])
    if r["rows"]:
        if flag is None:
            flag = store._azure_sql_sec_init = set()
        flag.add((db_id, name))
        return True
    return False


def forget(store, db_id):
    flag = getattr(store, "_azure_sql_sec_init", None)
    if flag:
        for k in [k for k in flag if k[0] == db_id]:
            flag.discard(k)


def _real_table(table):
    return (table or "").strip().strip('[]"`').split(".")[-1].strip('[]"`')


# ═════════════════════════ ARM snapshot lookups ═════════════════════════
def _db_prefix(server, database):
    return f"/servers/{server}/databases/{database}".lower()


def _recs(arm_state, server, database, type_suffix):
    pre = _db_prefix(server, database)
    for rec in (arm_state or {}).values():
        t = str(rec.get("_type") or "").lower()
        rid = str(rec.get("id") or "").lower()
        if t.endswith(type_suffix) and pre in rid:
            yield rec


def database_props(arm_state, server, database):
    for rec in (arm_state or {}).values():
        if str(rec.get("_type") or "").lower() == "microsoft.sql/servers/databases" and str(rec.get("id") or "").lower().endswith(_db_prefix(server, database)):
            return rec.get("properties") or {}
    return {}


def admin_login(arm_state, server):
    for rec in (arm_state or {}).values():
        if str(rec.get("_type") or "").lower() == "microsoft.sql/servers" and str(rec.get("id") or "").lower().endswith(f"/servers/{server}".lower()):
            return (rec.get("properties") or {}).get("administratorLogin")
    return None


def labels_for(arm_state, server, database):
    out = {}
    for rec in _recs(arm_state, server, database, "/sensitivitylabels"):
        m = re.search(r"/tables/([^/]+)/columns/([^/]+)/sensitivitylabels/", str(rec.get("id") or ""), re.I)
        p = rec.get("properties") or {}
        if m and not p.get("isDisabled"):
            out[(m.group(1).lower(), m.group(2).lower())] = {"table": m.group(1), "column": m.group(2), "labelName": p.get("labelName"),
                                                             "informationType": p.get("informationType"), "rank": p.get("rank")}
    return out


def masking_policy(arm_state, server, database):
    """(enabled, exempt set, [rule dict]) from dataMaskingPolicies/Default and its rules."""
    enabled, exempt, rules = False, set(), []
    for rec in _recs(arm_state, server, database, "/datamaskingpolicies"):
        p = rec.get("properties") or {}
        enabled = str(p.get("dataMaskingState") or "").lower() == "enabled"
        exempt = {x.strip().lower() for x in str(p.get("exemptPrincipals") or "").split(";") if x.strip()}
    for rec in _recs(arm_state, server, database, "/datamaskingpolicies/rules"):
        p = rec.get("properties") or {}
        if str(p.get("ruleState") or "Enabled").lower() == "enabled" and p.get("tableName") and p.get("columnName"):
            rules.append(p)
    return enabled, exempt, rules


# ═════════════════════════ Data Discovery & Classification ═════════════════════════
NAME_PATTERNS = [
    (re.compile(r"e_?mail", re.I), "Contact Info", "Confidential", "Medium"),
    (re.compile(r"phone|mobile|fax", re.I), "Contact Info", "Confidential", "Medium"),
    (re.compile(r"address|street|zip|postal", re.I), "Contact Info", "Confidential", "Medium"),
    (re.compile(r"ssn|social_?sec|national_?id|passport", re.I), "National ID", "Highly Confidential", "High"),
    (re.compile(r"credit|card_?n|cvv|iban|account_?n", re.I), "Credit Card", "Highly Confidential", "Critical"),
    (re.compile(r"passw|pwd|secret|token", re.I), "Credentials", "Highly Confidential", "Critical"),
    (re.compile(r"first_?name|last_?name|full_?name|surname", re.I), "Name", "Confidential - GDPR", "Medium"),
    (re.compile(r"birth|dob", re.I), "Date Of Birth", "Confidential - GDPR", "Medium"),
    (re.compile(r"salary|wage|income|totaldue|price", re.I), "Financial", "Confidential", "Low"),
]


def _luhn(s):
    d = [int(c) for c in re.sub(r"\D", "", s)]
    if not 13 <= len(d) <= 19:
        return False
    tot = 0
    for i, n in enumerate(reversed(d)):
        if i % 2:
            n *= 2
            n = n - 9 if n > 9 else n
        tot += n
    return tot % 10 == 0


DATA_PATTERNS = [   # (info type, label, rank, predicate)
    ("Contact Info", "Confidential", "Medium", lambda v: re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", v) is not None),
    ("National ID", "Highly Confidential", "High", lambda v: re.fullmatch(r"\d{3}-\d{2}-\d{4}", v) is not None),
    ("Credit Card", "Highly Confidential", "Critical", lambda v: re.fullmatch(r"[\d \-]{13,23}", v) is not None and _luhn(v)),
    ("Contact Info", "Confidential", "Medium", lambda v: re.fullmatch(r"\+?[\d\s().\-]{9,18}", v) is not None and len(re.sub(r"\D", "", v)) >= 9
        and re.fullmatch(r"[\d \-]{13,23}", v) is None),
    ("Network", "Confidential", "Low", lambda v: re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", v) is not None),
]


def discover(store, db_id, arm_state=None, server=None, database=None, sample=200):
    """Scan every user table: per column -> {table, column, type, current label, recommendation{informationType,labelName,rank,source,
    matchRatio,sampled}}.  `source` is 'data' (values matched) or 'name' (column-name pattern)."""
    labels = labels_for(arm_state, server, database) if arm_state is not None else {}
    out = []
    for t in user_tables(store, db_id):
        if not _SAFE.match(t):
            continue
        cols = table_columns(store, db_id, t)
        try:
            rows = _x(store, db_id, f'SELECT * FROM "{t}" LIMIT {int(sample)}')["rows"]
        except Exception:
            rows = []
        for i, c in enumerate(cols):
            vals = [str(r[i]) for r in rows if i < len(r) and r[i] is not None and str(r[i]) != ""]
            rec = None
            if vals:
                for info, label, rank, pred in DATA_PATTERNS:
                    hit = sum(1 for v in vals if pred(v))
                    if hit / len(vals) >= 0.6:
                        rec = {"informationType": info, "labelName": label, "rank": rank, "source": "data",
                               "matchRatio": round(hit / len(vals), 2), "sampled": len(vals)}
                        break
            if rec is None:
                for rx, info, label, rank in NAME_PATTERNS:
                    if rx.search(c):
                        rec = {"informationType": info, "labelName": label, "rank": rank, "source": "name", "matchRatio": None, "sampled": len(vals)}
                        break
            cur = labels.get((t.lower(), c.lower()))
            out.append({"table": t, "column": c, "label": cur, "recommendation": rec})
    return {"columns": out, "classified": sum(1 for o in out if o["label"]),
            "recommended": sum(1 for o in out if o["recommendation"] and not o["label"])}


# ═════════════════════════ SQL parsing (just enough for the features above) ═════════════════════════
_SELECT_RE = re.compile(r"^\s*select\b", re.I)
_FROM_RE = re.compile(r"\b(?:from|join)\s+([\[\]\w.\"`]+)(?:\s+(?:as\s+)?(?!(?:where|join|inner|left|right|full|cross|on|group|order|limit|union|having)\b)(\w+))?", re.I)
_REF_RE = re.compile(r"^(?:([\[\]\w\"`]+)\.)?([\[\]\w\"`]+)(?:\s+(?:as\s+)?([\[\]\w\"`]+))?$", re.I)


def _split_top(s, sep=","):
    out, depth, cur, q = [], 0, "", None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


def _unq(x):
    return (x or "").strip().strip('[]"`')


def select_sources(store, db_id, sql, result_columns):
    """For a SELECT: [(table|None, column|None)] aligned with result_columns (a direct column reference gives its source;
    an expression gives (None, None))."""
    if not _SELECT_RE.match(sql):
        return [(None, None)] * len(result_columns)
    body = sql.strip().rstrip(";")
    low = body.lower()
    # top-level FROM
    depth, idx = 0, -1
    for i, ch in enumerate(body):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and low[i:i + 6] == " from " or (depth == 0 and low[i:i + 5] == "\nfrom"):
            idx = i
            break
    if idx < 0:
        return [(None, None)] * len(result_columns)
    sel = re.sub(r"^\s*select\s+(distinct\s+|all\s+)?(top\s*\(?\d+\)?\s+)?", "", body[:idx], flags=re.I)
    aliases, tables = {}, []
    for m in _FROM_RE.finditer(body[idx:]):
        t = _real_table(m.group(1))
        if m.group(2):
            aliases[m.group(2).lower()] = t
        aliases[t.lower()] = t
        tables.append(t)
    tcols = {t: table_columns(store, db_id, t) for t in set(tables)}
    srcs = []
    for item in _split_top(sel):
        item = item.strip()
        m = _REF_RE.match(item)
        if item == "*" or (item.endswith(".*") and _REF_RE.match(item[:-2] + ".x")):
            tabs = [aliases.get(_unq(item[:-2]).lower(), _unq(item[:-2]))] if item != "*" else tables
            for t in tabs:
                srcs += [(t, c) for c in tcols.get(t, table_columns(store, db_id, t))]
        elif m and not re.match(r"^\d", item):
            q, c = _unq(m.group(1)), _unq(m.group(2))
            t = aliases.get(q.lower()) if q else None
            if t is None:
                t = next((tb for tb in tables if c.lower() in [x.lower() for x in tcols.get(tb, [])]), tables[0] if tables else None)
            srcs.append((t, c))
        else:
            srcs.append((None, None))
    return srcs if len(srcs) == len(result_columns) else [(None, None)] * len(result_columns)


# ═════════════════════════ Dynamic Data Masking ═════════════════════════
def _partial(v, prefix, pad, suffix):
    s = str(v)
    prefix, suffix = max(0, int(prefix or 0)), max(0, int(suffix or 0))
    if prefix + suffix >= len(s):
        return pad if (prefix + suffix) else pad
    return s[:prefix] + pad + (s[len(s) - suffix:] if suffix else "")


def mask_value(rule, v, rng=random):
    if v is None:
        return None
    fn = str(rule.get("maskingFunction") or "Default")
    if fn == "Email":
        s = str(v)
        return (s[0] if s else "X") + "XXX@XXXX.com"
    if fn == "CCN":
        return _partial(v, 0, "XXXX-XXXX-XXXX-", 4)
    if fn == "SSN":
        return _partial(v, 0, "XXX-XX-", 4)
    if fn in ("Text", "Custom"):
        return _partial(v, rule.get("prefixSize"), rule.get("replacementString") or "XXXX", rule.get("suffixSize"))
    if fn == "Number":
        lo, hi = rule.get("numberFrom"), rule.get("numberTo")
        if lo is not None and hi is not None:
            lo, hi = int(lo), int(hi)
            return rng.randint(min(lo, hi), max(lo, hi))
        return 0
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        return 0
    s = str(v)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T].*)?", s):
        return "1900-01-01 00:00:00.0000000" if len(s) > 10 else "1900-01-01"
    return "X" * min(4, len(s)) if s else s


def _perms_ensure(store, db_id):
    _ensure(store, db_id, "perms", f"CREATE TABLE IF NOT EXISTS {HIDDEN_PREFIX}perms (principal TEXT, permission TEXT)")


def has_unmask(store, db_id, login):
    _perms_ensure(store, db_id)
    r = _x(store, db_id, f"SELECT 1 FROM {HIDDEN_PREFIX}perms WHERE lower(principal)=? AND permission='UNMASK'", [login.lower()])
    return bool(r["rows"])


_GRANT_RE = re.compile(r"^\s*(grant|revoke)\s+unmask\s+(?:to|from|on\s+\S+\s+to|on\s+\S+\s+from)\s+\[?([\w@.\-]+)\]?\s*;?\s*$", re.I)


def handle_permission(store, db_id, sql, is_admin):
    """GRANT/REVOKE UNMASK.  Returns a result dict or None when `sql` is not such a statement."""
    m = _GRANT_RE.match(sql)
    if not m:
        return None
    if not is_admin:
        raise SecError(403, "PermissionDenied", "The user does not have permission to perform this action (GRANT/REVOKE UNMASK requires CONTROL).")
    _perms_ensure(store, db_id)
    who = m.group(2)
    _x(store, db_id, f"DELETE FROM {HIDDEN_PREFIX}perms WHERE lower(principal)=? AND permission='UNMASK'", [who.lower()])
    if m.group(1).lower() == "grant":
        _x(store, db_id, f"INSERT INTO {HIDDEN_PREFIX}perms (principal, permission) VALUES (?, 'UNMASK')", [who])
    return {"columns": [], "rows": [], "rowCount": 0}


def apply_masking(store, db_id, arm_state, server, database, sql, result, login, is_admin):
    """Mask the result set in place for non-privileged logins.  Returns the list of masked column names."""
    if is_admin or not result.get("rows"):
        return []
    enabled, exempt, rules = masking_policy(arm_state, server, database)
    if not enabled or not rules or login.lower() in exempt or has_unmask(store, db_id, login):
        return []
    by = {(_real_table(r["tableName"]).lower(), _unq(r["columnName"]).lower()): r for r in rules}
    srcs = select_sources(store, db_id, sql, result["columns"])
    plan = {}
    for i, (t, c) in enumerate(srcs):
        if t and c and (t.lower(), c.lower()) in by:
            plan[i] = by[(t.lower(), c.lower())]
    if not plan:
        return []
    result["rows"] = [[mask_value(plan[i], v) if i in plan else v for i, v in enumerate(row)] for row in result["rows"]]
    return [result["columns"][i] for i in plan]


# ═════════════════════════ audit: data sensitivity information ═════════════════════════
def sensitivity_for(store, db_id, arm_state, server, database, sql, result):
    labels = labels_for(arm_state, server, database)
    if not labels or not _SELECT_RE.match(sql):
        return None
    hit = []
    for t, c in select_sources(store, db_id, sql, result.get("columns", [])):
        if t and c and (t.lower(), c.lower()) in labels:
            lb = labels[(t.lower(), c.lower())]
            hit.append({"schemaName": "dbo", "tableName": lb["table"], "columnName": lb["column"], "label": lb["labelName"],
                        "informationType": lb["informationType"], "rank": lb["rank"]})
    return hit or None


# ═════════════════════════ Ledger ═════════════════════════
_L = HIDDEN_PREFIX + "ledger_"
_CREATE_RE = re.compile(r"^\s*create\s+table\s+(?:if\s+not\s+exists\s+)?([\[\]\w.\"`]+)(.*)$", re.I | re.S)
_LEDGER_WITH_RE = re.compile(r"\)\s*with\s*\(\s*(system_versioning\s*=\s*on[^)]*\)?\s*,\s*)?ledger\s*=\s*on\s*(\(\s*append_only\s*=\s*(on|off)\s*(?:,[^)]*)?\))?\s*\)\s*;?\s*$", re.I)
_WRITE_RE = re.compile(r"^\s*(insert\s+(?:or\s+\w+\s+)?into|update|delete\s+from|replace\s+into|truncate\s+table)\s+([\[\]\w.\"`]+)", re.I)


def _ledger_ensure(store, db_id):
    _ensure(store, db_id, "ledger_tables", f"CREATE TABLE IF NOT EXISTS {_L}tables (table_name TEXT PRIMARY KEY, append_only INTEGER, created_ts TEXT)")
    _ensure(store, db_id, "ledger_blocks", f"CREATE TABLE IF NOT EXISTS {_L}blocks (block_id INTEGER PRIMARY KEY, prev_hash TEXT, ts TEXT, table_name TEXT, op TEXT, "
                                           "stmt_hash TEXT, state_hash TEXT, row_changes INTEGER, hash TEXT)")
    _ensure(store, db_id, "ledger_history", f"CREATE TABLE IF NOT EXISTS {_L}history (seq INTEGER PRIMARY KEY, block_id INTEGER, table_name TEXT, operation TEXT, row_json TEXT)")
    _ensure(store, db_id, "ledger_digests", f"CREATE TABLE IF NOT EXISTS {_L}digests (digest_id INTEGER PRIMARY KEY, block_id INTEGER, hash TEXT, ts TEXT, digest_time TEXT)")


def ledger_tables(store, db_id, create=True):
    if not create and not _hidden_exists(store, db_id, "ledger_tables"):
        return {}
    _ledger_ensure(store, db_id)
    return {r[0].lower(): {"name": r[0], "appendOnly": bool(r[1]), "created": r[2]}
            for r in _x(store, db_id, f"SELECT table_name, append_only, created_ts FROM {_L}tables")["rows"]}


def _canon_rows(rows):
    return sorted(json.dumps(list(r), default=str, sort_keys=True) for r in rows)


def table_state_hash(store, db_id, table):
    rows = _x(store, db_id, f'SELECT * FROM "{table}"')["rows"]
    return hashlib.sha256("\n".join(_canon_rows(rows)).encode()).hexdigest()


def _block_hash(prev, bid, ts, table, op, stmt_hash, state_hash):
    return hashlib.sha256(f"{prev}|{bid}|{ts}|{table}|{op}|{stmt_hash}|{state_hash}".encode()).hexdigest()


def ledger_pre(store, db_id, arm_state, server, database, sql):
    """Before a statement runs.  Returns (sql_to_run, ctx) or raises SecError.  ctx carries the table snapshot for write capture."""
    ledger_db = bool(database_props(arm_state, server, database).get("isLedgerOn"))
    m = _CREATE_RE.match(sql)
    if m:
        name = _real_table(m.group(1))
        wm = _LEDGER_WITH_RE.search(sql)
        if wm or ledger_db:
            if wm:
                sql = sql[:wm.start()] + ")"
                append_only = bool(wm.group(2)) and (wm.group(3) or "").lower() == "on"
            else:
                append_only = False
            if name.startswith(HIDDEN_PREFIX):
                raise SecError(400, "SQLError", "Table names starting with '__vyomi_' are reserved.")
            return sql, {"create_ledger": (name, append_only)}
        return sql, None
    w = _WRITE_RE.match(sql)
    if w:
        t = _real_table(w.group(2))
        if t.lower().startswith(HIDDEN_PREFIX):
            raise SecError(403, "PermissionDenied", f"The object '{t}' is reserved by the Vyomi ledger / security engine and cannot be modified.")
        lt = ledger_tables(store, db_id, create=False).get(t.lower())
        if lt:
            op = w.group(1).lower().split()[0]
            if lt["appendOnly"] and op in ("update", "delete", "truncate", "replace"):
                raise SecError(400, "LedgerAppendOnly", f"Msg 37359: Updates and deletes are not allowed on the append-only ledger table '{lt['name']}'.")
            before = _x(store, db_id, f'SELECT * FROM "{lt["name"]}"')["rows"]
            return sql, {"ledger_write": lt["name"], "op": op, "before": before}
    elif re.match(r"^\s*(drop\s+table|alter\s+table)\s+", sql, re.I):
        t = _real_table(re.sub(r"^\s*(drop\s+table|alter\s+table)\s+(if\s+exists\s+)?", "", sql, flags=re.I).split()[0])
        lt = ledger_tables(store, db_id, create=False).get(t.lower())
        if lt and lt["appendOnly"] and re.match(r"^\s*drop", sql, re.I) is None:
            raise SecError(400, "LedgerAppendOnly", f"Msg 37361: ALTER TABLE is not allowed on the append-only ledger table '{lt['name']}'.")
    for name in re.findall(r"\b(" + HIDDEN_PREFIX + r"\w+)", sql, re.I):
        if re.match(r"^\s*(insert|update|delete|drop|alter|truncate|replace|create)\b", sql, re.I):
            raise SecError(403, "PermissionDenied", f"The object '{name}' is reserved by the Vyomi ledger / security engine and cannot be modified.")
    return sql, None


def ledger_post(store, db_id, ctx, sql):
    if not ctx:
        return
    _ledger_ensure(store, db_id)
    if "create_ledger" in ctx:
        name, append_only = ctx["create_ledger"]
        _x(store, db_id, f"DELETE FROM {_L}tables WHERE table_name=?", [name])
        _x(store, db_id, f"INSERT INTO {_L}tables (table_name, append_only, created_ts) VALUES (?,?,?)", [name, 1 if append_only else 0, _iso()])
        _append_block(store, db_id, name, "CREATE", sql, None)
        return
    t = ctx["ledger_write"]
    after = _x(store, db_id, f'SELECT * FROM "{t}"')["rows"]
    b_cnt, a_cnt = {}, {}
    for r in ctx["before"]:
        k = json.dumps(list(r), default=str)
        b_cnt[k] = b_cnt.get(k, 0) + 1
    for r in after:
        k = json.dumps(list(r), default=str)
        a_cnt[k] = a_cnt.get(k, 0) + 1
    removed = [k for k, n in b_cnt.items() for _ in range(max(0, n - a_cnt.get(k, 0)))]
    added = [k for k, n in a_cnt.items() for _ in range(max(0, n - b_cnt.get(k, 0)))]
    bid = _append_block(store, db_id, t, ctx["op"].upper(), sql, len(removed) + len(added))
    for k in removed:
        _x(store, db_id, f"INSERT INTO {_L}history (block_id, table_name, operation, row_json) VALUES (?,?,?,?)", [bid, t, "DELETE", k])
    for k in added:
        _x(store, db_id, f"INSERT INTO {_L}history (block_id, table_name, operation, row_json) VALUES (?,?,?,?)", [bid, t, "INSERT", k])


def _iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time() % 1) * 1e6):06d}Z"


def _append_block(store, db_id, table, op, sql, changes):
    last = _x(store, db_id, f"SELECT block_id, hash FROM {_L}blocks ORDER BY block_id DESC LIMIT 1")["rows"]
    bid = (last[0][0] + 1) if last else 0
    prev = last[0][1] if last else GENESIS
    ts = _iso()
    stmt_hash = hashlib.sha256(sql.encode()).hexdigest()
    state = table_state_hash(store, db_id, table)
    h = _block_hash(prev, bid, ts, table, op, stmt_hash, state)
    _x(store, db_id, f"INSERT INTO {_L}blocks (block_id, prev_hash, ts, table_name, op, stmt_hash, state_hash, row_changes, hash) VALUES (?,?,?,?,?,?,?,?,?)",
       [bid, prev, ts, table, op, stmt_hash, state, changes or 0, h])
    return bid


def ledger_info(store, db_id, limit=200):
    _ledger_ensure(store, db_id)
    blocks = _x(store, db_id, f"SELECT block_id, prev_hash, ts, table_name, op, state_hash, row_changes, hash FROM {_L}blocks ORDER BY block_id DESC LIMIT {int(limit)}")["rows"]
    digs = _x(store, db_id, f"SELECT digest_id, block_id, hash, ts, digest_time FROM {_L}digests ORDER BY digest_id DESC LIMIT 50")["rows"]
    return {"tables": list(ledger_tables(store, db_id).values()),
            "blocks": [{"blockId": b[0], "previousHash": b[1], "timestamp": b[2], "table": b[3], "operation": b[4], "tableStateHash": b[5],
                        "rowChanges": b[6], "hash": b[7]} for b in blocks],
            "digests": [{"digestId": d[0], "blockId": d[1], "hash": d[2], "lastTransactionCommitTime": d[3], "digestTime": d[4]} for d in digs]}


def ledger_history(store, db_id, table):
    _ledger_ensure(store, db_id)
    rows = _x(store, db_id, f"SELECT seq, block_id, operation, row_json FROM {_L}history WHERE lower(table_name)=? ORDER BY seq", [table.lower()])["rows"]
    return [{"sequence": r[0], "ledgerTransactionId": r[1], "operation": r[2], "row": json.loads(r[3])} for r in rows]


def ledger_digest(store, db_id, database="db"):
    _ledger_ensure(store, db_id)
    last = _x(store, db_id, f"SELECT block_id, hash, ts FROM {_L}blocks ORDER BY block_id DESC LIMIT 1")["rows"]
    if not last:
        raise SecError(409, "LedgerEmpty", "The ledger has no blocks yet: create a ledger table and write to it first.")
    now = _iso()
    _x(store, db_id, f"INSERT INTO {_L}digests (block_id, hash, ts, digest_time) VALUES (?,?,?,?)", [last[0][0], last[0][1], last[0][2], now])
    return {"database_name": database, "block_id": last[0][0], "hash": "0x" + last[0][1], "last_transaction_commit_time": last[0][2], "digest_time": now}


def ledger_verify(store, db_id, extra_digests=None):
    """Recompute the whole chain, check every stored/supplied digest against it, and compare each ledger table's current
    contents with the table-state hash of its latest block.  Returns {ok, issues[], blocksVerified, digestsVerified}."""
    _ledger_ensure(store, db_id)
    issues = []
    rows = _x(store, db_id, f"SELECT block_id, prev_hash, ts, table_name, op, stmt_hash, state_hash, hash FROM {_L}blocks ORDER BY block_id")["rows"]
    prev, byid, latest = GENESIS, {}, {}
    for i, (bid, ph, ts, tb, op, sh, st, h) in enumerate(rows):
        if bid != i:
            issues.append(f"Block sequence gap: expected block {i}, found {bid}.")
        if ph != prev:
            issues.append(f"Block {bid}: previous-hash does not link to block {bid - 1} (chain broken).")
        if _block_hash(ph, bid, ts, tb, op, sh, st) != h:
            issues.append(f"Block {bid}: stored hash does not match its contents (block altered).")
        prev = h
        byid[bid] = h
        latest[tb.lower()] = (bid, st)
    digs = [(r[0], r[1]) for r in _x(store, db_id, f"SELECT block_id, hash FROM {_L}digests")["rows"]]
    for d in (extra_digests or []):
        digs.append((int(d.get("block_id")), str(d.get("hash", "")).replace("0x", "")))
    for bid, h in digs:
        if byid.get(bid) != h:
            issues.append(f"Digest for block {bid} does not match the ledger (the chain was rewritten or truncated after the digest was taken).")
    live = {t.lower(): t for t in user_tables(store, db_id)}
    for lt, (bid, st) in latest.items():
        if lt in live and table_state_hash(store, db_id, live[lt]) != st:
            issues.append(f"Table '{live[lt]}': current contents differ from the ledger (last block {bid}); rows were modified outside the ledger.")
    return {"ok": not issues, "issues": issues, "blocksVerified": len(rows), "digestsVerified": len(digs),
            "result": "Verification succeeded" if not issues else "Verification failed"}


# ═════════════════════════ Always Encrypted ═════════════════════════
_A = HIDDEN_PREFIX + "ae_"


def _ae_ensure(store, db_id):
    _ensure(store, db_id, "ae_cmk", f"CREATE TABLE IF NOT EXISTS {_A}cmk (name TEXT PRIMARY KEY, key_path TEXT, provider TEXT)")
    _ensure(store, db_id, "ae_cek", f"CREATE TABLE IF NOT EXISTS {_A}cek (name TEXT PRIMARY KEY, cmk TEXT, encrypted_value TEXT, key_version TEXT)")
    _ensure(store, db_id, "ae_cols", f"CREATE TABLE IF NOT EXISTS {_A}cols (table_name TEXT, column_name TEXT, cek TEXT, enc_type TEXT)")


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def ae_create_cmk(store, db_id, kv_store, name, key_path):
    from core import azure_cmk_core as cmk
    _ae_ensure(store, db_id)
    if not _SAFE.match(name or ""):
        raise SecError(400, "BadRequest", "Column master key name must be an identifier.")
    ok, why = cmk.usable(kv_store, key_path) if kv_store is not None else (False, "no Key Vault keys store")
    if not ok:
        raise SecError(400, "KeyVaultKeyNotFound", f"The Key Vault key '{key_path}' cannot be used as a column master key ({why}).")
    _x(store, db_id, f"DELETE FROM {_A}cmk WHERE name=?", [name])
    _x(store, db_id, f"INSERT INTO {_A}cmk (name, key_path, provider) VALUES (?,?,?)", [name, key_path, "AZURE_KEY_VAULT"])
    return {"name": name, "keyPath": key_path, "keyStoreProviderName": "AZURE_KEY_VAULT"}


def ae_create_cek(store, db_id, kv_store, name, cmk_name):
    from core import azure_cmk_core as cmk
    _ae_ensure(store, db_id)
    row = _x(store, db_id, f"SELECT key_path FROM {_A}cmk WHERE name=?", [cmk_name])["rows"]
    if not row:
        raise SecError(404, "ResourceNotFound", f"Column master key '{cmk_name}' does not exist.")
    if not _SAFE.match(name or ""):
        raise SecError(400, "BadRequest", "Column encryption key name must be an identifier.")
    name_k, ver = cmk.parse_key_uri(row[0][0])
    cek = os.urandom(32)
    try:
        wrapped = cmk._kv_call(kv_store, "wrapkey", name_k, ver or "", cek)
    except cmk.CmkError as e:
        raise SecError(403, "KeyVaultKeyInaccessible", e.message)
    _x(store, db_id, f"DELETE FROM {_A}cek WHERE name=?", [name])
    _x(store, db_id, f"INSERT INTO {_A}cek (name, cmk, encrypted_value, key_version) VALUES (?,?,?,?)",
       [name, cmk_name, wrapped["value"], wrapped.get("kid", "").rsplit("/", 1)[-1]])
    return {"name": name, "columnMasterKey": cmk_name, "encryptedValueLength": len(wrapped["value"])}


def _cek_bytes(store, db_id, kv_store, cek_name):
    """The driver unwrapping the CEK through Key Vault (fails when the CMK is disabled/deleted)."""
    from core import azure_cmk_core as cmk
    row = _x(store, db_id, f"SELECT c.encrypted_value, c.key_version, k.key_path FROM {_A}cek c JOIN {_A}cmk k ON k.name=c.cmk WHERE c.name=?", [cek_name])["rows"]
    if not row:
        raise SecError(404, "ResourceNotFound", f"Column encryption key '{cek_name}' does not exist.")
    name_k, _ = cmk.parse_key_uri(row[0][2])
    try:
        return _unb64(cmk._kv_call(kv_store, "unwrapkey", name_k, row[0][1], _unb64(row[0][0]))["value"])
    except cmk.CmkError as e:
        raise SecError(500, "ColumnEncryptionKeyUnavailable",
                       f"Failed to decrypt a column encryption key using key store provider 'AZURE_KEY_VAULT'. {e.message}")


def ae_encrypt_value(cek, plaintext, deterministic):
    pt = json.dumps(plaintext, default=str).encode()
    mk = hashlib.sha256(b"enc" + cek).digest()
    mac = hashlib.sha256(b"mac" + cek).digest()
    iv = hmac.new(mac, b"siv" + pt, hashlib.sha256).digest()[:16] if deterministic else os.urandom(16)
    ks, ctr = bytearray(), 0
    while len(ks) < len(pt):
        ks += hmac.new(mk, iv + ctr.to_bytes(4, "big"), hashlib.sha256).digest()
        ctr += 1
    ct = bytes(a ^ b for a, b in zip(pt, ks))
    tag = hmac.new(mac, iv + ct, hashlib.sha256).digest()
    return "0x01" + (tag + iv + ct).hex().upper()


def ae_decrypt_value(cek, blob):
    raw = bytes.fromhex(str(blob)[4:])
    tag, iv, ct = raw[:32], raw[32:48], raw[48:]
    mk = hashlib.sha256(b"enc" + cek).digest()
    mac = hashlib.sha256(b"mac" + cek).digest()
    if not hmac.compare_digest(hmac.new(mac, iv + ct, hashlib.sha256).digest(), tag):
        raise SecError(500, "DecryptionFailed", "Decryption failed: the ciphertext was modified or encrypted with a different key.")
    ks, ctr = bytearray(), 0
    while len(ks) < len(ct):
        ks += hmac.new(mk, iv + ctr.to_bytes(4, "big"), hashlib.sha256).digest()
        ctr += 1
    return json.loads(bytes(a ^ b for a, b in zip(ct, ks)).decode())


def _is_cipher(v):
    return isinstance(v, str) and v.startswith("0x01") and len(v) >= 4 + 96 and re.fullmatch(r"[0-9A-F]+", v[2:]) is not None


def ae_encrypt_column(store, db_id, kv_store, table, column, cek_name, enc_type):
    _ae_ensure(store, db_id)
    enc_type = (enc_type or "Deterministic").capitalize()
    if enc_type not in ("Deterministic", "Randomized"):
        raise SecError(400, "BadRequest", "encryptionType must be Deterministic or Randomized.")
    if table not in user_tables(store, db_id) or column not in table_columns(store, db_id, table):
        raise SecError(404, "ResourceNotFound", f"Column {table}.{column} does not exist.")
    cek = _cek_bytes(store, db_id, kv_store, cek_name)
    if _x(store, db_id, f"SELECT 1 FROM {_A}cols WHERE lower(table_name)=? AND lower(column_name)=?", [table.lower(), column.lower()])["rows"]:
        raise SecError(409, "AlreadyEncrypted", f"Column {table}.{column} is already encrypted.")
    rows = _x(store, db_id, f'SELECT rowid, "{column}" FROM "{table}"')["rows"] if _has_rowid(store, db_id, table) else []
    for rid, v in rows:
        if v is not None:
            _x(store, db_id, f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?', [ae_encrypt_value(cek, v, enc_type == "Deterministic"), rid])
    _x(store, db_id, f"INSERT INTO {_A}cols (table_name, column_name, cek, enc_type) VALUES (?,?,?,?)", [table, column, cek_name, enc_type])
    return {"table": table, "column": column, "columnEncryptionKey": cek_name, "encryptionType": enc_type, "rowsEncrypted": len([1 for _, v in rows if v is not None])}


def _has_rowid(store, db_id, table):
    try:
        _x(store, db_id, f'SELECT rowid FROM "{table}" LIMIT 1')
        return True
    except Exception:
        return False


def ae_columns(store, db_id, create=True):
    if not create and not _hidden_exists(store, db_id, "ae_cols"):
        return {}
    _ae_ensure(store, db_id)
    return {(r[0].lower(), r[1].lower()): {"table": r[0], "column": r[1], "cek": r[2], "type": r[3]}
            for r in _x(store, db_id, f"SELECT table_name, column_name, cek, enc_type FROM {_A}cols")["rows"]}


def ae_info(store, db_id):
    _ae_ensure(store, db_id)
    return {"columnMasterKeys": [{"name": r[0], "keyPath": r[1], "keyStoreProviderName": r[2]} for r in _x(store, db_id, f"SELECT name, key_path, provider FROM {_A}cmk")["rows"]],
            "columnEncryptionKeys": [{"name": r[0], "columnMasterKey": r[1]} for r in _x(store, db_id, f"SELECT name, cmk FROM {_A}cek")["rows"]],
            "encryptedColumns": list(ae_columns(store, db_id).values())}


def ae_pre(store, db_id, kv_store, sql, params, enabled):
    """Rewrite a statement + params for the emulated driver.  Returns (params, enc_ctx|None).  Rejects what real SQL Server rejects."""
    cols = ae_columns(store, db_id, create=False)
    if not cols:
        return params, None
    params = list(params or [])
    ctx = {"cols": cols}
    touched = []                       # (param index, table, column, enc info)
    m = re.match(r"^\s*insert\s+(?:or\s+\w+\s+)?into\s+([\[\]\w.\"`]+)\s*(?:\(([^)]*)\))?\s*values\s*(.*)$", sql, re.I | re.S)
    if m:
        t = _real_table(m.group(1))
        names = [_unq(x) for x in m.group(2).split(",")] if m.group(2) else table_columns(store, db_id, t)
        vals = m.group(3)
        groups = re.findall(r"\(([^()]*)\)", vals) or []
        pi = 0
        for g in groups:
            for j, tok in enumerate(_split_top(g)):
                tok = tok.strip()
                if j >= len(names):
                    break
                enc = cols.get((t.lower(), names[j].lower()))
                if tok == "?":
                    if enc:
                        touched.append((pi, enc))
                    pi += 1
                elif enc and tok.upper() != "NULL":
                    raise SecError(400, "SQLError", f"Msg 206: Operand type clash: a literal is incompatible with the encrypted column '{names[j]}' "
                                                    "(encryption type: " + enc["type"].upper() + "). Use a parameterized statement with column encryption enabled.")
    else:
        tm = re.match(r"^\s*(?:update\s+([\[\]\w.\"`]+)|select\b.*?\bfrom\s+([\[\]\w.\"`]+)|delete\s+from\s+([\[\]\w.\"`]+))", sql, re.I | re.S)
        t = _real_table(next((g for g in (tm.groups() if tm else ()) if g), ""))
        if t:
            qpos = 0
            for mm in re.finditer(r"([\[\]\w.\"`]+)\s*(=|<>|!=|<=|>=|<|>|\blike\b)\s*(\?|'(?:[^']|'')*'|-?\d[\d.]*)|\?", sql, re.I):
                if mm.group(0) == "?":
                    qpos += 1
                    continue
                col, op, rhs = _unq(mm.group(1).split(".")[-1]), mm.group(2).lower(), mm.group(3)
                enc = cols.get((t.lower(), col.lower()))
                is_set = bool(re.match(r"^\s*update\b", sql, re.I)) and mm.start() < (re.search(r"\bwhere\b", sql, re.I).start() if re.search(r"\bwhere\b", sql, re.I) else 10 ** 9)
                if enc:
                    if not is_set and (op != "=" or enc["type"] == "Randomized"):
                        raise SecError(400, "SQLError", "Msg 33277: Encryption scheme mismatch for columns/variables: operator '" + op.upper() + "' is not supported on "
                                       f"{enc['type'].upper()} encrypted column '{col}'. Only equality on deterministic columns is supported.")
                    if rhs != "?":
                        raise SecError(400, "SQLError", f"Msg 206: Operand type clash: a literal is incompatible with the encrypted column '{col}'. "
                                                        "Use a parameterized statement with column encryption enabled.")
                    touched.append((qpos, enc))
                if rhs == "?":
                    qpos += 1
    if not touched:
        return params, ctx
    if not enabled:
        raise SecError(400, "SQLError", "Msg 206: Operand type clash: varchar is incompatible with varchar(8000) encrypted with a column encryption key. "
                                        "Enable Column Encryption Setting on the connection to let the driver encrypt this parameter.")
    ceks = {}
    for idx, enc in touched:
        if idx >= len(params):
            continue
        if enc["cek"] not in ceks:
            ceks[enc["cek"]] = _cek_bytes(store, db_id, kv_store, enc["cek"])
        if params[idx] is not None:
            params[idx] = ae_encrypt_value(ceks[enc["cek"]], params[idx], enc["type"] == "Deterministic")
    return params, ctx


def ae_post(store, db_id, kv_store, sql, result, ctx, enabled):
    """Driver-side result decryption (only with column encryption enabled)."""
    if not ctx or not enabled or not result.get("rows"):
        return
    srcs = select_sources(store, db_id, sql, result["columns"])
    idxs = [(i, ctx["cols"][(t.lower(), c.lower())]) for i, (t, c) in enumerate(srcs) if t and c and (t.lower(), c.lower()) in ctx["cols"]]
    if not idxs:
        return
    ceks = {}
    out = []
    for row in result["rows"]:
        row = list(row)
        for i, enc in idxs:
            if _is_cipher(row[i]):
                if enc["cek"] not in ceks:
                    ceks[enc["cek"]] = _cek_bytes(store, db_id, kv_store, enc["cek"])
                row[i] = ae_decrypt_value(ceks[enc["cek"]], row[i])
        out.append(row)
    result["rows"] = out
