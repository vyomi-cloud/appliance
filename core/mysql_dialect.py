"""MySQL -> SQLite dialect translation for the in-browser (Nano) data plane.

There is no official MySQL/MariaDB WebAssembly build, so on Nano a MySQL-flavoured instance (RDS MySQL/MariaDB/Aurora-MySQL,
Cloud SQL MySQL) is backed by sqlite3. This module lets applications and the console query editor send the MySQL SQL they
actually write: it rewrites it to SQLite, answers the MySQL administrative statements (SHOW/DESCRIBE/USE/SET ...) from SQLite's
catalog, and maps SQLite errors to MySQL error codes/messages.

Pure Python, tokenizer based (string literals and comments are never touched), no third-party packages, so it loads on host
CPython and Pyodide alike. Real MySQL (Pro/Max container) never goes through here.

Honest limits (this is a translation, not MySQL): no stored procedures/triggers/events, no ALTER TABLE ... MODIFY/CHANGE
(SQLite cannot), ON UPDATE CURRENT_TIMESTAMP does not auto-update, collations/strict-mode/charset semantics are SQLite's, one
database per instance (CREATE DATABASE/USE are accepted but do not create a second namespace).
"""
from __future__ import annotations

import re

DEFAULT_VERSION = "8.0.36"


class MySQLTranslateError(Exception):
    """A statement the in-browser engine cannot honour; carries a MySQL-style message."""


# ── tokenizer ────────────────────────────────────────────────────────────────
# kinds: ws, str, qid (backtick), id, num, op
_TOKEN = re.compile(
    r"""(?P<ws>\s+)
      |(?P<lc>--[ \t][^\n]*|--$|\#[^\n]*)
      |(?P<bc>/\*.*?\*/)
      |(?P<str>'(?:[^'\\]|\\.|'')*'|"(?:[^"\\]|\\.|"")*")
      |(?P<qid>`(?:[^`]|``)*`)
      |(?P<num>\d+\.\d+(?:[eE][+-]?\d+)?|\.\d+|\d+(?:[eE][+-]?\d+)?)
      |(?P<id>@@?[A-Za-z_][A-Za-z0-9_.$]*|[A-Za-z_][A-Za-z0-9_$]*)
      |(?P<op>.)""",
    re.X | re.S)


def _tokenize(sql: str, convert: bool = True) -> list[list]:
    out = []
    for m in _TOKEN.finditer(sql):
        kind = m.lastgroup
        text = m.group()
        if kind in ("lc", "bc"):
            if kind == "bc" and text.startswith("/*!"):
                inner = re.sub(r"^/\*!\d*\s*|\s*\*/$", "", text)   # MySQL conditional comment: run its content
                out.extend(_tokenize(inner))
            else:
                out.append(["ws", " "])
            continue
        if not convert:
            out.append([("id" if kind == "qid" else kind), text])
            continue
        if kind == "str" and text[0] == '"':                       # MySQL: "x" is a string literal, not an identifier
            body = text[1:-1].replace('""', '"').replace("'", "''")
            text = "'" + body + "'"
        if kind == "qid":
            text = '"' + text[1:-1].replace("``", "`").replace('"', '""') + '"'
            kind = "id"
        out.append([kind, text])
    return out


def _s(tokens) -> str:
    return "".join(t[1] for t in tokens).strip()


def _sig(tokens):
    return [t for t in tokens if t[0] != "ws"]


def _split_statements(sql: str) -> list[str]:
    """Split on ';' outside strings/comments; returns RAW statement text (conversion happens once, later)."""
    out, cur = [], []
    for m in _TOKEN.finditer(sql):
        if m.lastgroup == "op" and m.group() == ";":
            if "".join(cur).strip():
                out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(m.group())
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def _upper(t):
    return t[1].upper() if t[0] == "id" else None


def _unq(name: str) -> str:
    return name[1:-1].replace('""', '"') if name.startswith('"') else name


# ── argument parsing / function rewriting ────────────────────────────────────
def _match_paren(toks, i):
    """toks[i] is '(' -> index of its matching ')' (or -1)."""
    depth = 0
    for j in range(i, len(toks)):
        if toks[j][0] == "op" and toks[j][1] == "(":
            depth += 1
        elif toks[j][0] == "op" and toks[j][1] == ")":
            depth -= 1
            if depth == 0:
                return j
    return -1


def _split_args(toks):
    args, cur, depth = [], [], 0
    for t in toks:
        if t[0] == "op" and t[1] == "(":
            depth += 1
        elif t[0] == "op" and t[1] == ")":
            depth -= 1
        if t[0] == "op" and t[1] == "," and depth == 0:
            args.append(cur)
            cur = []
        else:
            cur.append(t)
    args.append(cur)
    return args


def _t(text, kind="id"):
    return [kind, text]


def _wrap(parts):
    return [_t("(", "op")] + parts + [_t(")", "op")]


