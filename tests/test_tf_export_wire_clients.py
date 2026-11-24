"""boto3-shaped clients over an in-process transport (what Nano uses): same Terraform as boto3, no sockets."""
import pytest

pytest.importorskip("botocore")
from core.tf_export.wire_clients import WireClient, ClientError  # noqa: E402


def _models():
    import os
    import botocore
    return os.path.join(os.path.dirname(botocore.__file__), "data")


def test_query_protocol_roundtrip_and_error_mapping():
    seen = {}

    def transport(method, path, query, headers, body):
        seen.update(method=method, path=path, body=body.decode(), auth=headers["Authorization"])
        xml = (b'<DescribeVpcsResponse xmlns="http://ec2.amazonaws.com/doc/2016-11-15/"><vpcSet><item><vpcId>vpc-1</vpcId>'
               b'<cidrBlock>10.0.0.0/16</cidrBlock><tagSet><item><key>Name</key><value>main</value></item></tagSet></item></vpcSet></DescribeVpcsResponse>')
        return 200, {"content-type": "text/xml"}, xml

    ec2 = WireClient("ec2", transport, "us-east-1", _models())
    vpcs = ec2.describe_vpcs()["Vpcs"]
    assert vpcs[0]["VpcId"] == "vpc-1" and vpcs[0]["Tags"] == [{"Key": "Name", "Value": "main"}]
    assert "Action=DescribeVpcs" in seen["body"] and "/ec2/" in seen["auth"]

    def boom(*a):
        return 400, {}, b'<Response><Errors><Error><Code>InvalidVpcID.NotFound</Code><Message>x</Message></Error></Errors></Response>'
    with pytest.raises(ClientError):
        WireClient("ec2", boom, "us-east-1", _models()).describe_vpcs()
