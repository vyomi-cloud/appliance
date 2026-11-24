import boto3

waf = boto3.client("wafv2")
vis = lambda name: {"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True, "MetricName": name}
r = waf.create_web_acl(Name="facilities-acl", Scope="REGIONAL", DefaultAction={"Allow": {}}, VisibilityConfig=vis("facilities-acl"),
                       Rules=[{"Name": "rate", "Priority": 1, "Action": {"Block": {}},
                               "Statement": {"RateBasedStatement": {"Limit": 100, "AggregateKeyType": "IP"}}, "VisibilityConfig": vis("rate")}])
print("web ACL", r["Summary"]["ARN"])
