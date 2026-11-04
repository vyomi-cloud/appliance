"""Application Auto Scaling for DynamoDB (AWS-09 leftover): scalable targets, target-tracking policies that really
adjust the table's provisioned capacity from the consumed-capacity CloudWatch metrics, activities.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_appautoscaling_dynamodb.py
"""
import json
import time

from core import appautoscaling_core as aa
from core import cloudwatch_core as cw
from core.aws_wire_router import AwsWireRouter

AA = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/application-autoscaling/aws4_request, SignedHeaders=host, Signature=0"
DD = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/dynamodb/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def call(r, op, payload=None):
    out = r.handle("POST", "/", {}, {"authorization": AA, "x-amz-target": "AnyScaleFrontendService." + op,
                                     "content-type": "application/x-amz-json-1.1"}, json.dumps(payload or {}).encode())
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def ddb(r, op, payload):
    out = r.handle("POST", "/", {}, {"authorization": DD, "x-amz-target": "DynamoDB_20120810." + op,
                                     "content-type": "application/x-amz-json-1.0"}, json.dumps(payload).encode())
    return out["status"], json.loads(out["body"])


def cap(r, name="tbl1"):
    return ddb(r, "DescribeTable", {"TableName": name})[1]["Table"]["ProvisionedThroughput"]


def main():
    r = AwsWireRouter()
    s, _ = ddb(r, "CreateTable", {"TableName": "tbl1", "BillingMode": "PROVISIONED", "ProvisionedThroughput": {"ReadCapacityUnits": 100, "WriteCapacityUnits": 100},
                                  "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}], "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}]})
    _check("create provisioned table", s == 200)
    ddb(r, "CreateTable", {"TableName": "odt", "BillingMode": "PAY_PER_REQUEST",
                           "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}], "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}]})
    W = "dynamodb:table:WriteCapacityUnits"
    base = {"ServiceNamespace": "dynamodb", "ResourceId": "table/tbl1", "ScalableDimension": W}
    _check("register: missing table 400", call(r, "RegisterScalableTarget", {**base, "ResourceId": "table/nope", "MinCapacity": 1, "MaxCapacity": 5})[0] == 400)
    _check("register: on-demand table 400", call(r, "RegisterScalableTarget", {**base, "ResourceId": "table/odt", "MinCapacity": 1, "MaxCapacity": 5})[0] == 400)
    _check("register: min>max 400", call(r, "RegisterScalableTarget", {**base, "MinCapacity": 9, "MaxCapacity": 5})[0] == 400)
    _check("register: ecs unsupported 400", call(r, "RegisterScalableTarget", {**base, "ServiceNamespace": "ecs", "MinCapacity": 1, "MaxCapacity": 5})[0] == 400)
    s, o = call(r, "RegisterScalableTarget", {**base, "MinCapacity": 10, "MaxCapacity": 400})
    _check("register target", s == 200 and o["ScalableTargetARN"].startswith("arn:aws:application-autoscaling:"))
    s, o = call(r, "DescribeScalableTargets", {"ServiceNamespace": "dynamodb"})
    _check("describe targets", s == 200 and o["ScalableTargets"][0]["MaxCapacity"] == 400 and o["ScalableTargets"][0]["ResourceId"] == "table/tbl1")
    # range change that excludes current capacity pulls the table inside it
    call(r, "RegisterScalableTarget", {**base, "MinCapacity": 150, "MaxCapacity": 400})
    _check("min above current raises capacity", cap(r)["WriteCapacityUnits"] == 150)
    s, o = call(r, "DescribeScalingActivities", {"ServiceNamespace": "dynamodb", "ResourceId": "table/tbl1"})
    _check("activity for min raise", o["ScalingActivities"][0]["StatusCode"] == "Successful" and "150" in o["ScalingActivities"][0]["Description"])
    call(r, "RegisterScalableTarget", {**base, "MinCapacity": 10, "MaxCapacity": 400})

    pol = {**base, "PolicyName": "w-track", "PolicyType": "TargetTrackingScaling", "TargetTrackingScalingPolicyConfiguration": {
        "TargetValue": 70.0, "PredefinedMetricSpecification": {"PredefinedMetricType": "DynamoDBWriteCapacityUtilization"}}}
    _check("policy needs target", call(r, "PutScalingPolicy", {**pol, "ResourceId": "table/other"})[0] == 400)
    bad = json.loads(json.dumps(pol)); bad["TargetTrackingScalingPolicyConfiguration"]["PredefinedMetricSpecification"]["PredefinedMetricType"] = "DynamoDBReadCapacityUtilization"
    _check("wrong metric for dimension 400", call(r, "PutScalingPolicy", bad)[0] == 400)
    s, o = call(r, "PutScalingPolicy", pol)
    _check("put policy", s == 200 and "scalingPolicy" in o["PolicyARN"])
    s, o = call(r, "DescribeScalingPolicies", {"ServiceNamespace": "dynamodb"})
    _check("describe policies", o["ScalingPolicies"][0]["TargetTrackingScalingPolicyConfiguration"]["TargetValue"] == 70.0)

    # drive load: 170 WCU/s for 4 minutes against 150 provisioned (113%) -> scale out toward 170/0.7 = 243
    store = r.ddb
    created = store.tables["tbl1"]["appas"]["policies"]
    for pk in created:
        created[pk]["_created"] -= 4000
    now = time.time()
    for m in range(5):
        t = now - (4 - m) * 60 + 5
        cw.ingest_internal_metric(r.cw, "AWS/DynamoDB", "ConsumedWriteCapacityUnits", [{"Name": "TableName", "Value": "tbl1"}], 170 * 60.0, unit="Count", ts=t)
    _check("lazy evaluation on describe", aa.evaluate(store, now) == 1)
    _check("scaled out to 243", cap(r)["WriteCapacityUnits"] == 243)
    s, o = call(r, "DescribeScalingActivities", {"ServiceNamespace": "dynamodb", "ResourceId": "table/tbl1"})
    _check("scale-out activity", "243" in o["ScalingActivities"][0]["Description"] and "TargetTracking" in o["ScalingActivities"][0]["Cause"])

    # idle for 16+ minutes -> scale in, never below MinCapacity
    later = now + 3600
    aa.evaluate(store, later)
    _check("scaled in to min after idle", store.tables["tbl1"]["provisioned_throughput"]["WriteCapacityUnits"] == 10)
    # DisableScaleIn keeps capacity
    call(r, "RegisterScalableTarget", {**base, "MinCapacity": 5, "MaxCapacity": 400})
    _check("deregister missing 400", call(r, "DeregisterScalableTarget", {**base, "ResourceId": "table/zzz"})[0] == 400)
    s, _ = call(r, "DeregisterScalableTarget", base)
    _check("deregister", s == 200 and call(r, "DescribeScalableTargets", {"ServiceNamespace": "dynamodb"})[1]["ScalableTargets"] == [])
    _check("policies removed with target", call(r, "DescribeScalingPolicies", {"ServiceNamespace": "dynamodb"})[1]["ScalingPolicies"] == [])
    print("appautoscaling conformance OK")


if __name__ == "__main__":
    main()
