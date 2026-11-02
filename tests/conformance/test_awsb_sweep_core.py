"""AWS sweep B2 conformance — real behaviour added to EventBridge/Kinesis/EC2/VPC/etc. consoles.
Run: PYTHONPATH=. python3 tests/conformance/test_awsb_sweep_core.py"""
import json

from core import sqs_core as sqs, eventbridge_core as eb, cloudwatch_core as cwc
from core.messaging_store import InMemoryMessagingStore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def eventbridge_pipe_metrics():
    s = InMemoryMessagingStore()
    cws = cwc.CloudWatchStore(); s.cw_store = cws
    sq = lambda a, b: sqs.dispatch(s, "AmazonSQS." + a, b).body
    src = sq("CreateQueue", {"QueueName": "ps"})["QueueUrl"]
    dst = sq("CreateQueue", {"QueueName": "pd"})["QueueUrl"]
    arn = lambda u: sq("GetQueueAttributes", {"QueueUrl": u})["Attributes"]["QueueArn"]
    eb.dispatch_pipes(s, "POST", "/v1/pipes/mp", body=json.dumps({"Source": arn(src), "Target": arn(dst)}).encode())
    sq("SendMessage", {"QueueUrl": src, "MessageBody": "a"})
    sq("SendMessage", {"QueueUrl": src, "MessageBody": "b"})
    d = [{"Name": "PipeName", "Value": "mp"}]
    tot = lambda m: (lambda x: sum(p[1] for p in x["points"]) if x else None)(cwc._series(cws, "AWS/EventBridge/Pipes", m, d))
    _check("pipe Execution = 2", tot("Execution") == 2.0)
    _check("pipe ExecutionSucceeded = 2", tot("ExecutionSucceeded") == 2.0)
    _check("no ExecutionFailed", tot("ExecutionFailed") is None)
    eb.dispatch_pipes(s, "POST", "/v1/pipes/bad", body=json.dumps({"Source": arn(src), "Target": "arn:aws:lambda:us-east-1:1:function:nope"}).encode())
    sq("SendMessage", {"QueueUrl": src, "MessageBody": "c"})
    _check("failed delivery -> ExecutionFailed",
           (lambda x: x and sum(p[1] for p in x["points"]) == 1.0)(cwc._series(cws, "AWS/EventBridge/Pipes", "ExecutionFailed", [{"Name": "PipeName", "Value": "bad"}])))


