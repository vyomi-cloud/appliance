"""EC2 GetCapacityManagerSupportabilityScores (new upstream operation, issue #161)."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def call(**kw):
    auth = "AWS4-HMAC-SHA256 Credential=AKIATEST/20261029/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=00"
    return requests.post(f"{BASE}/", headers={"Authorization": auth}, data={"Action": "GetCapacityManagerSupportabilityScores", "Version": "2016-11-15", **kw}, timeout=30)


def main():
    ok = dict(CapacityAmount="10", CapacityUnit="vcpu", MarketType="on-demand")
    ok["CapacityAvailabilityZoneId.1"] = "use1-az1"
    r = call(**ok)
    check("valid request returns 200", r.status_code == 200)
    check("response has aggregateScore and score set", "GetCapacityManagerSupportabilityScoresResponse" in r.text and "aggregateScore" in r.text and "capacityManagerSupportabilityScoreSet" in r.text)
    for missing in ("CapacityAmount", "CapacityUnit", "MarketType", "CapacityAvailabilityZoneId.1"):
        p = {k: v for k, v in ok.items() if k != missing}
        r = call(**p)
        check(f"missing {missing} -> MissingParameter", r.status_code == 400 and "MissingParameter" in r.text)
    sys.exit(1 if failed else 0)


main()
