"""Security scanning core: vuln scan, audit classifier, deterministic detector, Security Hub + GuardDuty wire.
Run: PYTHONPATH=. <venv python> tests/conformance/test_secscan_core.py"""
import datetime
import json
import sys
from types import SimpleNamespace

from core import secscan_core as sc
from core import vuln_scan_core as vs

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)
    ok += 1


# ── version compare + advisories ─────────────────────────────────────────────
c = vs.version_cmp
check(c("1.1.1k-r0", "1.1.1n") < 0 and c("3.0.2", "3.0.2") == 0 and c("1.9.5p1", "1.9.5p2") < 0 and c("2.14.1", "2.15.0") < 0, "version order")
cfg = {"history": [{"created_by": "/bin/sh -c apk add --no-cache openssl=1.1.1k-r0 curl=8.5.0-r0 && pip install requests==2.19.0 pyyaml==6.0"},
                   {"created_by": "npm install lodash@4.17.15"}], "config": {"Env": ["PYTHON_VERSION=3.8.12"]}}
r = vs.scan_image(cfg, "python", "3.8-slim", today=datetime.date(2026, 11, 4))
ids = {(f["vulnerabilityId"], f["package"]) for f in r["findings"]}
check(("CVE-2022-0778", "openssl") in ids and ("CVE-2018-18074", "requests") in ids and ("CVE-2020-8203", "lodash") in ids, "pinned vulns found")
check(not any(f["package"] == "curl" for f in r["findings"]) and not any(f["package"] == "pyyaml" for f in r["findings"]), "fixed versions not flagged")
check(r["engine"] == "vyomi-advisory" and r["endOfLife"][0]["product"] == "python", "engine + python 3.8 EOL")
check(vs.scan_image({"config": {"Labels": {"vyomi.sbom": json.dumps([{"name": "log4j-core", "version": "2.14.1", "eco": "maven"}])}}}, "app", "1")["findings"][0]["vulnerabilityId"] == "CVE-2021-44228", "sbom label -> Log4Shell")
check(vs.scan_image({}, "alpine", "3.17", today=datetime.date(2026, 11, 4))["endOfLife"][0]["cycle"] == "3.17", "alpine 3.17 EOL from the tag alone")
tr = vs.parse_trivy_report({"Metadata": {"TrivyVersion": "0.58.0"}, "Results": [{"Type": "alpine", "Vulnerabilities": [{"VulnerabilityID": "CVE-1", "PkgName": "x", "InstalledVersion": "1", "FixedVersion": "2", "Severity": "HIGH", "CVSS": {"nvd": {"V3Score": 7.5}}, "Title": "t"}]}]})
check(vs.scan_image(cfg, "a", "b", trivy_report=tr)["engine"] == "trivy", "trivy report takes over")

# ── classifier ──────────────────────────────────────────────────────────────
pol = json.dumps({"Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/*"}]})
e = sc.classify("aws", "PUT", "/b", {"policy": ""}, {}, pol, 204, svc="s3")
check(e and "storage-public" in e["tags"] and e["resource"] == "arn:aws:s3:::b", "public bucket policy")
check(sc.classify("aws", "PUT", "/b", {"policy": ""}, {}, json.dumps({"Statement": [{"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::1:root"}}]}), 204, svc="s3") is None, "private policy ignored")
e = sc.classify("aws", "POST", "/", {}, {"x-amz-target": "com.amazonaws.cloudtrail.v20131101.CloudTrail_20131101.StopLogging"}, '{"Name":"t1"}', 200, svc="cloudtrail")
check(e and "audit-log-disabled" in e["tags"], "StopLogging")
e = sc.classify("aws", "POST", "/", {}, {}, "Action=AuthorizeSecurityGroupIngress&GroupId=sg-1&CidrIp=0.0.0.0/0&FromPort=22", 200, svc="vpc")
check(e and "network-exposed" in e["tags"], "SG world SSH")
e = sc.classify("azure", "PUT", "/subscriptions/s/resourceGroups/r/providers/Microsoft.Storage/storageAccounts/sa", {}, {}, json.dumps({"properties": {"allowBlobPublicAccess": True}}), 200)
check(e and "storage-public" in e["tags"], "azure storage public")
e = sc.classify("azure", "PUT", "/subscriptions/s/resourceGroups/r/providers/Microsoft.Authorization/roleAssignments/x", {}, {}, json.dumps({"properties": {"roleDefinitionId": "/x/8e3af657-a8ff-443c-a75c-2fe8c4bcb635"}}), 201)
check(e and "priv-escalation" in e["tags"], "azure owner assignment")
e = sc.classify("gcp", "POST", "/storage/v1/b/bk/iam:setIamPolicy", {}, {}, json.dumps({"bindings": [{"role": "roles/storage.objectViewer", "members": ["allUsers"]}]}), 200)
check(e and "storage-public" in e["tags"], "gcp allUsers")
check(sc.classify("aws", "GET", "/", {}, {}, "", 200, svc="s3") is None, "plain read is not an event")

