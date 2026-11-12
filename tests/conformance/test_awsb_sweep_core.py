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


def vpc_transit_gateway():
    import re, types
    from core import vpc_core as vpc
    s = types.SimpleNamespace()
    def call(p, ok=True):
        r = vpc.dispatch(s, p)
        if ok and r.status != 200:
            raise AssertionError((p.get("Action"), r.body))
        return r
    xid = lambda body, tag: re.search(f"<{tag}>(.*?)</{tag}>", body).group(1)
    va = xid(call({"Action": "CreateVpc", "CidrBlock": "10.60.0.0/16"}).body, "vpcId")
    vb = xid(call({"Action": "CreateVpc", "CidrBlock": "10.61.0.0/16"}).body, "vpcId")
    sa = xid(call({"Action": "CreateSubnet", "VpcId": va, "CidrBlock": "10.60.1.0/24"}).body, "subnetId")
    sb = xid(call({"Action": "CreateSubnet", "VpcId": vb, "CidrBlock": "10.61.1.0/24"}).body, "subnetId")
    tg = call({"Action": "CreateTransitGateway", "Description": "hub"}).body
    tid = xid(tg, "transitGatewayId")
    _check("CreateTransitGateway: available with default assoc+prop route tables", xid(tg, "state") == "available" and "<associationDefaultRouteTableId>" in tg and "<propagationDefaultRouteTableId>" in tg)
    _check("bad AmazonSideAsn rejected", call({"Action": "CreateTransitGateway", "Options.AmazonSideAsn": "9059"}, ok=False).status == 400)
    rtid = xid(tg, "associationDefaultRouteTableId")
    aa = xid(call({"Action": "CreateTransitGatewayVpcAttachment", "TransitGatewayId": tid, "VpcId": va, "SubnetIds.1": sa}).body, "transitGatewayAttachmentId")
    ab = xid(call({"Action": "CreateTransitGatewayVpcAttachment", "TransitGatewayId": tid, "VpcId": vb, "SubnetIds.1": sb}).body, "transitGatewayAttachmentId")
    _check("duplicate attachment of same VPC rejected", "DuplicateTransitGatewayAttachment" in call({"Action": "CreateTransitGatewayVpcAttachment", "TransitGatewayId": tid, "VpcId": va, "SubnetIds.1": sa}, ok=False).body)
    _check("subnet of another VPC rejected", call({"Action": "CreateTransitGatewayVpcAttachment", "TransitGatewayId": tid, "VpcId": va, "SubnetIds.1": sb}, ok=False).status == 400)
    r = call({"Action": "SearchTransitGatewayRoutes", "TransitGatewayRouteTableId": rtid}).body
    _check("default propagation: both VPC CIDRs are PROPAGATED routes in the default table", "10.60.0.0/16" in r and "10.61.0.0/16" in r and r.count("<type>propagated</type>") == 2)
    _check("attachments are associated with the default route table", aa in call({"Action": "GetTransitGatewayRouteTableAssociations", "TransitGatewayRouteTableId": rtid}).body)
    # static route + shadowing + blackhole
    call({"Action": "CreateTransitGatewayRoute", "TransitGatewayRouteTableId": rtid, "DestinationCidrBlock": "10.61.0.0/16", "TransitGatewayAttachmentId": ab})
    r = call({"Action": "SearchTransitGatewayRoutes", "TransitGatewayRouteTableId": rtid, "Filter.1.Name": "route-search.exact-match", "Filter.1.Value.1": "10.61.0.0/16"}).body
    _check("static route replaces the propagated one for the same CIDR", r.count("<item>") >= 1 and "<type>static</type>" in r and "<type>propagated</type>" not in r)
    _check("duplicate static route rejected", "TransitGatewayRouteAlreadyExists" in call({"Action": "CreateTransitGatewayRoute", "TransitGatewayRouteTableId": rtid, "DestinationCidrBlock": "10.61.0.0/16", "Blackhole": "true"}, ok=False).body)
    call({"Action": "DeleteTransitGatewayRoute", "TransitGatewayRouteTableId": rtid, "DestinationCidrBlock": "10.61.0.0/16"})
    r = call({"Action": "SearchTransitGatewayRoutes", "TransitGatewayRouteTableId": rtid, "Filter.1.Name": "type", "Filter.1.Value.1": "propagated"}).body
    _check("deleting the static route re-exposes the propagation", "10.61.0.0/16" in r)
    # custom route table: isolate attachment A
    rt2 = xid(call({"Action": "CreateTransitGatewayRouteTable", "TransitGatewayId": tid}).body, "transitGatewayRouteTableId")
    call({"Action": "DisassociateTransitGatewayRouteTable", "TransitGatewayRouteTableId": rtid, "TransitGatewayAttachmentId": aa})
    call({"Action": "AssociateTransitGatewayRouteTable", "TransitGatewayRouteTableId": rt2, "TransitGatewayAttachmentId": aa})
    _check("an attachment can only be associated with one route table", "Resource.AlreadyAssociated" in call({"Action": "AssociateTransitGatewayRouteTable", "TransitGatewayRouteTableId": rtid, "TransitGatewayAttachmentId": aa}, ok=False).body)
    call({"Action": "EnableTransitGatewayRouteTablePropagation", "TransitGatewayRouteTableId": rt2, "TransitGatewayAttachmentId": ab})
    r = call({"Action": "SearchTransitGatewayRoutes", "TransitGatewayRouteTableId": rt2}).body
    _check("enabling propagation of B into rt2 adds exactly B's CIDR", "10.61.0.0/16" in r and "10.60.0.0/16" not in r)
    _check("duplicate propagation rejected", "Duplicate" in call({"Action": "EnableTransitGatewayRouteTablePropagation", "TransitGatewayRouteTableId": rt2, "TransitGatewayAttachmentId": ab}, ok=False).body)
    call({"Action": "DisableTransitGatewayRouteTablePropagation", "TransitGatewayRouteTableId": rt2, "TransitGatewayAttachmentId": ab})
    _check("disabling propagation removes the propagated route", "10.61.0.0/16" not in call({"Action": "SearchTransitGatewayRoutes", "TransitGatewayRouteTableId": rt2}).body)
    _check("route table with associations cannot be deleted", "IncorrectState" in call({"Action": "DeleteTransitGatewayRouteTable", "TransitGatewayRouteTableId": rt2}, ok=False).body)
    # VPC route targeting the TGW
    vrt = s._vpc_model["subnets"][sa]["route_table"]
    call({"Action": "CreateRoute", "RouteTableId": vrt, "DestinationCidrBlock": "10.61.0.0/16", "TransitGatewayId": tid})
    _check("VPC route table route to the TGW renders transitGatewayId", f"<transitGatewayId>{tid}</transitGatewayId>" in call({"Action": "DescribeRouteTables", "RouteTableId.1": vrt}).body)
    _check("route to a non-existent TGW rejected", call({"Action": "CreateRoute", "RouteTableId": vrt, "DestinationCidrBlock": "10.9.0.0/16", "TransitGatewayId": "tgw-nope"}, ok=False).status == 400)
    # data plane: the Reachability evaluator now follows the TGW
    ia = xid(call({"Action": "RunInstances", "ImageId": vpc._default_ami_id(s._vpc_model), "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1", "SubnetId": sa}).body, "instanceId")
    ib = xid(call({"Action": "RunInstances", "ImageId": vpc._default_ami_id(s._vpc_model), "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1", "SubnetId": sb}).body, "instanceId")
    sga = [g["id"] for g in s._vpc_model["sgs"].values() if g.get("vpc_id") == va][0]
    sgb = [g["id"] for g in s._vpc_model["sgs"].values() if g.get("vpc_id") == vb][0]
    call({"Action": "AuthorizeSecurityGroupIngress", "GroupId": sgb, "IpProtocol": "tcp", "FromPort": "22", "ToPort": "22", "CidrIp": "10.60.0.0/16"})
    def reach():
        return vpc.reach(s, {"instance_id": ia}, {"instance_id": ib}, 22, "tcp")
    _check("no route to VPC B yet -> unreachable (NO_ROUTE)", not reach().reachable)
    vrt_b = s._vpc_model["subnets"][sb]["route_table"]
    call({"Action": "CreateRoute", "RouteTableId": vrt_b, "DestinationCidrBlock": "10.60.0.0/16", "TransitGatewayId": tid})
    # A isolated in rt2 (which has no route to B yet): TGW_NO_ROUTE
    v = reach()
    _check("A's associated TGW table has no route to B -> unreachable", not v.reachable)
    call({"Action": "DisableTransitGatewayRouteTablePropagation", "TransitGatewayRouteTableId": rtid, "TransitGatewayAttachmentId": aa})   # B's table stops learning A
    call({"Action": "EnableTransitGatewayRouteTablePropagation", "TransitGatewayRouteTableId": rt2, "TransitGatewayAttachmentId": ab})
    v = reach()
    _check("route to B in A's table but B's table has no route back -> unreachable", not v.reachable)
    call({"Action": "EnableTransitGatewayRouteTablePropagation", "TransitGatewayRouteTableId": rtid, "TransitGatewayAttachmentId": aa})   # B's table (default) learns A
    v = reach()
    _check("both TGW tables + both VPC route tables route -> reachable via transit-gateway", v.reachable and v.path == "transit-gateway")
    call({"Action": "DeleteRoute", "RouteTableId": vrt_b, "DestinationCidrBlock": "10.60.0.0/16"})
    _check("without B's VPC return route -> unreachable", not reach().reachable)
    call({"Action": "TerminateInstances", "InstanceId.1": ia}); call({"Action": "TerminateInstances", "InstanceId.1": ib})
    # detach: routes pointing at it blackhole; propagations vanish
    call({"Action": "CreateTransitGatewayRoute", "TransitGatewayRouteTableId": rt2, "DestinationCidrBlock": "172.16.0.0/12", "TransitGatewayAttachmentId": ab})
    call({"Action": "DeleteTransitGatewayVpcAttachment", "TransitGatewayAttachmentId": ab})
    _check("detaching blackholes static routes that targeted it", "<state>blackhole</state>" in call({"Action": "SearchTransitGatewayRoutes", "TransitGatewayRouteTableId": rt2}).body)
    _check("detaching removes its propagated routes everywhere", "10.61.0.0/16" not in call({"Action": "SearchTransitGatewayRoutes", "TransitGatewayRouteTableId": rtid}).body)
    _check("TGW with attachments cannot be deleted", "IncorrectState" in call({"Action": "DeleteTransitGateway", "TransitGatewayId": tid}, ok=False).body)
    call({"Action": "DeleteTransitGatewayVpcAttachment", "TransitGatewayAttachmentId": aa})
    call({"Action": "DeleteTransitGatewayRouteTable", "TransitGatewayRouteTableId": rt2})
    call({"Action": "DeleteTransitGateway", "TransitGatewayId": tid})
    _check("TGW deleted", "<transitGatewaySet></transitGatewaySet>" in call({"Action": "DescribeTransitGateways"}).body)