_DATE_FMT = {"%Y": "%Y", "%y": "%y", "%m": "%m", "%d": "%d", "%H": "%H", "%h": "%H", "%i": "%M", "%s": "%S", "%S": "%S",
             "%T": "%H:%M:%S", "%j": "%j", "%W": "%w", "%%": "%%", "%e": "%d", "%c": "%m"}
_UNITS = {"SECOND": "seconds", "MINUTE": "minutes", "HOUR": "hours", "DAY": "days", "MONTH": "months", "YEAR": "years",
          "WEEK": "days"}


def _fn(name, args, version, db):
    """Return replacement tokens for MySQL function `name(args)`, or None to leave it alone."""
    a = args
    n = len(a)
    ws = _t(" ", "ws")
    if name in ("NOW", "SYSDATE", "CURRENT_TIMESTAMP", "LOCALTIME", "LOCALTIMESTAMP"):
        return [_t("CURRENT_TIMESTAMP")]
    if name == "CURDATE" or name == "CURRENT_DATE":
        return [_t("date"), _t("(", "op"), _t("'now'", "str"), _t(")", "op")]
    if name == "CURTIME" or name == "CURRENT_TIME":
        return [_t("time"), _t("(", "op"), _t("'now'", "str"), _t(")", "op")]
    if name == "UNIX_TIMESTAMP" and n == 0:
        return [_t("CAST"), _t("(", "op"), _t("strftime"), _t("(", "op"), _t("'%s'", "str"), _t(",", "op"), _t("'now'", "str"),
                _t(")", "op"), ws, _t("AS"), ws, _t("INTEGER"), _t(")", "op")]
    if name == "LAST_INSERT_ID":
        return [_t("last_insert_rowid"), _t("(", "op"), _t(")", "op")]
    if name == "VERSION":
        return [_t("'" + version + "'", "str")]
    if name in ("DATABASE", "SCHEMA"):
        return [_t("'" + db.replace("'", "''") + "'", "str")]
    if name in ("USER", "CURRENT_USER", "SESSION_USER", "SYSTEM_USER"):
        return [_t("'admin@%'", "str")]
    if name == "CONNECTION_ID":
        return [_t("1", "num")]
    if name == "RAND":
        return [_t("("), _t("abs", "id"), _t("(", "op"), _t("random"), _t("(", "op"), _t(")", "op"), _t("/", "op"),
                _t("9223372036854775807.0", "num"), _t(")", "op"), _t(")", "op")] if False else \
            _wrap([_t("abs"), _t("(", "op"), _t("random"), _t("(", "op"), _t(")", "op"), _t(")", "op"), _t("/", "op"),
                   _t("9223372036854775807.0", "num")])
    if name == "IF" and n == 3:
        return [_t("IIF"), _t("(", "op")] + a[0] + [_t(",", "op")] + a[1] + [_t(",", "op")] + a[2] + [_t(")", "op")]
    if name == "CONCAT" and n >= 2:
        parts = []
        for k, arg in enumerate(a):
            if k:
                parts += [ws, _t("||", "op"), ws]
            parts += _wrap(arg)
        return _wrap(parts)
    if name == "CONCAT_WS" and n >= 2:
        sep = _wrap(a[0])
        parts = []
        for k, arg in enumerate(a[1:]):
            if k:
                parts += [ws, _t("||", "op"), ws] + sep + [ws, _t("||", "op"), ws]
            parts += _wrap(arg)
        return _wrap(parts)
    if name == "CHAR_LENGTH" or name == "CHARACTER_LENGTH":
        return [_t("length"), _t("(", "op")] + a[0] + [_t(")", "op")]
    if name == "LOCATE" and n >= 2:
        return [_t("instr"), _t("(", "op")] + a[1] + [_t(",", "op")] + a[0] + [_t(")", "op")]
    if name == "LEFT" and n == 2:
        return [_t("substr"), _t("(", "op")] + a[0] + [_t(",", "op"), _t("1", "num"), _t(",", "op")] + a[1] + [_t(")", "op")]
    if name == "RIGHT" and n == 2:
        return [_t("substr"), _t("(", "op")] + a[0] + [_t(",", "op"), _t("-", "op")] + _wrap(a[1]) + [_t(")", "op")]
    if name in ("YEAR", "MONTH", "DAY", "DAYOFMONTH", "HOUR", "MINUTE", "SECOND") and n == 1:
        f = {"YEAR": "%Y", "MONTH": "%m", "DAY": "%d", "DAYOFMONTH": "%d", "HOUR": "%H", "MINUTE": "%M", "SECOND": "%S"}[name]
        return [_t("CAST"), _t("(", "op"), _t("strftime"), _t("(", "op"), _t("'" + f + "'", "str"), _t(",", "op")] + a[0] + \
            [_t(")", "op"), ws, _t("AS"), ws, _t("INTEGER"), _t(")", "op")]
    if name == "DATEDIFF" and n == 2:
        return [_t("CAST"), _t("(", "op"), _t("julianday"), _t("(", "op")] + a[0] + [_t(")", "op"), _t("-", "op"),
                _t("julianday"), _t("(", "op")] + a[1] + [_t(")", "op"), ws, _t("AS"), ws, _t("INTEGER"), _t(")", "op")]
    if name == "DATE_FORMAT" and n == 2 and len(a[1]) == 1 and a[1][0][0] == "str":
        fmt = a[1][0][1][1:-1]
        fmt = re.sub(r"%.", lambda m: _DATE_FMT.get(m.group(), m.group()), fmt)
        return [_t("strftime"), _t("(", "op"), _t("'" + fmt + "'", "str"), _t(",", "op")] + a[0] + [_t(")", "op")]
    if name in ("DATE_ADD", "DATE_SUB", "ADDDATE", "SUBDATE") and n == 2:
        iv = _sig(a[1])
        if iv and iv[0][0] == "id" and iv[0][1].upper() == "INTERVAL" and len(iv) >= 3 and iv[1][0] == "num" \
                and iv[2][1].upper() in _UNITS:
            amt = float(iv[1][1]) * (7 if iv[2][1].upper() == "WEEK" else 1)
            amt = int(amt) if amt == int(amt) else amt
            sign = "-" if name in ("DATE_SUB", "SUBDATE") else "+"
            return [_t("datetime"), _t("(", "op")] + a[0] + [_t(",", "op"),
                    _t("'" + sign + str(amt) + " " + _UNITS[iv[2][1].upper()] + "'", "str"), _t(")", "op")]
    if name == "TRUNCATE" and n == 2:   # TRUNCATE(x, d) the function, not the statement
        return None
    return None


