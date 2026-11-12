"""EC2 console gap-sweep (wave 5b) — core/vpc_core.py additions: security group VPC
associations (ec2.security-groups.sharing), Allowed AMIs / Serial Console / default
credit specification account settings (ec2.settings.other).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_ec2_gap_sweep_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import re
import types

try:
    from core import vpc_core as vpc
except ImportError:  # pragma: no cover - Pyodide flat layout
    import vpc_core as vpc  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    s = types.SimpleNamespace()

    def call(p, status=200):
        r = vpc.dispatch(s, p)
        if r.status != status:
            raise AssertionError((p.get("Action"), r.status, r.body))
        return r.body

    def xid(body, tag):
        m = re.search(f"<{tag}>(.*?)</{tag}>", body)
        return m.group(1) if m else None

    # ── security group VPC associations ─────────────────────────────────
    vpc_a = xid(call({"Action": "CreateVpc", "CidrBlock": "10.70.0.0/16"}), "vpcId")
    vpc_b = xid(call({"Action": "CreateVpc", "CidrBlock": "10.71.0.0/16"}), "vpcId")
    sub_b = xid(call({"Action": "CreateSubnet", "VpcId": vpc_b, "CidrBlock": "10.71.1.0/24"}), "subnetId")
    sg_a = xid(call({"Action": "CreateSecurityGroup", "VpcId": vpc_a, "GroupName": "shared-sg", "GroupDescription": "d"}), "groupId")

    _check("launching into a foreign VPC with a foreign SG is rejected",
           "InvalidParameterValue" in call({"Action": "RunInstances", "SubnetId": sub_b,
                                            "SecurityGroupId.1": sg_a, "MinCount": "1", "MaxCount": "1"}, 400))
    call({"Action": "AssociateSecurityGroupVpc", "GroupId": sg_a, "VpcId": vpc_b})
    assoc = call({"Action": "DescribeSecurityGroupVpcAssociations", "GroupId.1": sg_a})
    _check("association listed", f"<groupId>{sg_a}</groupId>" in assoc and f"<vpcId>{vpc_b}</vpcId>" in assoc)
    iid = xid(call({"Action": "RunInstances", "SubnetId": sub_b, "SecurityGroupId.1": sg_a,
                    "MinCount": "1", "MaxCount": "1"}), "instanceId")
    _check("launch succeeds once associated", iid is not None)
    _check("disassociating an in-use SG/VPC pair is rejected",
           "DependencyViolation" in call({"Action": "DisassociateSecurityGroupVpc", "GroupId": sg_a, "VpcId": vpc_b}, 400))
    call({"Action": "TerminateInstances", "InstanceId.1": iid})
    call({"Action": "DisassociateSecurityGroupVpc", "GroupId": sg_a, "VpcId": vpc_b})
    _check("association gone after disassociate",
           f"<vpcId>{vpc_b}</vpcId>" not in call({"Action": "DescribeSecurityGroupVpcAssociations", "GroupId.1": sg_a}))
    _check("re-launch without association is rejected again",
           "InvalidParameterValue" in call({"Action": "RunInstances", "SubnetId": sub_b,
                                            "SecurityGroupId.1": sg_a, "MinCount": "1", "MaxCount": "1"}, 400))

    # ── Allowed AMIs ─────────────────────────────────────────────────────
    default_body = call({"Action": "RunInstances", "MinCount": "1", "MaxCount": "1"})
    _check("unrestricted launch of the seeded (amazon-owned) AMI succeeds by default", "<instanceId>" in default_body)
    call({"Action": "EnableAllowedImagesSettings"})
    _check("enabling with no criteria blocks the default AMI",
           "UnauthorizedImage" in call({"Action": "RunInstances", "MinCount": "1", "MaxCount": "1"}, 400))
    call({"Action": "ReplaceImageCriteriaInAllowedImagesSettings", "ImageCriteria.1.ImageProviders.1": "amazon"})
    settings = call({"Action": "GetAllowedImagesSettings"})
    _check("settings reflect enabled + criteria", "<allowedImagesSettingsState>enabled</allowedImagesSettingsState>" in settings
           and "<item>amazon</item>" in settings)
    _check("launch succeeds once 'amazon' is an allowed provider", "<instanceId>" in call({"Action": "RunInstances", "MinCount": "1", "MaxCount": "1"}))
    call({"Action": "DisableAllowedImagesSettings"})
    _check("disabled settings read back disabled", "<allowedImagesSettingsState>disabled</allowedImagesSettingsState>" in call({"Action": "GetAllowedImagesSettings"}))

    # ── EC2 Serial Console ───────────────────────────────────────────────
    _check("serial console enabled by default", "<serialConsoleAccessEnabled>true</serialConsoleAccessEnabled>" in call({"Action": "GetSerialConsoleAccessStatus"}))
    call({"Action": "DisableSerialConsoleAccess"})
    _check("disable round-trips", "<serialConsoleAccessEnabled>false</serialConsoleAccessEnabled>" in call({"Action": "GetSerialConsoleAccessStatus"}))
    call({"Action": "EnableSerialConsoleAccess"})

    # ── Default credit specification ────────────────────────────────────
    _check("t3 defaults to unlimited", "<cpuCredits>unlimited</cpuCredits>" in call({"Action": "GetDefaultCreditSpecification", "InstanceFamily": "t3"}))
    call({"Action": "ModifyDefaultCreditSpecification", "InstanceFamily": "t3", "CpuCredits": "standard"})
    _check("modified default reads back", "<cpuCredits>standard</cpuCredits>" in call({"Action": "GetDefaultCreditSpecification", "InstanceFamily": "t3"}))
    iid2 = xid(call({"Action": "RunInstances", "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1"}), "instanceId")
    _check("new t3 instance inherits the account default credit spec", s._vpc_model["instances"][iid2]["credit_spec"] == "standard")
    iid3 = xid(call({"Action": "RunInstances", "InstanceType": "t3.micro", "CreditSpecification.CpuCredits": "unlimited",
                     "MinCount": "1", "MaxCount": "1"}), "instanceId")
    _check("explicit CreditSpecification overrides the account default", s._vpc_model["instances"][iid3]["credit_spec"] == "unlimited")

    print("RESULT: PASS — EC2 gap-sweep vpc_core additions conform.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
