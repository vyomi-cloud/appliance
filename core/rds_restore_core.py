"""RDS RestoreDBInstanceFromS3 — builds a NEW DB instance from backup files that live in the simulator's own S3.

Real RestoreDBInstanceFromS3 only supports MySQL and a Percona XtraBackup physical backup, which needs MySQL's storage engine
to replay and cannot be read here. The honest backend Vyomi has is its own engine plus the formats its other features write
into S3, so the restore reads, from `s3://<S3BucketName>/<S3Prefix>`:

  * `*.sql` / `*.sql.gz` logical dumps (the plain-SQL form Vyomi's own exports write, and a `mysqldump` file: LOCK/UNLOCK/SET/
    USE statements, `ENGINE=`/`CHARSET=`/`AUTO_INCREMENT=` table options, inline `KEY`/`UNIQUE KEY` lines are normalised for
    the engine, `/*! ... */` conditional comments are dropped) — replayed statement by statement on the new instance;
  * `*.parquet` files of an RDS snapshot export (`<db>/<schema>.<table>/part-*.gz.parquet`) when a Parquet reader is installed
    (pyarrow on the offline appliance; not available in Nano) — each becomes a table with typed columns and its rows.

Everything else (including an XtraBackup `.xbstream`/`.gz` physical backup) is refused with InvalidS3BucketFault-style errors
and the honest reason. The validation (engine/source engine, role ARN, existing instance, missing bucket or empty prefix) and
the resulting instance record follow the real API; a failing statement leaves the instance in `incompatible-restore`.
Pure Python, loads under Pyodide.
"""
from __future__ import annotations

import gzip
import re

_PARQUET_READER = None


def set_parquet_reader(fn) -> None:
    """fn(bytes) -> {"columns": [{"name", "type"}], "rows": [[...]]} with types from core.sql_store.ARROW_TYPES."""
    global _PARQUET_READER
    _PARQUET_READER = fn


_TYPE_SQL = {
    "sqlite": {"int64": "INTEGER", "float64": "REAL", "bool": "INTEGER", "string": "TEXT", "binary": "BLOB"},
    "postgres": {"int64": "BIGINT", "float64": "DOUBLE PRECISION", "bool": "BOOLEAN", "string": "TEXT", "binary": "BYTEA"},
}
_SKIP = re.compile(r"^\s*(LOCK\s+TABLES|UNLOCK\s+TABLES|SET\s|USE\s|START\s+TRANSACTION|BEGIN|COMMIT|CREATE\s+DATABASE|"
                   r"DROP\s+DATABASE|FLUSH\s)", re.I)


def _s3():
    try:
        from core import s3_object_core as m
    except ImportError:
        import s3_object_core as m  # type: ignore
    return m


def _sq():
    try:
        from core import sql_store as m
    except ImportError:
        import sql_store as m  # type: ignore
    return m


def _mysql_to_engine(stmt: str, dialect: str) -> str | None:
    """Normalise one mysqldump statement for the engine; None = drop it."""
    if _SKIP.match(stmt):
        return None
    if re.match(r"^\s*CREATE\s+TABLE", stmt, re.I):
        stmt = stmt.replace("`", '"') if dialect != "sqlite" else stmt
        lines = []
        for ln in stmt.split("\n"):
            t = ln.strip().rstrip(",")
            if re.match(r"^(FULLTEXT\s+|SPATIAL\s+)?KEY\s", t, re.I) or re.match(r"^CONSTRAINT\s", t, re.I):
                continue
            ln = re.sub(r"^(\s*)UNIQUE\s+KEY\s+[`\"\w]+\s*\(", r"\1UNIQUE (", ln, flags=re.I)
            ln = re.sub(r"\s+AUTO_INCREMENT\b(?!=)", "", ln, flags=re.I)
            ln = re.sub(r"\s+(unsigned|zerofill)\b", "", ln, flags=re.I)
            ln = re.sub(r"\s+(COLLATE|CHARACTER\s+SET)\s+\w+", "", ln, flags=re.I)
            lines.append(ln)
        stmt = "\n".join(lines)
        stmt = re.sub(r",(\s*\))", r"\1", stmt)                       # a trailing comma left by a dropped KEY line
        stmt = re.sub(r"\)\s*(ENGINE|AUTO_INCREMENT|DEFAULT\s+CHARSET|CHARSET|COLLATE|COMMENT|ROW_FORMAT)\b.*$", ")", stmt,
                      flags=re.I | re.S)
    elif dialect != "sqlite":
        stmt = stmt.replace("`", '"')
    return stmt


