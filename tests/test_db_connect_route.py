"""GET /_vyomi/db-connect: one paste-and-run connection record per database (user, real password, database, engine, port source)."""
import json
import urllib.parse

from core.aws_wire_router import AwsWireRouter

_H = {"content-type": "application/x-www-form-urlencoded",
      "authorization": "AWS4-HMAC-SHA256 Credential=t/20260101/us-east-1/rds/aws4_request, SignedHeaders=host, Signature=x"}


def _create(r, ident, engine, user, pw, db):
    body = urllib.parse.urlencode({"Version": "2014-10-31", "Action": "CreateDBInstance", "DBInstanceIdentifier": ident, "DBInstanceClass": "db.t3.micro",
                                   "Engine": engine, "MasterUsername": user, "MasterUserPassword": pw, "DBName": db, "AllocatedStorage": "20"}).encode()
    assert r.handle("POST", "/", {}, _H, body)["status"] == 200


def _rows(r):
    res = r.handle("GET", "/_vyomi/db-connect", {}, {}, b"")
    assert res["status"] == 200 and res["headers"]["content-type"] == "application/json"
    return {d["id"]: d for d in json.loads(res["body"])["databases"]}


def test_every_database_gets_its_real_credentials():
    r = AwsWireRouter()
    assert _rows(r) == {}
    _create(r, "shop-pg", "postgres", "appuser", "P@ss:w/rd#1", "shop")
    _create(r, "shop-my", "mysql", "root", "Pa55w0rd!", "orders")
    rows = _rows(r)
    pg, my = rows["shop-pg"], rows["shop-my"]
    assert (pg["engine"], pg["user"], pg["password"], pg["database"], pg["cloud"], pg["default_port"]) == ("postgres", "appuser", "P@ss:w/rd#1", "shop", "aws", 5432)
    assert (my["engine"], my["user"], my["password"], my["database"], my["default_port"]) == ("mysql", "root", "Pa55w0rd!", "orders", 3306)
    assert pg["key"] == "rds:shop-pg" and pg["host"] == "127.0.0.1"


def test_only_available_supported_engines_are_listed():
    r = AwsWireRouter()
    _create(r, "ora", "oracle-ee", "admin", "x", "o")          # not a Postgres/MySQL family: no connection string
    assert "ora" not in _rows(r)