def _rewrite_funcs(toks, version, db):
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t[0] == "id" and not t[1].startswith('"') and not t[1].startswith("@"):
            j = i + 1
            while j < len(toks) and toks[j][0] == "ws":
                j += 1
            name = t[1].upper()
            # niladic MySQL "functions" written without parentheses
            if name in ("CURRENT_TIMESTAMP", "LOCALTIME", "LOCALTIMESTAMP") and not (j < len(toks) and toks[j][1] == "("):
                out.append(t)
                i += 1
                continue
            if j < len(toks) and toks[j][0] == "op" and toks[j][1] == "(":
                k = _match_paren(toks, j)
                if k > 0:
                    inner = toks[j + 1:k]
                    # GROUP_CONCAT(x [ORDER BY ..] SEPARATOR 's')
                    if name == "GROUP_CONCAT":
                        sep = None
                        for p in range(len(inner) - 1, -1, -1):
                            if inner[p][0] == "id" and inner[p][1].upper() == "SEPARATOR":
                                sepcand = [x for x in inner[p + 1:] if x[0] != "ws"]
                                if sepcand and sepcand[0][0] == "str":
                                    sep = sepcand[0][1]
                                    inner = inner[:p]
                                break
                        for p in range(len(inner)):
                            if inner[p][0] == "id" and inner[p][1].upper() == "ORDER":   # ORDER BY inside is not supported by sqlite
                                inner = inner[:p]
                                break
                        body = _rewrite_funcs(inner, version, db)
                        out += [_t("group_concat"), _t("(", "op")] + body + ([_t(",", "op"), _t(sep, "str")] if sep else []) + [_t(")", "op")]
                        i = k + 1
                        continue
                    args = [_trim(_rewrite_funcs(x, version, db)) for x in _split_args(inner)] if _s(inner) else []
                    rep = _fn(name, args, version, db)
                    if rep is not None:
                        out += rep
                        i = k + 1
                        continue
                    out += [t] + toks[i + 1:j + 1] + _join_args(args) + [toks[k]]
                    i = k + 1
                    continue
        out.append(t)
        i += 1
    return out


def _trim(toks):
    a, b = 0, len(toks)
    while a < b and toks[a][0] == "ws":
        a += 1
    while b > a and toks[b - 1][0] == "ws":
        b -= 1
    return toks[a:b]


def _join_args(args):
    out = []
    for n, a in enumerate(args):
        if n:
            out.append(_t(",", "op"))
        out += a
    return out


# ── statement-level rewrites ─────────────────────────────────────────────────
_TYPE_INT = {"TINYINT", "SMALLINT", "MEDIUMINT", "INT", "INTEGER", "BIGINT"}
_COL_STRIP = {"UNSIGNED", "ZEROFILL", "SIGNED"}


