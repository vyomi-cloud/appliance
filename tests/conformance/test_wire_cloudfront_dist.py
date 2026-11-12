"""CloudFront distributions / invalidations / OAC / OAI / policies / functions / tags over the router with a real boto3 client."""
import os
import sys

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(__file__))
from _wire_boto import make_clients  # noqa: E402


def _cf():
    _, client = make_clients()
    return client("cloudfront")


def _cfg(ref="r1", enabled=False, alias=None, **extra):
    cfg = {"CallerReference": ref, "Comment": "c", "Enabled": enabled,
           "Origins": {"Quantity": 1, "Items": [{"Id": "o1", "DomainName": "b.s3.amazonaws.com", "S3OriginConfig": {"OriginAccessIdentity": ""}}]},
           "DefaultCacheBehavior": {"TargetOriginId": "o1", "ViewerProtocolPolicy": "redirect-to-https",
                                    "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6"}}
    if alias:
        cfg["Aliases"] = {"Quantity": 1, "Items": [alias]}
    cfg.update(extra)
    return cfg


def _code(e):
    return e.value.response["Error"]["Code"]


def test_distribution_lifecycle_and_validation():
    cf = _cf()
    r = cf.create_distribution(DistributionConfig=_cfg(alias="www.example.com"))
    did, etag = r["Distribution"]["Id"], r["ETag"]
    assert r["Distribution"]["DomainName"].endswith(".cloudfront.net") and r["Distribution"]["Status"] == "Deployed"
    assert cf.create_distribution(DistributionConfig=_cfg(alias="www.example.com"))["Distribution"]["Id"] == did   # idempotent CallerReference
    with pytest.raises(ClientError) as e:
        cf.create_distribution(DistributionConfig=_cfg(ref="r2", alias="www.example.com"))
    assert _code(e) == "CNAMEAlreadyExists"
    bad = _cfg(ref="r3")
    bad["DefaultCacheBehavior"]["TargetOriginId"] = "nope"
    with pytest.raises(ClientError) as e:
        cf.create_distribution(DistributionConfig=bad)
    assert _code(e) == "NoSuchOrigin"
    assert cf.list_distributions()["DistributionList"]["Items"][0]["Id"] == did
    cfg = cf.get_distribution_config(Id=did)
    assert cfg["DistributionConfig"]["Aliases"]["Items"] == ["www.example.com"]
    new = cfg["DistributionConfig"]
    new["Comment"] = "updated"
    with pytest.raises(ClientError) as e:
        cf.update_distribution(Id=did, DistributionConfig=new, IfMatch="stale")
    assert _code(e) == "PreconditionFailed"
    u = cf.update_distribution(Id=did, DistributionConfig=new, IfMatch=cfg["ETag"])
    assert cf.get_distribution(Id=did)["Distribution"]["DistributionConfig"]["Comment"] == "updated"
    new["Enabled"] = True
    u = cf.update_distribution(Id=did, DistributionConfig=new, IfMatch=u["ETag"])
    with pytest.raises(ClientError) as e:
        cf.delete_distribution(Id=did, IfMatch=u["ETag"])
    assert _code(e) == "DistributionNotDisabled"
    new["Enabled"] = False
    u = cf.update_distribution(Id=did, DistributionConfig=new, IfMatch=u["ETag"])
    cf.delete_distribution(Id=did, IfMatch=u["ETag"])
    with pytest.raises(ClientError) as e:
        cf.get_distribution(Id=did)
    assert _code(e) == "NoSuchDistribution"


