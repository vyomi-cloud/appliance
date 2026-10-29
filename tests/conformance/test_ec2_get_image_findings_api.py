"""EC2 GetImageFindings (new upstream operation, issue #142): known AMI -> empty findings, unknown -> InvalidAMIID.NotFound."""
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
    return requests.post(f"{BASE}/", headers={"Authorization": auth}, data={"Action": "GetImageFindings", "Version": "2016-11-15", **kw}, timeout=30)


def main():
    ami = requests.get(f"{BASE}/api/ec2/amis", timeout=30).json()
    ami = ami.get("amis", ami) if isinstance(ami, dict) else ami
    ami_id = (ami[0].get("ami") or ami[0].get("image_id")) if ami else "ami-amzn2023"
    r = call(ImageId=ami_id)
    check("known AMI returns 200", r.status_code == 200)
    check("response has imageFindingsSet", "GetImageFindingsResponse" in r.text and "imageFindingsSet" in r.text)
    r = call(ImageId="ami-00000000deadbeef0")
    check("unknown AMI -> InvalidAMIID.NotFound", r.status_code == 400 and "InvalidAMIID.NotFound" in r.text)
    r = call()
    check("missing ImageId -> MissingParameter", r.status_code == 400 and "MissingParameter" in r.text)
    sys.exit(1 if failed else 0)


main()