def _clean_column(toks):
    """One CREATE TABLE column definition (significant tokens) -> (sqlite_text, is_autoinc, is_pk, name)."""
    s = [t for t in toks if t[0] != "ws"]
    out, i, auto, pk, name = [], 0, False, False, None
    while i < len(s):
        t = s[i]
        u = _upper(t)
        if name is None and t[0] == "id":
            name = _unq(t[1])
        if u in _COL_STRIP:
            i += 1
            continue
        if u == "AUTO_INCREMENT":
            auto = True
            i += 1
            continue
        if u == "PRIMARY":
            pk = True
        if u in ("ENUM", "SET") and i + 1 < len(s) and s[i + 1][1] == "(":
            k = _match_paren(s, i + 1)
            out.append(_t("TEXT"))
            i = k + 1
            continue
        if u in _TYPE_INT and i + 1 < len(s) and s[i + 1][1] == "(":     # INT(11) display width
            k = _match_paren(s, i + 1)
            out.append(_t("INTEGER" if u in ("BIGINT", "INT", "INTEGER", "MEDIUMINT") else u))
            i = k + 1
            continue
        if u in ("CHARACTER", "CHARSET", "COLLATE") or (u == "CHAR" and i + 1 < len(s) and _upper(s[i + 1]) == "SET"):
            i += 3 if u == "CHARACTER" else 2          # CHARACTER SET x / CHARSET x / COLLATE x
            if u == "CHAR":
                i += 1
            continue
        if u == "ON" and i + 2 < len(s) and _upper(s[i + 1]) == "UPDATE":
            i += 3
            if i < len(s) and s[i][1] == "(":
                i = _match_paren(s, i) + 1
            continue
        if u == "COMMENT" and i + 1 < len(s) and s[i + 1][0] == "str":
            i += 2
            continue
        out.append(t)
        i += 1
    return _respace(out), auto, pk, name


def _respace(sig):
    """Whitespace-free tokens -> tokens with sensible single spaces (no space around parens/commas/dots)."""
    out = []
    for t in sig:
        if t[0] == "ws":
            continue
        if out:
            prev = out[-1]
            tight = (t[1] in (")", ",", ".") or t[1] == "(" and prev[0] == "id" or prev[1] in ("(", ".")
                     or prev[1] == "," and False)
            if not tight:
                out.append(["ws", " "])
            elif prev[1] == "," and t[1] != ")":
                out.append(["ws", " "])
        out.append(t)
    return out


def _create_table(toks, version, db):
    sig = _sig(toks)
    # find the opening paren of the column list
    p = next((n for n, t in enumerate(toks) if t[0] == "op" and t[1] == "("), -1)
    if p < 0:
        return [_s(toks)]
    q = _match_paren(toks, p)
    head = toks[:p]
    body = toks[p + 1:q]
    # table name = last id before '('
    tname = [t for t in head if t[0] == "id"][-1][1]
    tbare = _unq(tname)
    cols, extras, indexes, table_pk = [], [], [], None
    autos = []
    for item in _split_args(body):
        it = list(item)
        while it and it[0][0] == "ws":
            it.pop(0)
        sg = _sig(it)
        if not sg:
            continue
        u0 = _upper(sg[0])
        u1 = _upper(sg[1]) if len(sg) > 1 else None
        if u0 == "PRIMARY" and u1 == "KEY":
            inner = _sig(it[it.index(next(t for t in it if t[1] == "(")) + 1:])
            cl = [x[1] for x in inner if x[0] == "id"]
            table_pk = [_unq(c) for c in cl if c.upper() not in ("ASC", "DESC") and not c.startswith("(")]
            continue
        if u0 in ("KEY", "INDEX") or (u0 == "UNIQUE" and u1 in ("KEY", "INDEX")) or u0 == "FULLTEXT" or u0 == "SPATIAL":
            uniq = u0 == "UNIQUE"
            ids = [t for t in sg if t[0] == "id"]
            op = next(n for n, t in enumerate(sg) if t[1] == "(")
            iname = next((t[1] for t in sg[:op] if t[0] == "id" and _upper(t) not in ("KEY", "INDEX", "UNIQUE", "FULLTEXT", "SPATIAL")), None)
            cl = _s(sg[op:_match_paren(sg, op) + 1])
            cl = re.sub(r"\(\s*\d+\s*\)", "", cl)             # prefix lengths  col(191)
            iname = iname or ('"idx_%s_%d"' % (tbare, len(indexes) + 1))
            indexes.append("CREATE %sINDEX IF NOT EXISTS %s ON %s %s" % ("UNIQUE " if uniq else "", iname, tname, cl))
            continue
        if u0 == "UNIQUE" or (u0 == "CONSTRAINT" and "UNIQUE" in [_upper(x) for x in sg]):
            extras.append(_s(_strip_unique_key_word(it)))
            continue
        if u0 == "CONSTRAINT" or u0 == "FOREIGN" or u0 == "CHECK":
            extras.append(_s(it))
            continue
        c, auto, pk, name = _clean_column(it)
        cols.append([c, auto, pk, name])
        if auto:
            autos.append(name)
    for c in cols:
        if c[1]:
            # AUTO_INCREMENT -> INTEGER PRIMARY KEY AUTOINCREMENT (sqlite needs the PK on the column itself)
            toks_c = [t for t in _drop_key_after_primary(c[0]) if t[0] != "ws"]
            nm = toks_c[0]
            rest = [t for t in toks_c[1:]
                    if _upper(t) not in ("INTEGER", "INT", "BIGINT", "SMALLINT", "TINYINT", "MEDIUMINT", "NOT", "NULL")]
            c[0] = _respace([nm, _t("INTEGER"), _t("PRIMARY"), _t("KEY"), _t("AUTOINCREMENT")] + rest)
    pk_single = table_pk and len(table_pk) == 1 and table_pk[0] in autos
    defs = [_s(c[0]) for c in cols]
    if table_pk and not pk_single:
        defs.append("PRIMARY KEY (%s)" % ", ".join('"%s"' % x for x in table_pk))
    defs += extras
    head_txt = _s(head).replace("`", '"')
    stmts = ["%s (%s)" % (head_txt, ", ".join(defs))] + indexes
    return stmts


