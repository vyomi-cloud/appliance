"""EC2 CreateCapacityReservationFleet with the new AvailabilityZone/AvailabilityZoneId/InstanceRequirements
parameters, plus Describe/Cancel (upstream change, issue #162)."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def call(action, **kw):
    auth = "AWS4-HMAC-SHA256 Credential=AKIATEST/20261029/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=00"
    return requests.post(f"{BASE}/", headers={"Authorization": auth}, data={"Action": action, "Version": "2016-11-15", **kw}, timeout=30)


def main():
    r = call("CreateCapacityReservationFleet", TotalTargetCapacity="4", AvailabilityZone="us-east-1b",
             AvailabilityZoneId="use1-az2", **{"InstanceRequirements.VCpuCount.Min": "2"})
    check("create with fleet-level AZ + InstanceRequirements returns 200", r.status_code == 200)
    check("response has fleet id, state, reservation set",
          "capacityReservationFleetId" in r.text and "<state>submitted</state>" in r.text and "fleetCapacityReservationSet" in r.text)
    check("fleet AZ is reflected", "us-east-1b" in r.text and "use1-az2" in r.text)
    fid = r.text.split("<capacityReservationFleetId>")[1].split("<")[0] if "<capacityReservationFleetId>" in r.text else ""
    r = call("CreateCapacityReservationFleet", TotalTargetCapacity="2",
             **{"InstanceTypeSpecification.1.InstanceType": "c5.large", "TagSpecification.1.ResourceType": "capacity-reservation-fleet",
                "TagSpecification.1.Tag.1.Key": "env", "TagSpecification.1.Tag.1.Value": "dev"})
    check("create with InstanceTypeSpecification returns 200", r.status_code == 200 and "c5.large" in r.text)
    r = call("CreateCapacityReservationFleet", **{"InstanceTypeSpecification.1.InstanceType": "c5.large"})
    check("missing TotalTargetCapacity -> MissingParameter", r.status_code == 400 and "MissingParameter" in r.text)
    r = call("CreateCapacityReservationFleet", TotalTargetCapacity="2")
    check("no instance types or requirements -> MissingParameter", r.status_code == 400 and "MissingParameter" in r.text)
    r = call("DescribeCapacityReservationFleets", **{"CapacityReservationFleetId.1": fid})
    check("describe returns the created fleet", r.status_code == 200 and fid and fid in r.text and "<state>active</state>" in r.text)
    r = call("CancelCapacityReservationFleets", **{"CapacityReservationFleetId.1": fid})
    check("cancel succeeds", r.status_code == 200 and "cancelled" in r.text and "successfulFleetCancellationSet" in r.text)
    r = call("DescribeCapacityReservationFleets", **{"CapacityReservationFleetId.1": "crf-doesnotexist"})
    check("describe unknown id -> NotFound", r.status_code == 400 and "NotFound" in r.text)
    sys.exit(1 if failed else 0)


main()
