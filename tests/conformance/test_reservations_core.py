"""DynamoDB reserved capacity + RDS capacity reservations (Vyomi-only service vyomi-reservations): records with REAL utilisation math
against the provisioned tables / running DB instances.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_reservations_core.py
"""
import json
from urllib.parse import urlencode

from core.aws_wire_router import AwsWireRouter

RES = "AWS4-HMAC-SHA256 Credential=T/20261105/us-east-1/vyomi-reservations/aws4_request, SignedHeaders=host, Signature=0"
DDB = "AWS4-HMAC-SHA256 Credential=T/20261105/us-east-1/dynamodb/aws4_request, SignedHeaders=host, Signature=0"
RDS = "AWS4-HMAC-SHA256 Credential=T/20261105/us-east-1/rds/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def res(r, op, body=None):
    o = r.handle("POST", "/" + op, {}, {"authorization": RES, "content-type": "application/json"}, json.dumps(body or {}).encode())
    return o["status"], json.loads(o["body"])


def main():
    r = AwsWireRouter()
    # --- DynamoDB
    s, v = res(r, "DescribeDynamoDBReservedCapacity")
    _check("empty", s == 200 and v["Reservations"] == [] and v["Utilization"]["write"]["UtilizationPercent"] is None)
    _check("units below minimum", res(r, "PurchaseDynamoDBReservedCapacity", {"CapacityType": "write", "Units": 50})[0] == 400)
    _check("units not multiple of 100", res(r, "PurchaseDynamoDBReservedCapacity", {"CapacityType": "write", "Units": 150})[0] == 400)
    _check("bad term", res(r, "PurchaseDynamoDBReservedCapacity", {"CapacityType": "write", "Units": 100, "TermYears": 2})[0] == 400)
    _check("bad type", res(r, "PurchaseDynamoDBReservedCapacity", {"CapacityType": "x", "Units": 100})[0] == 400)
    s, w = res(r, "PurchaseDynamoDBReservedCapacity", {"CapacityType": "write", "Units": 200, "TermYears": 3})
    _check("purchase", s == 200 and w["ReservationArn"].startswith("arn:aws:dynamodb::123456789012:reserved-capacity/"))
    for name, rcu, wcu in (("t-prov-1", 100, 120), ("t-prov-2", 50, 30)):
        o = r.handle("POST", "/", {}, {"authorization": DDB, "x-amz-target": "DynamoDB_20120810.CreateTable", "content-type": "application/x-amz-json-1.0"}, json.dumps({
            "TableName": name, "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}], "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
            "BillingMode": "PROVISIONED", "ProvisionedThroughput": {"ReadCapacityUnits": rcu, "WriteCapacityUnits": wcu}}).encode())
        assert o["status"] == 200, o
    r.handle("POST", "/", {}, {"authorization": DDB, "x-amz-target": "DynamoDB_20120810.CreateTable", "content-type": "application/x-amz-json-1.0"}, json.dumps({
        "TableName": "t-ondemand", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}], "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
        "BillingMode": "PAY_PER_REQUEST"}).encode())
    s, v = res(r, "DescribeDynamoDBReservedCapacity")
    wu = v["Utilization"]["write"]
    _check("write utilisation: reserved 200, provisioned 150 -> used 150, unused 50, 75%", (wu["ReservedUnits"], wu["ProvisionedUnits"], wu["UsedReservedUnits"], wu["UnusedReservedUnits"], wu["UtilizationPercent"]) == (200, 150, 150, 50, 75.0), wu)
    _check("on-demand table not counted", v["ProvisionedTables"] == 2)
    ru = v["Utilization"]["read"]
    _check("read side unreserved: provisioned 150, none reserved", (ru["ReservedUnits"], ru["UnreservedProvisionedUnits"], ru["UtilizationPercent"]) == (0, 150, None))
    res(r, "PurchaseDynamoDBReservedCapacity", {"CapacityType": "write", "Units": 100})
    s, v = res(r, "DescribeDynamoDBReservedCapacity")
    _check("second reservation adds up (300 reserved, 50% unused)", v["Utilization"]["write"]["ReservedUnits"] == 300 and v["Utilization"]["write"]["UtilizationPercent"] == 50.0)
    _check("delete reservation", res(r, "DeleteDynamoDBReservedCapacity", {"ReservationId": w["ReservationId"]})[0] == 200)
    _check("delete missing -> 404", res(r, "DeleteDynamoDBReservedCapacity", {"ReservationId": "nope"})[0] == 404)

    # --- RDS
    _check("bad class", res(r, "CreateRDSCapacityReservation", {"DBInstanceClass": "m5.large", "InstanceCount": 1})[0] == 400)
    _check("count 0", res(r, "CreateRDSCapacityReservation", {"DBInstanceClass": "db.t3.micro", "InstanceCount": 0})[0] == 400)
    _check("bad az", res(r, "CreateRDSCapacityReservation", {"DBInstanceClass": "db.t3.micro", "InstanceCount": 1, "AvailabilityZone": "mars-1"})[0] == 400)
    _check("az outside region", res(r, "CreateRDSCapacityReservation", {"DBInstanceClass": "db.t3.micro", "InstanceCount": 1, "AvailabilityZone": "eu-west-1a"})[0] == 400)
    _check("past end date", res(r, "CreateRDSCapacityReservation", {"DBInstanceClass": "db.t3.micro", "InstanceCount": 1, "EndDate": "2020-01-01T00:00:00Z"})[0] == 400)
    s, cr = res(r, "CreateRDSCapacityReservation", {"Name": "prod-pool", "DBInstanceClass": "db.t3.micro", "InstanceCount": 3, "AvailabilityZone": "us-east-1a"})
    _check("create with 0 matching instances -> 0% utilised", s == 200 and cr["MatchingInstances"] == 0 and cr["UnusedInstances"] == 3 and cr["UtilizationPercent"] == 0.0)
    _check("duplicate name", res(r, "CreateRDSCapacityReservation", {"Name": "prod-pool", "DBInstanceClass": "db.t3.micro", "InstanceCount": 1})[1]["__type"] == "ReservationAlreadyExists")

    def mk(i, cls, az):
        q = {"Action": "CreateDBInstance", "DBInstanceIdentifier": i, "DBInstanceClass": cls, "Engine": "postgres", "MasterUsername": "u", "MasterUserPassword": "password1",
             "AllocatedStorage": "20", "AvailabilityZone": az}
        o = r.handle("POST", "/", {}, {"authorization": RDS, "content-type": "application/x-www-form-urlencoded"}, urlencode(q).encode())
        assert o["status"] == 200, o["body"][:200]
    mk("db-a", "db.t3.micro", "us-east-1a")
    mk("db-b", "db.t3.micro", "us-east-1a")
    mk("db-c", "db.t3.micro", "us-east-1b")      # other AZ: not matched
    mk("db-d", "db.m5.large", "us-east-1a")      # other class: not matched
    s, v = res(r, "DescribeRDSCapacityReservations", {"ReservationId": cr["ReservationId"]})
    x = v["CapacityReservations"][0]
    _check("2 of 3 reserved slots used (matching class + AZ only), 66.7%", (x["MatchingInstances"], x["UsedInstances"], x["UnusedInstances"], x["UtilizationPercent"]) == (2, 2, 1, 66.7), x)
    s, c2 = res(r, "CreateRDSCapacityReservation", {"DBInstanceClass": "db.t3.micro", "InstanceCount": 1, "AvailabilityZone": "us-east-1a", "Engine": "mysql"})
    _check("engine filter honoured (no mysql instances)", c2["MatchingInstances"] == 0)
    s, c3 = res(r, "CreateRDSCapacityReservation", {"DBInstanceClass": "db.t3.micro", "InstanceCount": 1})
    _check("no AZ -> matches the class in any AZ; over-subscribed shows unreserved", c3["MatchingInstances"] == 3 and c3["UsedInstances"] == 1 and c3["UnreservedMatchingInstances"] == 2)
    s, cc = res(r, "CancelRDSCapacityReservation", {"ReservationId": cr["ReservationId"]})
    _check("cancel", cc["State"] == "cancelled")
    _check("cancel twice refused", res(r, "CancelRDSCapacityReservation", {"ReservationId": cr["ReservationId"]})[0] == 400)
    _check("unknown reservation", res(r, "DescribeRDSCapacityReservations", {"ReservationId": "x"})[0] == 404)
    _check("unknown op", res(r, "Nope")[0] == 404)
    print("reservations: all ok")


if __name__ == "__main__":
    main()