def _drop_key_after_primary(c):
    out, i = [], 0
    while i < len(c):
        u = _upper(c[i])
        if u == "PRIMARY":
            i += 1
            while i < len(c) and (c[i][0] == "ws" or _upper(c[i]) == "KEY"):
                i += 1
            continue
        out.append(c[i])
        i += 1
    return out


def _strip_unique_key_word(it):
    out, skip = [], False
    for t in it:
        if _upper(t) in ("KEY", "INDEX") and not skip:
            skip = True
            continue
        out.append(t)
    return out


def _upsert(toks):
    """ON DUPLICATE KEY UPDATE a=VALUES(a), b=b+1  ->  ON CONFLICT DO UPDATE SET a=excluded.a, b=b+1 ; INSERT IGNORE -> INSERT OR IGNORE."""
    sg = _sig(toks)
    if not sg:
        return toks
    if _upper(sg[0]) == "INSERT" and len(sg) > 1 and _upper(sg[1]) == "IGNORE":
        first = True
        res = []
        for t in toks:
            if first and _upper(t) == "INSERT":
                res += [_t("INSERT"), _t(" ", "ws"), _t("OR"), _t(" ", "ws"), _t("IGNORE")]
                first = False
                skip_ign = True
                continue
            if _upper(t) == "IGNORE" and not first:
                first = None
                continue
            res.append(t)
        toks = res
    low = [(_upper(t) or "") for t in toks]
    for i in range(len(toks) - 3):
        if low[i] == "ON" and _upper(_next_sig(toks, i, 1)) == "DUPLICATE":
            j = i
            # drop through KEY UPDATE
            k = i
            seen = 0
            while k < len(toks) and seen < 4:
                if toks[k][0] != "ws":
                    seen += 1
                k += 1
            tail = toks[k:]
            tail = _values_to_excluded(tail)
            return toks[:i] + [_t("ON"), _t(" ", "ws"), _t("CONFLICT"), _t(" ", "ws"), _t("DO"), _t(" ", "ws"), _t("UPDATE"),
                               _t(" ", "ws"), _t("SET"), _t(" ", "ws")] + tail
    return toks


def _next_sig(toks, i, n):
    c = 0
    for j in range(i + 1, len(toks)):
        if toks[j][0] != "ws":
            c += 1
            if c == n:
                return toks[j]
    return ["op", ""]


def _values_to_excluded(toks):
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        if _upper(t) == "VALUES":
            j = i + 1
            while j < len(toks) and toks[j][0] == "ws":
                j += 1
            if j < len(toks) and toks[j][1] == "(":
                k = _match_paren(toks, j)
                out += [_t("excluded"), _t(".", "op")] + toks[j + 1:k]
                i = k + 1
                continue
        out.append(t)
        i += 1
    return out


def _limit(toks):
    low = [(_upper(t) or "") for t in toks]
    for i in range(len(toks)):
        if low[i] == "LIMIT":
            rest = _sig(toks[i + 1:])
            if len(rest) >= 3 and rest[0][0] == "num" and rest[1][1] == "," and rest[2][0] == "num":
                return toks[:i] + [_t("LIMIT"), _t(" ", "ws"), rest[2], _t(" ", "ws"), _t("OFFSET"), _t(" ", "ws"), rest[0]] \
                    + _tail_after(toks[i + 1:], 3)
    return toks


def _tail_after(toks, n):
    c = 0
    for j, t in enumerate(toks):
        if t[0] != "ws":
            c += 1
            if c == n:
                return toks[j + 1:]
    return []


