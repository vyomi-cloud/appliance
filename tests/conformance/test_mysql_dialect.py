"""MySQL -> SQLite dialect translation (core/mysql_dialect.py) + the RDS data plane for MySQL-family instances on sqlite (Nano)."""
import sqlite3, sys, asyncio
sys.path.insert(0, ".")
from core import mysql_dialect as m
c = sqlite3.connect(":memory:", isolation_level=None)
def ex(s,p=None):
    cur=c.cursor(); cur.execute(s, list(p or []))
    cols=[d[0] for d in cur.description] if cur.description else []
    rows=[list(r) for r in cur.fetchall()] if cur.description else []
    return {"columns":cols,"rows":rows,"rowcount":cur.rowcount if not cols else len(rows)}
def R(sql,p=None): return m.run(sql,p,ex,db="shop")
fails=0
def chk(name, got, want):
    global fails
    ok = got==want
    fails += (not ok)
    print(("PASS " if ok else "FAIL ")+name, "" if ok else f"got={got!r} want={want!r}")
R("""CREATE TABLE `users` (
  `id` int(11) unsigned NOT NULL AUTO_INCREMENT,
  `email` varchar(191) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` enum('a','b') DEFAULT 'a',
  `score` bigint(20) DEFAULT 0,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `note` text COMMENT 'free text',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_email` (`email`),
  KEY `idx_score` (`score`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
chk("show tables", R("SHOW TABLES")["rows"], [["users"]])
chk("show tables hdr", R("SHOW TABLES")["columns"], ["Tables_in_shop"])
R("INSERT INTO users (email, score) VALUES ('a@x.com', 1), ('b@x.com', 2)")
chk("autoinc", R("SELECT id FROM users ORDER BY id")["rows"], [[1],[2]])
chk("last_insert_id", R("INSERT INTO users (email) VALUES ('c@x.com')") and R("SELECT LAST_INSERT_ID()")["rows"], [[3]])
chk("insert ignore", R("INSERT IGNORE INTO users (email) VALUES ('a@x.com')")["rowcount"], 0)
R("INSERT INTO users (email, score) VALUES ('a@x.com', 9) ON DUPLICATE KEY UPDATE score = VALUES(score)")
chk("upsert", R("SELECT score FROM users WHERE email='a@x.com'")["rows"], [[9]])
chk("limit a,b", R("SELECT id FROM users ORDER BY id LIMIT 1, 2")["rows"], [[2],[3]])
chk("concat", R("SELECT CONCAT(email, '-', id) FROM users WHERE id = 1")["rows"], [["a@x.com-1"]])
chk("if", R("SELECT IF(score > 5, 'hi', 'lo') FROM users WHERE id = 1")["rows"], [["hi"]])
chk("backtick+dq", R('SELECT `email` FROM `users` WHERE email = "b@x.com"')["rows"], [["b@x.com"]])
chk("describe", [r[0] for r in R("DESCRIBE users")["rows"]][:3], ["id","email","status"])
chk("show columns", len(R("SHOW COLUMNS FROM users")["rows"]), 7)
chk("show create", R("SHOW CREATE TABLE users")["columns"], ["Table","Create Table"])
chk("show index", len(R("SHOW INDEX FROM users")["rows"]) >= 2, True)
chk("use/set noop", R("USE shop; SET NAMES utf8mb4")["rowcount"], 0)
chk("show databases", ["shop"] in R("SHOW DATABASES")["rows"], True)
chk("select version", R("SELECT VERSION()")["rows"], [["8.0.36"]])
chk("database()", R("SELECT DATABASE()")["rows"], [["shop"]])
chk("@@version", R("SELECT @@version")["rows"], [["8.0.36"]])
chk("show variables like", R("SHOW VARIABLES LIKE 'max_conn%'")["rows"], [["max_connections","151"]])
chk("group_concat", R("SELECT GROUP_CONCAT(email SEPARATOR ';') FROM users WHERE id<3")["rows"][0][0] in ("a@x.com;b@x.com","b@x.com;a@x.com"), True)
chk("year()", R("SELECT YEAR('2024-05-06')")["rows"], [[2024]])
chk("date_format", R("SELECT DATE_FORMAT('2024-05-06 07:08:09', '%Y/%m/%d %H:%i:%s')")["rows"], [["2024/05/06 07:08:09"]])
chk("date_add", R("SELECT DATE_ADD('2024-05-06', INTERVAL 2 DAY)")["rows"], [["2024-05-08 00:00:00"]])
chk("datediff", R("SELECT DATEDIFF('2024-05-08','2024-05-06')")["rows"], [[2]])
chk("string literal untouched", R("SELECT 'NOW() `x` LIMIT 1,2'")["rows"], [["NOW() `x` LIMIT 1,2"]])
chk("for update", R("SELECT id FROM users WHERE id=1 FOR UPDATE")["rows"], [[1]])
R("ALTER TABLE users ADD COLUMN age INT(3) UNSIGNED DEFAULT 0")
R("ALTER TABLE users ADD INDEX idx_age (age)")
chk("alter add", len(R("DESCRIBE users")["rows"]), 8)
chk("truncate", (R("TRUNCATE TABLE users"), R("SELECT COUNT(*) FROM users")["rows"])[1], [[0]])
R("INSERT INTO users (email) VALUES ('z@x.com')")
chk("truncate resets autoinc", R("SELECT id FROM users")["rows"], [[1]])
for bad, code in (("SELECT * FROM nope", "1146"), ("INSERT INTO users (email) VALUES ('z@x.com')", "1062"), ("SELECT zz FROM users", "1054"),
                  ("SELEC 1", "1064"), ("INSERT INTO users (email) VALUES (NULL)", "1048")):
    try: R(bad); chk("err "+code, "no error", code)
    except m.MySQLTranslateError as e: chk("err "+code, code in str(e), True)
try: R("ALTER TABLE users MODIFY COLUMN age BIGINT"); chk("modify unsupported","no error","error")
except m.MySQLTranslateError as e: chk("modify unsupported", "not supported" in str(e), True)

# ── through the RDS data plane: a MySQL instance on the sqlite engine accepts MySQL SQL; a Postgres one does not translate ──
from core.sql_store import InMemorySqlStore
from core import rds_core
st = InMemorySqlStore()
r = rds_core.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "my1", "DBInstanceClass": "db.t3.micro", "Engine": "mysql",
                           "MasterUsername": "admin", "MasterUserPassword": "S3cure-Passw0rd!", "AllocatedStorage": "20"})
if True:
    st.get_instance("my1")["db_instance_status"] = "available"
    q = rds_core.execute_sql(st, "my1", "CREATE TABLE `t` (`id` INT AUTO_INCREMENT PRIMARY KEY, `n` VARCHAR(10)) ENGINE=InnoDB")
    chk("rds mysql create", q.get("ok"), True)
    chk("rds mysql insert", rds_core.execute_sql(st, "my1", "INSERT INTO t (n) VALUES ('a'),('b')").get("ok"), True)
    chk("rds mysql show tables", rds_core.execute_sql(st, "my1", "SHOW TABLES").get("rows"), [["t"]])
    chk("rds mysql error code", "1146" in rds_core.execute_sql(st, "my1", "SELECT * FROM nope").get("message", ""), True)
    chk("rds mysql async", asyncio.run(rds_core.aexecute_sql(st, "my1", "SELECT COUNT(*) FROM t"))["rows"], [[2]])
print("FAILS", fails)
sys.exit(1 if fails else 0)