def eventbridge_integration():
    import threading, http.server
    got = []
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got.append((self.headers.get("x-api-key"), self.rfile.read(int(self.headers.get("Content-Length", 0)))))
            self.send_response(200); self.end_headers()
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    s = InMemoryMessagingStore()
    cws = cwc.CloudWatchStore(); s.cw_store = cws
    c = lambda a, b: eb.dispatch(s, "AWSEvents." + a, b)
    r = c("CreateConnection", {"Name": "cn", "AuthorizationType": "API_KEY", "AuthParameters": {"ApiKeyAuthParameters": {"ApiKeyName": "x-api-key", "ApiKeyValue": "sekret"}}})
    _check("CreateConnection -> AUTHORIZED", r.status == 200 and r.body["ConnectionState"] == "AUTHORIZED")
    carn = r.body["ConnectionArn"]
    d = c("DescribeConnection", {"Name": "cn"}).body
    _check("DescribeConnection never echoes the secret", "sekret" not in json.dumps(d) and d["AuthParameters"]["ApiKeyAuthParameters"]["ApiKeyName"] == "x-api-key")
    _check("duplicate connection rejected", c("CreateConnection", {"Name": "cn", "AuthorizationType": "BASIC", "AuthParameters": {"BasicAuthParameters": {}}}).body["__type"] == "ResourceAlreadyExistsException")
    _check("API_KEY without ApiKeyAuthParameters rejected", c("CreateConnection", {"Name": "z", "AuthorizationType": "API_KEY", "AuthParameters": {}}).body["__type"] == "ValidationException")
    _check("ListConnections", [x["Name"] for x in c("ListConnections", {}).body["Connections"]] == ["cn"])
    a = c("CreateApiDestination", {"Name": "ad", "ConnectionArn": carn, "InvocationEndpoint": f"http://127.0.0.1:{srv.server_port}/hook", "HttpMethod": "POST"})
    _check("CreateApiDestination ACTIVE, default rate 300", a.body["ApiDestinationState"] == "ACTIVE" and c("DescribeApiDestination", {"Name": "ad"}).body["InvocationRateLimitPerSecond"] == 300)
    _check("API destination needs an existing connection", c("CreateApiDestination", {"Name": "b", "ConnectionArn": "arn:x", "InvocationEndpoint": "http://x", "HttpMethod": "POST"}).body["__type"] == "ResourceNotFoundException")
    _check("connection in use cannot be deleted", c("DeleteConnection", {"Name": "cn"}).body["__type"] == "ResourceInUseException")
    c("PutRule", {"Name": "wr", "EventPattern": json.dumps({"source": ["my.app"]})})
    c("PutTargets", {"Rule": "wr", "Targets": [{"Id": "t", "Arn": a.body["ApiDestinationArn"]}]})
    c("PutEvents", {"Entries": [{"Source": "my.app", "DetailType": "x", "Detail": "{}"}]})
    _check("matching event really POSTed to the endpoint with the connection's API key", len(got) == 1 and got[0][0] == "sekret" and b"my.app" in got[0][1])
    c("DeauthorizeConnection", {"Name": "cn"})
    c("PutEvents", {"Entries": [{"Source": "my.app", "DetailType": "x", "Detail": "{}"}]})
    _check("deauthorized connection -> no delivery, FailedInvocations", len(got) == 1)
    srv.shutdown()
    c("DeleteApiDestination", {"Name": "ad"}); _check("connection deletable after its destination", c("DeleteConnection", {"Name": "cn"}).body["ConnectionState"] == "DELETING")
    # global endpoints
    buses = ["arn:aws:events:us-east-1:123456789012:event-bus/default", "arn:aws:events:us-west-2:123456789012:event-bus/default"]
    fo = {"FailoverConfig": {"Primary": {"HealthCheck": "arn:aws:route53:::healthcheck/abc"}, "Secondary": {"Route": "us-west-2"}}}
    e = c("CreateEndpoint", {"Name": "ge", "RoutingConfig": fo, "EventBuses": buses})
    _check("CreateEndpoint ACTIVE", e.body["State"] == "ACTIVE" and c("DescribeEndpoint", {"Name": "ge"}).body["EndpointId"].endswith(".veo"))
    _check("endpoint needs two buses", c("CreateEndpoint", {"Name": "g2", "RoutingConfig": fo, "EventBuses": buses[:1]}).body["__type"] == "ValidationException")
    _check("ListEndpoints", len(c("ListEndpoints", {}).body["Endpoints"]) == 1)
    c("UpdateEndpoint", {"Name": "ge", "ReplicationConfig": {"State": "DISABLED"}})
    _check("UpdateEndpoint persisted", c("DescribeEndpoint", {"Name": "ge"}).body["ReplicationConfig"]["State"] == "DISABLED")
    c("DeleteEndpoint", {"Name": "ge"}); _check("DeleteEndpoint", c("DescribeEndpoint", {"Name": "ge"}).body["__type"] == "ResourceNotFoundException")
    # TestEventPattern
    ev = {"id": "1", "account": "1", "source": "a.b", "time": "2026-01-01T00:00:00Z", "region": "us-east-1", "resources": [], "detail-type": "T", "detail": {"n": 5}}
    t = lambda pat, e=ev: c("TestEventPattern", {"EventPattern": json.dumps(pat), "Event": json.dumps(e)}).body
    _check("TestEventPattern match", t({"source": ["a.b"]})["Result"] is True)
    _check("TestEventPattern miss", t({"source": ["zzz"]})["Result"] is False)
    _check("TestEventPattern numeric/prefix operators", t({"detail": {"n": [{"numeric": [">", 3]}]}})["Result"] is True)
    _check("suffix/wildcard/ignore-case/$or/anything-but", all([
        t({"source": [{"suffix": ".b"}]})["Result"], t({"source": [{"wildcard": "a.*"}]})["Result"],
        t({"detail-type": [{"equals-ignore-case": "t"}]})["Result"], t({"$or": [{"source": ["no"]}, {"detail-type": ["T"]}]})["Result"],
        not t({"source": [{"anything-but": ["a.b"]}]})["Result"], t({"detail": {"n": [{"numeric": [">=", 5, "<", 6]}]}})["Result"]]))
    _check("TestEventPattern bad json", c("TestEventPattern", {"EventPattern": "{", "Event": "{}"}).body["__type"] == "InvalidEventPatternException")


def main():
    eventbridge_pipe_metrics()
    eventbridge_integration()
    print("\nAWS sweep B2: ALL GREEN")


if __name__ == "__main__":
    main()