def collect(s3_store, bucket: str, prefix: str):
    """Returns (work, error). work = [("sql", stmt) | ("table", name, columns, rows)], in file order."""
    c = _s3()
    if s3_store is None or not s3_store.bucket_exists(bucket):
        return None, f"InvalidS3BucketFault: the bucket {bucket} does not exist or is not accessible."
    keys = sorted(k for k in s3_store.bucket_objects(bucket) if k.startswith(prefix))
    if not keys:
        return None, f"InvalidS3BucketFault: no backup files were found under s3://{bucket}/{prefix}."
    work, unreadable = [], []
    for key in keys:
        low = key.lower()
        if key.endswith("/"):
            continue
        r = c.get_object(s3_store, bucket, key, {}, {})
        body = r.body if r.status == 200 and isinstance(r.body, bytes) else None
        if body is None:
            unreadable.append(key)
            continue
        if low.endswith(".sql") or low.endswith(".sql.gz"):
            try:
                text = (gzip.decompress(body) if low.endswith(".gz") else body).decode("utf-8", "replace")
            except OSError:
                unreadable.append(key)
                continue
            work.extend(("sql", s) for s in _sq().split_sql(text))
        elif low.endswith(".parquet"):
            if _PARQUET_READER is None:
                return None, ("InvalidS3BucketFault: this backup contains Parquet files but no Parquet reader is available "
                              "in this Vyomi environment (offline appliance only); restore from a .sql dump instead.")
            m = re.search(r"/(?:[^/]+)/(?:[^/.]+)\.([^/]+)/[^/]+$", key)
            table = m.group(1) if m else re.sub(r"\W", "_", key.rsplit("/", 1)[-1].split(".")[0])
            t = _PARQUET_READER(body)
            work.append(("table", table, t["columns"], t["rows"]))
        elif low.endswith((".json", ".txt", "/")) and "export_" in low:
            continue                                       # the export's own manifest files
        else:
            unreadable.append(key)
    if not work:
        return None, (f"InvalidS3BucketFault: none of the {len(keys)} file(s) under s3://{bucket}/{prefix} is a backup Vyomi can "
                      "restore (it reads .sql / .sql.gz logical dumps and, offline, RDS Parquet exports; an XtraBackup physical "
                      "backup cannot be replayed by this simulator).")
    return work, ""


def _stmts_for_table(store, name: str, columns: list, rows: list, dialect: str) -> list:
    sq = _sq()
    types = _TYPE_SQL["sqlite" if dialect == "sqlite" else "postgres"]
    cols = ", ".join(f"{sq.quote_ident(c['name'])} {types.get(c.get('type'), 'TEXT')}" for c in columns)
    out = [("sql", f"CREATE TABLE {sq.quote_ident(name)} ({cols})")]
    names = ", ".join(sq.quote_ident(c["name"]) for c in columns)
    for row in rows:
        out.append(("sql", f"INSERT INTO {sq.quote_ident(name)} ({names}) VALUES ("
                    + ", ".join(sq.sql_literal(v, dialect) for v in row) + ")"))
    return out


def statements(store, work: list) -> list:
    """Flatten collected work into engine-ready SQL statements."""
    dialect = _sq().engine_dialect(store)
    out = []
    for w in work:
        if w[0] == "sql":
            s = _mysql_to_engine(w[1], dialect)
            if s:
                out.append(s)
        else:
            out.extend(s for _, s in _stmts_for_table(store, w[1], w[2], w[3], dialect))
    return out