def _strip_locking(toks):
    low = [(_upper(t) or "") for t in toks]
    for i in range(len(toks) - 1):
        if low[i] == "FOR" and _upper(_next_sig(toks, i, 1)) == "UPDATE":
            return toks[:i]
        if low[i] == "LOCK" and _upper(_next_sig(toks, i, 1)) == "IN":
            return toks[:i]
    return toks


_VARS = [("version", DEFAULT_VERSION), ("version_comment", "Vyomi (SQLite-backed)"), ("max_connections", "151"),
         ("character_set_server", "utf8mb4"), ("collation_server", "utf8mb4_0900_ai_ci"), ("sql_mode",
         "ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION"),
         ("autocommit", "ON"), ("time_zone", "UTC"), ("lower_case_table_names", "0"), ("port", "3306")]


def _q(v):
    return "'" + str(v).replace("'", "''") + "'"


def _admin(sg, toks, db, version):
    """SHOW/DESCRIBE/USE/SET ... -> ('sql', [stmts]) | ('noop', None) | None when not an admin statement."""
    u = [(_upper(t) or t[1]) for t in sg]
    if not u:
        return None
    w = u[0]
    like = None
    if "LIKE" in u:
        li = u.index("LIKE")
        like = sg[li + 1][1] if li + 1 < len(sg) and sg[li + 1][0] == "str" else None
    if w in ("USE", "SET", "LOCK", "UNLOCK", "FLUSH", "ANALYZE", "OPTIMIZE", "GRANT", "REVOKE", "KILL"):
        if w == "SET" and len(u) > 1 and u[1] == "TRANSACTION":
            return ("noop", None)
        return ("noop", None)
    if w in ("CREATE", "DROP") and len(u) > 1 and u[1] in ("DATABASE", "SCHEMA"):
        return ("noop", None)
    if w == "START" and len(u) > 1 and u[1] == "TRANSACTION":
        return ("sql", ["BEGIN"])
    if w == "BEGIN" and len(u) == 1:
        return ("sql", ["BEGIN"])
    if w == "TRUNCATE":
        tn = [t for t in sg if t[0] == "id" and _upper(t) not in ("TRUNCATE", "TABLE")][0][1]
        return ("sql", ["DELETE FROM " + tn, "DELETE FROM sqlite_sequence WHERE name = " + _q(_unq(tn))], True)
    if w in ("DESCRIBE", "DESC", "EXPLAIN") and len(u) >= 2 and u[1] not in ("SELECT", "INSERT", "UPDATE", "DELETE", "FORMAT",
                                                                           "ANALYZE", "WITH"):
        tn = _unq(sg[1][1])
        return ("sql", [_describe_sql(tn)])
    if w == "SHOW":
        rest = u[1:]
        if rest[:1] in (["FULL"], ["GLOBAL"], ["SESSION"]):
            rest = rest[1:]
        head = rest[0] if rest else ""
        if head == "TABLES":
            cond = "" if not like else " AND name LIKE " + like
            hdr = "Tables_in_" + db
            return ("sql", ["SELECT name AS \"%s\" FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%%'%s ORDER BY name" % (hdr, cond)])
        if head in ("DATABASES", "SCHEMAS"):
            names = ["information_schema", "mysql", "performance_schema", "sys", db]
            return ("sql", [" UNION ALL ".join("SELECT %s AS \"Database\"" % _q(n) for n in names)])
        if head in ("COLUMNS", "FIELDS"):
            tn = _unq(sg[[t[1].upper() for t in sg].index(next(x for x in ("FROM", "IN") if x in [t[1].upper() for t in sg])) + 1][1])
            return ("sql", [_describe_sql(tn)])
        if head == "CREATE" and len(rest) > 1 and rest[1] == "TABLE":
            tn = _unq(sg[-1][1])
            return ("sql", ["SELECT name AS \"Table\", sql AS \"Create Table\" FROM sqlite_master WHERE type = 'table' AND name = " + _q(tn)])
        if head in ("INDEX", "INDEXES", "KEYS"):
            tn = _unq(sg[-1][1])
            return ("sql", ["SELECT %s AS \"Table\", CASE WHEN \"unique\" THEN 0 ELSE 1 END AS Non_unique, name AS Key_name, "
                            "'BTREE' AS Index_type FROM pragma_index_list(%s)" % (_q(tn), _q(tn))])
        if head in ("VARIABLES", "STATUS"):
            rows = _VARS if head == "VARIABLES" else [("Uptime", "1"), ("Threads_connected", "1"), ("Questions", "0")]
            rows = [(k, (version if k == "version" else v)) for k, v in rows]
            if like:
                pat = like[1:-1].replace("%", ".*").replace("_", ".")
                rows = [r for r in rows if re.fullmatch(pat, r[0], re.I)]
            if not rows:
                return ("sql", ["SELECT NULL AS Variable_name, NULL AS Value WHERE 0"])
            col = ("Variable_name", "Value")
            return ("sql", [" UNION ALL ".join("SELECT %s AS %s, %s AS %s" % (_q(k), col[0], _q(v), col[1]) for k, v in rows)])
        if head in ("PROCESSLIST",):
            return ("sql", ["SELECT 1 AS Id, 'admin' AS User, 'localhost' AS Host, %s AS db, 'Query' AS Command, 0 AS Time, "
                            "'executing' AS State, 'SHOW PROCESSLIST' AS Info" % _q(db)])
        if head in ("WARNINGS", "ERRORS"):
            return ("sql", ["SELECT NULL AS Level, NULL AS Code, NULL AS Message WHERE 0"])
        if head == "ENGINES":
            return ("sql", ["SELECT 'InnoDB' AS Engine, 'DEFAULT' AS Support, 'Supports transactions' AS Comment"])
        if head in ("TABLE",) and len(rest) > 1 and rest[1] == "STATUS":
            cond = "" if not like else " AND name LIKE " + like
            return ("sql", ["SELECT name AS Name, 'InnoDB' AS Engine, 0 AS Rows FROM sqlite_master WHERE type = 'table' "
                            "AND name NOT LIKE 'sqlite_%%'%s ORDER BY name" % cond])
        raise MySQLTranslateError("SHOW %s is not supported by the in-browser MySQL engine." % " ".join(rest))
    return None