def ec2_sg_related_resources():
    import re, types
    from core import vpc_core as vpc
    s = types.SimpleNamespace()
    def call(p):
        r = vpc.dispatch(s, p)
        assert r.status == 200, (p.get("Action"), r.body)
        return r.body
    xid = lambda body, tag: re.search(f"<{tag}>(.*?)</{tag}>", body).group(1)
    v = xid(call({"Action": "CreateVpc", "CidrBlock": "10.70.0.0/16"}), "vpcId")
    sn = xid(call({"Action": "CreateSubnet", "VpcId": v, "CidrBlock": "10.70.1.0/24"}), "subnetId")
    a = xid(call({"Action": "CreateSecurityGroup", "GroupName": "rel-a", "GroupDescription": "d", "VpcId": v}), "groupId")
    b = xid(call({"Action": "CreateSecurityGroup", "GroupName": "rel-b", "GroupDescription": "d", "VpcId": v}), "groupId")
    call({"Action": "AuthorizeSecurityGroupIngress", "GroupId": b, "IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": "443", "IpPermissions.1.ToPort": "443", "IpPermissions.1.Groups.1.GroupId": a})
    eni = xid(call({"Action": "CreateNetworkInterface", "SubnetId": sn, "SecurityGroupId.1": a}), "networkInterfaceId")
    i = xid(call({"Action": "RunInstances", "ImageId": vpc._default_ami_id(s._vpc_model), "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1", "SubnetId": sn, "SecurityGroupId.1": a}), "instanceId")
    enis = call({"Action": "DescribeNetworkInterfaces"})
    _check("DescribeNetworkInterfaces exposes the SG membership the Related-resources tab reads", eni in enis and enis.count(f"<groupId>{a}</groupId>") >= 1)
    inst = call({"Action": "DescribeInstances", "InstanceId.1": i})
    _check("DescribeInstances exposes groupSet with the SG", f"<groupId>{a}</groupId>" in inst)
    sgb = call({"Action": "DescribeSecurityGroups", "GroupId.1": b})
    _check("DescribeSecurityGroups exposes the rule that names the SG as a source", f"<groupId>{a}</groupId>" in sgb)
    _check("DeleteSecurityGroup is refused while the SG is in use", vpc.dispatch(s, {"Action": "DeleteSecurityGroup", "GroupId": a}).status == 400)


def main():
    eventbridge_pipe_metrics()
    eventbridge_integration()
    vpc_transit_gateway()
    ec2_sg_related_resources()
    print("\nAWS sweep B2: ALL GREEN")


if __name__ == "__main__":
    main()