# ── deterministic detector ──────────────────────────────────────────────────
def ev(sec, tag, actor="alice", cloud="aws", svc="iam", res="r", status=200, det=""):
    ts = (datetime.datetime(2026, 11, 4, 10, 0, 0, tzinfo=datetime.timezone.utc) + datetime.timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    return sc.new_event(cloud, actor, svc, "A", res, status, [tag], det, ts=ts)

feed = [ev(i, "auth-failure", status=403) for i in range(5)] + [ev(10, "audit-log-disabled", actor="console", res="t1", svc="cloudtrail", det="x")]
feed += [ev(20 + i, "recon-read", actor="bob", svc=s) for i, s in enumerate(["s3", "iam", "kms"] * 5)]
feed += [ev(30, "credential-created", actor="mallory", res="u1"), ev(40, "credential-created", actor="mallory", res="u2")]
th = sc.detect("aws", feed)
rules = {t["rule"] for t in th}
check({"auth-failure-burst", "audit-log-disabled", "recon-burst", "credential-persistence"} <= rules, f"all rules fire: {rules}")
check(sc.detect("aws", feed) == th, "detector is deterministic")
check(not sc.detect("aws", feed[:4]), "4 failures is below the burst threshold")
check(sc.detect("azure", feed) == [], "events are per cloud")
check(any(t["type"] == "Stealth:IAMUser/CloudTrailLoggingDisabled" for t in th), "GuardDuty type name")

# ── Security Hub posture + wire ─────────────────────────────────────────────
s3 = SimpleNamespace(buckets={"pub": {"cfg": {"policy": pol}}, "priv": {"cfg": {"encryption": "<x/>", "publicAccessBlock": "<BlockPublicPolicy>true</BlockPublicPolicy>"}}})
vpc = {"sgs": {"sg-1": {"id": "sg-1", "name": "web", "vpc_id": "v", "ingress": [{"protocol": "tcp", "from_port": 22, "to_port": 22, "cidrs": ["0.0.0.0/0"]}]}},
       "instances": {"i-1": {"id": "i-1", "state": "running", "public_ip": "3.3.3.3", "sg_ids": ["sg-1"]}}}
inv = sc.aws_collect(s3=s3, vpc_model=vpc)
rows = sc.aws_posture_findings(inv)
ctl = {(r["control"], r["rid"].rsplit("/", 1)[-1]) for r in rows}
check(("S3.2", "arn:aws:s3:::pub") in ctl and ("EC2.13", "sg-1") in ctl and ("EC2.9", "i-1") in ctl and ("CloudTrail.1", "AWS::::Account:123456789012") in ctl, f"posture controls {ctl}")
check(not any(r["rid"].endswith(":priv") and r["control"] in ("S3.2", "S3.4", "S3.8") for r in rows), "hardened bucket has no S3 findings")
check(any(r["product"] == "inspector" and r["control"] == "NETWORK_REACHABILITY" for r in rows), "inspector network reachability")
bag = {}
r = sc.hub_dispatch(bag, "POST", "/findings", b"{}", rows, th)
check(r.status == 401 and json.loads(r.body)["Code"] == "InvalidAccessException", "GetFindings before EnableSecurityHub")
check(sc.hub_dispatch(bag, "POST", "/accounts", b"{}", rows, th).status == 200, "enable")
check(sc.hub_dispatch(bag, "POST", "/accounts", b"{}", rows, th).status == 409, "enable twice")
f = json.loads(sc.hub_dispatch(bag, "POST", "/findings", json.dumps({"Filters": {"SeverityLabel": [{"Value": "CRITICAL", "Comparison": "EQUALS"}]}}).encode(), rows, th).body)["Findings"]
check(f and all(x["Severity"]["Label"] == "CRITICAL" for x in f) and f[0]["SchemaVersion"] == "2018-10-08", "filtered ASFF")
fid = f[0]["Id"]
u = json.loads(sc.hub_dispatch(bag, "PATCH", "/findings/batchupdate", json.dumps({"FindingIdentifiers": [{"Id": fid, "ProductArn": f[0]["ProductArn"]}], "Workflow": {"Status": "SUPPRESSED"}}).encode(), rows, th).body)
check(len(u["ProcessedFindings"]) == 1, "batch update")
f2 = json.loads(sc.hub_dispatch(bag, "POST", "/findings", json.dumps({"Filters": {"WorkflowStatus": [{"Value": "SUPPRESSED", "Comparison": "EQUALS"}]}}).encode(), rows, th).body)["Findings"]
check([x["Id"] for x in f2] == [fid], "workflow persisted")
n_before = len(json.loads(sc.hub_dispatch(bag, "POST", "/findings", b"{}", rows, th).body)["Findings"])
# GuardDuty
check(sc.gd_dispatch(bag, "GET", "/detector", b"", th).status == 200, "list detectors")
did = json.loads(sc.gd_dispatch(bag, "POST", "/detector", b'{"Enable":true}', th).body)["DetectorId"]
check(sc.gd_dispatch(bag, "POST", "/detector", b'{"Enable":true}', th).status == 400, "second detector rejected")
ids = json.loads(sc.gd_dispatch(bag, "POST", f"/detector/{did}/findings", b"{}", th).body)["FindingIds"]
check(len(ids) == len(th), "GuardDuty lists the detector's findings")
got = json.loads(sc.gd_dispatch(bag, "POST", f"/detector/{did}/findings/get", json.dumps({"FindingIds": ids[:1]}).encode(), th).body)["Findings"][0]
check(got["SchemaVersion"] == "2.0" and got["Service"]["ServiceName"] == "guardduty" and "vyomi-rules" in got["Service"]["AdditionalInfo"]["Value"], "GuardDuty finding shape + provenance")
sc.gd_dispatch(bag, "POST", f"/detector/{did}/findings/archive", json.dumps({"FindingIds": ids[:1]}).encode(), th)
act = json.loads(sc.gd_dispatch(bag, "POST", f"/detector/{did}/findings", json.dumps({"FindingCriteria": {"Criterion": {"service.archived": {"Eq": ["false"]}}}}).encode(), th).body)["FindingIds"]
check(len(act) == len(ids) - 1, "archive filter")
check(sc.gd_dispatch(bag, "POST", f"/detector/{did}/findings/create", b'{"FindingTypes":["Bogus"]}', th).status == 400, "bad sample type")
n_after = len(json.loads(sc.hub_dispatch(bag, "POST", "/findings", b"{}", rows, th).body)["Findings"])
check(n_after == n_before + len(th), "Security Hub ingests GuardDuty findings once a detector exists")
# Azure/GCP shapes
a = sc.azure_alert_view(th[0], "sub1")
check(a["type"] == "Microsoft.Security/Locations/alerts" and a["properties"]["vendorName"] == "Vyomi" and a["id"].startswith("/subscriptions/sub1/"), "azure alert shape")
print(f"OK {ok} checks")