def _describe_sql(tn):
    return ("SELECT name AS Field, lower(type) AS Type, CASE WHEN \"notnull\" THEN 'NO' ELSE 'YES' END AS \"Null\", "
            "CASE WHEN pk THEN 'PRI' ELSE '' END AS \"Key\", dflt_value AS \"Default\", "
            "CASE WHEN pk AND lower(type) LIKE 'int%%' THEN 'auto_increment' ELSE '' END AS Extra FROM pragma_table_info(%s)" % _q(tn))


def _alter(toks, sg):
    # ALTER TABLE t ADD [COLUMN] ..., ADD INDEX/KEY/UNIQUE ..., DROP INDEX x, DROP [COLUMN] c, RENAME TO, MODIFY/CHANGE (unsupported)
    u = [(_upper(t) or "") for t in sg]
    tn = sg[2][1]
    action = u[3] if len(u) > 3 else ""
    if action in ("MODIFY", "CHANGE"):
        raise MySQLTranslateError("ALTER TABLE ... %s COLUMN is not supported by the in-browser MySQL engine (SQLite cannot change a "
                                  "column in place). Create a new table and copy the rows instead." % action)
    if action == "ADD" and len(u) > 4 and (u[4] in ("INDEX", "KEY") or (u[4] == "UNIQUE")):
        uniq = u[4] == "UNIQUE"
        k = 5 + (1 if uniq and u[5] in ("INDEX", "KEY") else 0) if uniq else 5
        rest = sg[k:]
        name = rest[0][1] if rest and rest[0][1] != "(" else '"idx_%s_%d"' % (_unq(tn), 1)
        op = next(n for n, t in enumerate(rest) if t[1] == "(")
        cl = re.sub(r"\(\s*\d+\s*\)", "", _s(rest[op:_match_paren(rest, op) + 1]))
        return ["CREATE %sINDEX IF NOT EXISTS %s ON %s %s" % ("UNIQUE " if uniq else "", name, tn, cl)]
    if action == "DROP" and len(u) > 4 and u[4] in ("INDEX", "KEY"):
        return ["DROP INDEX IF EXISTS " + sg[5][1]]
    if action == "ADD" and len(u) > 4 and u[4] == "PRIMARY":
        raise MySQLTranslateError("ALTER TABLE ... ADD PRIMARY KEY is not supported by the in-browser MySQL engine.")
    if action == "ADD":
        rest = [t for t in toks]
        # drop AUTO_INCREMENT/UNSIGNED/etc. from the added column
        i = next(n for n, t in enumerate(sg) if _upper(t) == "ADD")
        body = [t for t in sg[i + 1:] if _upper(t) != "COLUMN"]
        c, auto, pk, name = _clean_column(body)
        return ["ALTER TABLE %s ADD COLUMN %s" % (tn, _s(c))]
    if action == "RENAME":
        tgt = sg[-1][1]
        return ["ALTER TABLE %s RENAME TO %s" % (tn, tgt)]
    return [_s(toks)]