def test_invalidations_tags_oac_policies():
    cf = _cf()
    oac = cf.create_origin_access_control(OriginAccessControlConfig={"Name": "oac", "SigningProtocol": "sigv4", "SigningBehavior": "always", "OriginAccessControlOriginType": "s3"})
    oid = oac["OriginAccessControl"]["Id"]
    cp = cf.create_cache_policy(CachePolicyConfig={"Name": "mine", "MinTTL": 0, "DefaultTTL": 60, "MaxTTL": 600,
                                                   "ParametersInCacheKeyAndForwardedToOrigin": {"EnableAcceptEncodingGzip": True, "HeadersConfig": {"HeaderBehavior": "none"},
                                                                                                "CookiesConfig": {"CookieBehavior": "none"}, "QueryStringsConfig": {"QueryStringBehavior": "none"}}})
    cpid = cp["CachePolicy"]["Id"]
    types = {i["Type"] for i in cf.list_cache_policies()["CachePolicyList"]["Items"]}
    assert types == {"managed", "custom"}
    with pytest.raises(ClientError) as e:
        cf.delete_cache_policy(Id="658327ea-f89d-4fab-a63d-7e88639e58f6", IfMatch="x")
    assert _code(e) == "IllegalDelete"
    cfg = _cfg(ref="x")
    cfg["Origins"]["Items"][0] = {"Id": "o1", "DomainName": "b.s3.amazonaws.com", "OriginAccessControlId": oid, "S3OriginConfig": {"OriginAccessIdentity": ""}}
    cfg["DefaultCacheBehavior"]["CachePolicyId"] = cpid
    d = cf.create_distribution(DistributionConfig=cfg)["Distribution"]
    with pytest.raises(ClientError) as e:
        cf.delete_origin_access_control(Id=oid, IfMatch=cf.get_origin_access_control(Id=oid)["ETag"])
    assert _code(e) == "OriginAccessControlInUse"
    with pytest.raises(ClientError) as e:
        cf.delete_cache_policy(Id=cpid, IfMatch=cf.get_cache_policy(Id=cpid)["ETag"])
    assert _code(e) == "CachePolicyInUse"
    assert cf.list_distributions_by_cache_policy_id(CachePolicyId=cpid)["DistributionIdList"]["Items"] == [d["Id"]]
    inv = cf.create_invalidation(DistributionId=d["Id"], InvalidationBatch={"Paths": {"Quantity": 2, "Items": ["/a/*", "/b.html"]}, "CallerReference": "i1"})["Invalidation"]
    assert cf.get_invalidation(DistributionId=d["Id"], Id=inv["Id"])["Invalidation"]["InvalidationBatch"]["Paths"]["Items"] == ["/a/*", "/b.html"]
    assert cf.list_invalidations(DistributionId=d["Id"])["InvalidationList"]["Items"][0]["Id"] == inv["Id"]
    with pytest.raises(ClientError) as e:
        cf.create_invalidation(DistributionId=d["Id"], InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["nolead"]}, "CallerReference": "i2"})
    assert _code(e) == "InvalidArgument"
    arn = d["ARN"]
    cf.tag_resource(Resource=arn, Tags={"Items": [{"Key": "env", "Value": "dev"}]})
    assert cf.list_tags_for_resource(Resource=arn)["Tags"]["Items"] == [{"Key": "env", "Value": "dev"}]
    cf.untag_resource(Resource=arn, TagKeys={"Items": ["env"]})
    assert cf.list_tags_for_resource(Resource=arn)["Tags"]["Items"] == []
    oai = cf.create_cloud_front_origin_access_identity(CloudFrontOriginAccessIdentityConfig={"CallerReference": "o", "Comment": "x"})
    assert oai["CloudFrontOriginAccessIdentity"]["S3CanonicalUserId"]
    assert len(cf.list_cloud_front_origin_access_identities()["CloudFrontOriginAccessIdentityList"]["Items"]) == 1
    cf.create_origin_request_policy(OriginRequestPolicyConfig={"Name": "orp", "HeadersConfig": {"HeaderBehavior": "none"}, "CookiesConfig": {"CookieBehavior": "none"}, "QueryStringsConfig": {"QueryStringBehavior": "none"}})
    cf.create_response_headers_policy(ResponseHeadersPolicyConfig={"Name": "rhp"})
    assert cf.get_cache_policy_config(Id=cpid)["CachePolicyConfig"]["Name"] == "mine"


def test_functions_and_monitoring():
    cf = _cf()
    code = b"function handler(event) { return event.request; }"
    f = cf.create_function(Name="fn", FunctionConfig={"Comment": "c", "Runtime": "cloudfront-js-2.0"}, FunctionCode=code)
    assert f["FunctionSummary"]["FunctionMetadata"]["Stage"] == "DEVELOPMENT"
    with pytest.raises(ClientError) as e:
        cf.create_function(Name="bad", FunctionConfig={"Comment": "c", "Runtime": "cloudfront-js-2.0"}, FunctionCode=b"var x = 1;")
    assert _code(e) == "InvalidArgument"
    assert cf.get_function(Name="fn", Stage="DEVELOPMENT")["FunctionCode"].read() == code
    p = cf.publish_function(Name="fn", IfMatch=f["ETag"])
    assert p["FunctionSummary"]["FunctionMetadata"]["Stage"] == "LIVE"
    assert cf.describe_function(Name="fn", Stage="LIVE")["FunctionSummary"]["Name"] == "fn"
    cfg = _cfg(ref="fnd")
    cfg["DefaultCacheBehavior"]["FunctionAssociations"] = {"Quantity": 1, "Items": [{"EventType": "viewer-request", "FunctionARN": f["FunctionSummary"]["FunctionMetadata"]["FunctionARN"]}]}
    d = cf.create_distribution(DistributionConfig=cfg)["Distribution"]
    with pytest.raises(ClientError) as e:
        cf.delete_function(Name="fn", IfMatch=cf.describe_function(Name="fn", Stage="DEVELOPMENT")["ETag"])
    assert _code(e) == "FunctionInUse"
    assert cf.list_functions()["FunctionList"]["Items"][0]["Name"] == "fn"
    cf.create_monitoring_subscription(DistributionId=d["Id"], MonitoringSubscription={"RealtimeMetricsSubscriptionConfig": {"RealtimeMetricsSubscriptionStatus": "Enabled"}})
    assert cf.get_monitoring_subscription(DistributionId=d["Id"])["MonitoringSubscription"]["RealtimeMetricsSubscriptionConfig"]["RealtimeMetricsSubscriptionStatus"] == "Enabled"
    cf.delete_monitoring_subscription(DistributionId=d["Id"])
    st = cf.copy_distribution(PrimaryDistributionId=d["Id"], CallerReference="cp1", Staging=True)["Distribution"]
    assert st["Id"] != d["Id"]
