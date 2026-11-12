"""EC2 Instance Connect over the router: a real boto3 `ec2-instance-connect` client pushes a (really generated) OpenSSH key
to an instance that lives in the shared EC2 model; validity window + validation errors are checked against that state."""
import base64
import os
import struct
import sys

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(__file__))
from _wire_boto import make_clients  # noqa: E402
from core import ec2_instance_connect_core as eic  # noqa: E402


def _pubkey(kind="ssh-ed25519", body=b"\x01" * 32):
    blob = struct.pack(">I", len(kind)) + kind.encode() + struct.pack(">I", len(body)) + body
    return f"{kind} {base64.b64encode(blob).decode()} user@host" + " " * 0


def _setup():
    router, client = make_clients()
    ec2 = client("ec2")
    ami = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
    iid = ec2.run_instances(ImageId=ami, MinCount=1, MaxCount=1, InstanceType="t3.micro")["Instances"][0]["InstanceId"]
    return router, ec2, client("ec2-instance-connect"), iid


def test_send_ssh_public_key_records_key_with_60s_window():
    router, ec2, ic, iid = _setup()
    az = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]["Placement"]["AvailabilityZone"]
    key = _pubkey(body=b"\x02" * 64)
    assert len(key) >= 80
    r = ic.send_ssh_public_key(InstanceId=iid, InstanceOSUser="ec2-user", SSHPublicKey=key, AvailabilityZone=az)
    assert r["Success"] is True and r["RequestId"]
    got = eic.keys_for(router.vpc, iid, "ec2-user")
    assert len(got) == 1 and got[0]["key"] == key.rsplit(" ", 1)[0].strip() and 55 < got[0]["expires"] - got[0]["pushed"] <= 60
    assert eic.keys_for(router.vpc, iid, "root") == []
    assert eic.keys_for(router.vpc, iid, "ec2-user", now=got[0]["expires"] + 1) == []   # expired after 60s


def test_validation_and_state_errors():
    router, ec2, ic, iid = _setup()
    key = _pubkey(body=b"\x02" * 64)

    def code(**kw):
        with pytest.raises(ClientError) as e:
            ic.send_ssh_public_key(**{"InstanceId": iid, "InstanceOSUser": "ec2-user", "SSHPublicKey": key, **kw})
        return e.value.response["Error"]["Code"]
    assert code(InstanceId="i-0123456789abcdef0") == "EC2InstanceNotFoundException"
    assert code(AvailabilityZone="us-west-2z") == "InvalidArgsException"
    assert code(SSHPublicKey="ssh-rsa " + "A" * 100) == "InvalidArgsException"      # not a real key blob
    assert code(InstanceOSUser="bad user!") == "InvalidArgsException"
    ec2.stop_instances(InstanceIds=[iid])
    assert code() == "EC2InstanceStateInvalidException"


def test_serial_console_needs_account_switch():
    router, ec2, ic, iid = _setup()
    key = _pubkey(body=b"\x03" * 64)
    ec2.disable_serial_console_access()
    with pytest.raises(ClientError) as e:
        ic.send_serial_console_ssh_public_key(InstanceId=iid, SSHPublicKey=key)
    assert e.value.response["Error"]["Code"] == "SerialConsoleAccessDisabledException"
    ec2.enable_serial_console_access()
    assert ic.send_serial_console_ssh_public_key(InstanceId=iid, SSHPublicKey=key, SerialPort=0)["Success"] is True
    assert eic.keys_for(router.vpc, iid, "serial-console")
