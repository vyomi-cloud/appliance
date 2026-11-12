"""ELBv2 gap sweep (wave 5b): target health reacting to a target's REAL EC2 instance
state (ec2.load-balancing.monitoring), real AWS/ApplicationELB HealthyHostCount /
UnHealthyHostCount CloudWatch metrics published on evaluation, and trust stores
(ec2.trust-stores) — a real CA bundle read from Vyomi's own S3 (nothing leaves the
simulator), associated with an HTTPS listener's mutual-TLS config.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_elbv2_gap_sweep_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import re

try:
    from core import elbv2_core as elb
    from core import vpc_core as vpc
    from core import cloudwatch_core as cw
    from core.aws_wire_router import AwsWireRouter
except ImportError:  # pragma: no cover - Pyodide flat layout
    import elbv2_core as elb  # type: ignore
    import vpc_core as vpc  # type: ignore
    import cloudwatch_core as cw  # type: ignore
    from aws_wire_router import AwsWireRouter  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _xid(body, tag):
    m = re.search(f"<{tag}>(.*?)</{tag}>", body)
    return m.group(1) if m else None


def run() -> int:
    r = AwsWireRouter()

    def elb_call(**p):
        resp = elb.dispatch(r.elbv2, p)
        if resp.status != 200:
            raise AssertionError((p.get("Action"), resp.status, resp.body))
        return resp.body

    # ── target health reacts to the real instance state ─────────────────
    lb = elb_call(Action="CreateLoadBalancer", Name="gap-lb", **{"Subnets.member.1": "subnet-a", "Subnets.member.2": "subnet-b"})
    lb_arn = _xid(lb, "LoadBalancerArn")
    tg = elb_call(Action="CreateTargetGroup", Name="gap-tg", Protocol="HTTP", Port="80", VpcId="vpc-1", TargetType="instance")
    tg_arn = _xid(tg, "TargetGroupArn")
    live = vpc.dispatch(r.vpc, {"Action": "RunInstances", "MinCount": "1", "MaxCount": "1"}).body
    iid = _xid(live, "instanceId")
    elb_call(Action="RegisterTargets", TargetGroupArn=tg_arn, **{"Targets.member.1.Id": iid})
    elb_call(Action="CreateListener", LoadBalancerArn=lb_arn, Protocol="HTTP", Port="80",
            **{"DefaultActions.member.1.Type": "forward", "DefaultActions.member.1.TargetGroupArn": tg_arn})
    health = elb_call(Action="DescribeTargetHealth", TargetGroupArn=tg_arn)
    _check("a running instance is really healthy", "<State>healthy</State>" in health)

    vpc.dispatch(r.vpc, {"Action": "StopInstances", "InstanceId.1": iid})
    health2 = elb_call(Action="DescribeTargetHealth", TargetGroupArn=tg_arn)
    _check("a stopped instance is really unhealthy, not deterministically healthy", "<State>unhealthy</State>" in health2)
    _check("the reason names the real failure", "Target.FailedHealthChecks" in health2 or "DeregistrationInProgress" in health2)

    # ── real AWS/ApplicationELB CloudWatch metrics on evaluation ─────────
    _check("UnHealthyHostCount was really ingested into the CloudWatch store",
           any(k.startswith("AWS/ApplicationELB\x1fUnHealthyHostCount\x1f") for k in r.cw.metrics))
    _check("HealthyHostCount was really ingested too",
           any(k.startswith("AWS/ApplicationELB\x1fHealthyHostCount\x1f") for k in r.cw.metrics))

    # ── trust stores (real CA bundle validation, read from Vyomi's own S3) ──
    r.s3.create_bucket("trust-bundles")
    from core import s3_object_core as s3core
    bundle = (b"-----BEGIN CERTIFICATE-----\nMIIBone\n-----END CERTIFICATE-----\n"
              b"-----BEGIN CERTIFICATE-----\nMIIBtwo\n-----END CERTIFICATE-----\n")
    s3core.put_object(r.s3, "trust-bundles", "ca.pem", bundle, {})
    elb_call(Action="CreateListener", LoadBalancerArn=lb_arn, Protocol="HTTPS", Port="443",
            **{"DefaultActions.member.1.Type": "forward", "DefaultActions.member.1.TargetGroupArn": tg_arn,
               "Certificates.member.1.CertificateArn": "arn:aws:acm:us-east-1:123456789012:certificate/dummy"})
    ts = elb_call(Action="CreateTrustStore", Name="gap-ts", CaCertificatesBundleS3Bucket="trust-bundles", CaCertificatesBundleS3Key="ca.pem")
    ts_arn = _xid(ts, "TrustStoreArn")
    _check("CA bundle was really parsed (2 certs)", "<NumberOfCaCertificates>2</NumberOfCaCertificates>" in ts)

    bad = elb.dispatch(r.elbv2, {"Action": "CreateTrustStore", "Name": "bad-ts",
                                 "CaCertificatesBundleS3Bucket": "trust-bundles", "CaCertificatesBundleS3Key": "missing.pem"})
    _check("a missing S3 object is rejected, not silently accepted", bad.status == 400)

    listeners = elb_call(Action="DescribeListeners", LoadBalancerArn=lb_arn)
    https_arn = re.findall(r"<ListenerArn>([^<]+)</ListenerArn>", listeners)[-1]
    elb_call(Action="ModifyListener", ListenerArn=https_arn, **{"MutualAuthentication.Mode": "verify", "MutualAuthentication.TrustStoreArn": ts_arn})
    assoc = elb_call(Action="DescribeTrustStoreAssociations", TrustStoreArn=ts_arn)
    _check("the trust store is really associated with the listener", https_arn in assoc)
    _check("deleting an in-use trust store is rejected",
           elb.dispatch(r.elbv2, {"Action": "DeleteTrustStore", "TrustStoreArn": ts_arn}).status == 400)
    elb_call(Action="ModifyListener", ListenerArn=https_arn, **{"MutualAuthentication.Mode": "off"})
    elb_call(Action="DeleteTrustStore", TrustStoreArn=ts_arn)

    print("RESULT: PASS — ELBv2 gap-sweep (real target health, CloudWatch metrics, trust stores) conforms.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