def prepare(sql: str, db: str = "db", version: str = DEFAULT_VERSION) -> list[dict]:
    """MySQL SQL (possibly several `;`-separated statements) -> ordered steps:
    {"sql": <sqlite sql>} to run, or {"noop": True} for statements that are accepted and do nothing.
    A step marked "main" receives the caller's bind parameters."""
    steps = []
    for stmt in _split_statements(sql):
        toks = _tokenize(stmt)
        sg = _sig(toks)
        if not sg:
            continue
        adm = _admin(sg, toks, db, version)
        if adm is not None:
            if adm[0] == "noop":
                steps.append({"noop": True})
            else:
                for n, s in enumerate(adm[1]):
                    steps.append({"sql": s, "main": n == len(adm[1]) - 1})
            continue
        u0 = _upper(sg[0])
        u1 = _upper(sg[1]) if len(sg) > 1 else None
        if u0 == "CREATE" and u1 in ("TABLE", "TEMPORARY"):
            body = _create_table([t for t in toks], version, db)
            body[0] = _s(_rewrite_funcs(_tokenize(body[0], convert=False), version, db))
            for n, s in enumerate(body):
                steps.append({"sql": s, "main": n == 0})
            continue
        if u0 == "ALTER" and u1 == "TABLE":
            for n, s in enumerate(_alter(toks, sg)):
                steps.append({"sql": s, "main": n == 0})
            continue
        if u0 == "DROP" and u1 == "INDEX":                       # DROP INDEX name ON t
            steps.append({"sql": "DROP INDEX IF EXISTS " + sg[2][1], "main": True})
            continue
        toks = _rewrite_funcs(toks, version, db)
        toks = _upsert(toks)
        toks = _limit(toks)
        toks = _strip_locking(toks)
        out = _s(toks)
        # SELECT @@version / @@sql_mode style system variables
        out = re.sub(r"@@(?:session\.|global\.)?version\b", "'" + version + "'", out, flags=re.I)
        out = re.sub(r"@@(?:session\.|global\.)?(\w+)", lambda m: _q(dict(_VARS).get(m.group(1).lower(), "")), out)
        steps.append({"sql": out, "main": True})
    if not steps:
        steps.append({"noop": True})
    return steps


_EMPTY = {"columns": [], "rows": [], "rowcount": 0}


def run(sql: str, params, exec_fn, db: str = "db", version: str = DEFAULT_VERSION) -> dict:
    """Translate and execute with `exec_fn(sqlite_sql, params) -> {columns, rows, rowcount}`. Returns the last statement's result.
    SQLite errors are re-raised as MySQL-style errors."""
    result = dict(_EMPTY)
    steps = prepare(sql, db, version)
    mains = [s for s in steps if s.get("main")]
    try:
        for st in steps:
            if st.get("noop"):
                result = dict(_EMPTY)
                continue
            p = params if (st.get("main") and (st is mains[0] or len(mains) == 1)) else None
            result = exec_fn(st["sql"], p)
    except MySQLTranslateError:
        raise
    except Exception as e:
        raise MySQLTranslateError(mysql_error(str(e), db)) from e
    return result


async def arun(sql: str, params, aexec_fn, db: str = "db", version: str = DEFAULT_VERSION) -> dict:
    result = dict(_EMPTY)
    steps = prepare(sql, db, version)
    mains = [s for s in steps if s.get("main")]
    try:
        for st in steps:
            if st.get("noop"):
                result = dict(_EMPTY)
                continue
            p = params if (st.get("main") and (st is mains[0] or len(mains) == 1)) else None
            result = await aexec_fn(st["sql"], p)
    except MySQLTranslateError:
        raise
    except Exception as e:
        raise MySQLTranslateError(mysql_error(str(e), db)) from e
    return result


def mysql_error(msg: str, db: str = "db") -> str:
    """SQLite error text -> the MySQL error the application would have seen."""
    m = re.search(r"no such table: (?:main\.)?(\S+)", msg)
    if m:
        return "ERROR 1146 (42S02): Table '%s.%s' doesn't exist" % (db, m.group(1).strip('"'))
    m = re.search(r"table (\S+) already exists", msg)
    if m:
        return "ERROR 1050 (42S01): Table '%s' already exists" % m.group(1).strip('"')
    m = re.search(r"no such column: (\S+)", msg)
    if m:
        return "ERROR 1054 (42S22): Unknown column '%s' in 'field list'" % m.group(1).strip('"')
    m = re.search(r"UNIQUE constraint failed: (\S+)", msg)
    if m:
        col = m.group(1).split(".")[-1].strip('"')
        return "ERROR 1062 (23000): Duplicate entry for key '%s'" % col
    m = re.search(r"NOT NULL constraint failed: (\S+)", msg)
    if m:
        return "ERROR 1048 (23000): Column '%s' cannot be null" % m.group(1).split(".")[-1].strip('"')
    if "FOREIGN KEY constraint failed" in msg:
        return "ERROR 1452 (23000): Cannot add or update a child row: a foreign key constraint fails"
    if "syntax error" in msg or "unrecognized token" in msg:
        return "ERROR 1064 (42000): You have an error in your SQL syntax; " + msg
    return msg


def is_mysql_engine(engine: str | None) -> bool:
    e = str(engine or "").lower()
    return e.startswith("mysql") or "maria" in e or e == "aurora-mysql" or e.startswith("aurora-mysql")
