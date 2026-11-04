"""RDS RestoreDBInstanceFromS3 (AWS-09 leftover): a new instance is built from a logical dump / RDS Parquet export that
lives in the simulator's own S3 and the restored rows are really queryable.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_rds_restore_s3.py
"""
import gzip
import re
from urllib.parse import urlencode

from core.aws_wire_router import AwsWireRouter

ROLE = "arn:aws:iam::123456789012:role/rds-s3-ingest"
DUMP = """-- MySQL dump 10.13
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
DROP TABLE IF EXISTS `customers`;
CREATE TABLE `customers` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) DEFAULT NULL,
  `email` varchar(80) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_email` (`email`),
  KEY `idx_name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4;
LOCK TABLES `customers` WRITE;
INSERT INTO `customers` VALUES (1,'Ada','ada@example.com'),(2,'Linus','linus@example.com');
UNLOCK TABLES;
"""


def _auth(svc):
    return f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"


def q(r, action, params=None):
    body = urlencode({"Action": action, "Version": "2014-10-31", **(params or {})}).encode()
    out = r.handle("POST", "/", {}, {"authorization": _auth("rds"), "content-type": "application/x-www-form-urlencoded"}, body)
    return out["status"], out["body"].decode()


def s3(r, method, path, body=b""):
    return r.handle(method, path, {}, {"authorization": _auth("s3")}, body)


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def base(i, prefix="bk/"):
    return {"DBInstanceIdentifier": i, "DBInstanceClass": "db.t3.micro", "Engine": "mysql", "MasterUsername": "admin", "MasterUserPassword": "pw12345678",
            "SourceEngine": "mysql", "SourceEngineVersion": "8.0.36", "S3BucketName": "rds-backups", "S3IngestionRoleArn": ROLE, "S3Prefix": prefix}


def main():
    r = AwsWireRouter()
    for miss in ("S3BucketName", "S3IngestionRoleArn", "SourceEngine"):
        p = base("x1"); p.pop(miss)
        st, x = q(r, "RestoreDBInstanceFromS3", p)
        _check(f"missing {miss} -> MissingParameter", st == 400 and "MissingParameter" in x)
    st, x = q(r, "RestoreDBInstanceFromS3", {**base("x1"), "Engine": "postgres"})
    _check("non-mysql engine rejected", st == 400 and "mysql" in x)
    st, x = q(r, "RestoreDBInstanceFromS3", {**base("x1"), "S3IngestionRoleArn": "not-an-arn"})
    _check("bad role arn rejected", st == 400)
    st, x = q(r, "RestoreDBInstanceFromS3", base("x1"))
    _check("missing bucket -> InvalidS3BucketFault", st == 400 and "InvalidS3BucketFault" in x)
    s3(r, "PUT", "/rds-backups")
    st, x = q(r, "RestoreDBInstanceFromS3", base("x1"))
    _check("empty prefix -> InvalidS3BucketFault", st == 400 and "InvalidS3BucketFault" in x)
    s3(r, "PUT", "/rds-backups/bk/backup.xbstream", b"\x00xbstream")
    st, x = q(r, "RestoreDBInstanceFromS3", base("x1"))
    _check("an XtraBackup physical backup is refused honestly", st == 400 and "XtraBackup" in x)

    s3(r, "PUT", "/rds-backups/bk/dump.sql.gz", gzip.compress(DUMP.encode()))
    st, x = q(r, "RestoreDBInstanceFromS3", base("restored-db"))
    _check("restore from .sql.gz", st == 200 and "<DBInstanceStatus>available</DBInstanceStatus>" in x and "<Engine>mysql</Engine>" in x)
    res = r.rds.execute_sql("restored-db", "SELECT id, name, email FROM customers ORDER BY id")
    _check("restored rows are queryable", [list(x) for x in res["rows"]] == [[1, "Ada", "ada@example.com"], [2, "Linus", "linus@example.com"]])
    st, x = q(r, "RestoreDBInstanceFromS3", base("restored-db"))
    _check("duplicate identifier rejected", st == 400 and "DBInstanceAlreadyExists" in x)

    s3(r, "PUT", "/rds-backups/bad/dump.sql", b"CREATE TABLE ok (a int);\nINSERT INTO nope_table VALUES (1);\n")
    st, x = q(r, "RestoreDBInstanceFromS3", base("broken-db", "bad/"))
    _check("a failing statement leaves incompatible-restore", st == 200 and "incompatible-restore" in x)

    # snapshot export (Parquet) -> restore round trip where a Parquet reader exists (offline appliance)
    try:
        from core import parquet_pyarrow
        have = parquet_pyarrow.install()
    except Exception:
        have = False
    if have:
        q(r, "CreateDBInstance", {"DBInstanceIdentifier": "src", "Engine": "mysql", "DBInstanceClass": "db.t3.micro", "MasterUsername": "u", "MasterUserPassword": "pw12345678"})
        r.rds.execute_sql("src", "CREATE TABLE pets (id INTEGER, name TEXT)")
        r.rds.execute_sql("src", "INSERT INTO pets VALUES (1,'rex'),(2,'tom')")
        q(r, "CreateDBSnapshot", {"DBInstanceIdentifier": "src", "DBSnapshotIdentifier": "src-snap"})
        st, x = q(r, "StartExportTask", {"ExportTaskIdentifier": "exp1", "SourceArn": "arn:aws:rds:us-east-1:123456789012:snapshot:src-snap",
                                          "S3BucketName": "rds-backups", "S3Prefix": "exports", "IamRoleArn": ROLE, "KmsKeyId": "k"})
        _check("export task", st == 200 and "COMPLETE" in x)
        st, x = q(r, "RestoreDBInstanceFromS3", base("from-parquet", "exports/"))
        _check("restore from RDS Parquet export", st == 200 and "available" in x)
        res = r.rds.execute_sql("from-parquet", "SELECT id, name FROM pets ORDER BY id")
        _check("parquet rows restored", [list(x) for x in res["rows"]] == [[1, "rex"], [2, "tom"]])
    else:
        print("  skip parquet round trip (pyarrow missing)")
    print("rds restore-from-S3 conformance OK")


if __name__ == "__main__":
    main()
