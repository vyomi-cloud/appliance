"""boto3 (official SDK, endpoint changed only) against Kinesis stream consumers /
encryption / enhanced monitoring and SSM maintenance windows / patch baselines,
engine operations that no SDK test called."""
import os
import sys
import uuid

import boto3

EP = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
KW = dict(endpoint_url=EP, region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
failed = False
sfx = uuid.uuid4().hex[:8]


def check(name, fn):
    global failed
    try:
        ok = fn()
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {str(e)[:200]}")
        ok = False
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def main():
    kin, ssm = boto3.client("kinesis", **KW), boto3.client("ssm", **KW)
    name = f"conf3-{sfx}"
    kin.create_stream(StreamName=name, ShardCount=1)
    arn = kin.describe_stream(StreamName=name)["StreamDescription"]["StreamARN"]
    cons = kin.register_stream_consumer(StreamARN=arn, ConsumerName=f"c-{sfx}")["Consumer"]
    check("kinesis ListStreamConsumers lists the consumer",
          lambda: f"c-{sfx}" in [c["ConsumerName"] for c in kin.list_stream_consumers(StreamARN=arn)["Consumers"]])
    check("kinesis DescribeStreamConsumer returns it",
          lambda: kin.describe_stream_consumer(StreamARN=arn, ConsumerName=f"c-{sfx}")
          ["ConsumerDescription"]["ConsumerARN"] == cons["ConsumerARN"])
    kin.start_stream_encryption(StreamName=name, EncryptionType="KMS", KeyId="alias/aws/kinesis")
    check("kinesis StartStreamEncryption sets KMS",
          lambda: kin.describe_stream(StreamName=name)["StreamDescription"].get("EncryptionType") == "KMS")
    kin.stop_stream_encryption(StreamName=name, EncryptionType="KMS", KeyId="alias/aws/kinesis")
    check("kinesis StopStreamEncryption clears it",
          lambda: kin.describe_stream(StreamName=name)["StreamDescription"].get("EncryptionType", "NONE") == "NONE")
    kin.enable_enhanced_monitoring(StreamName=name, ShardLevelMetrics=["IncomingBytes"])
    check("kinesis EnableEnhancedMonitoring is reflected", lambda: "IncomingBytes" in str(
        kin.describe_stream(StreamName=name)["StreamDescription"].get("EnhancedMonitoring")))
    kin.disable_enhanced_monitoring(StreamName=name, ShardLevelMetrics=["IncomingBytes"])
    check("kinesis DisableEnhancedMonitoring is reflected", lambda: "IncomingBytes" not in str(
        kin.describe_stream(StreamName=name)["StreamDescription"].get("EnhancedMonitoring")))

    # SSM
    win = ssm.create_maintenance_window(Name=f"w-{sfx}", Schedule="rate(7 days)", Duration=2, Cutoff=1,
                                        AllowUnassociatedTargets=True)["WindowId"]
    check("ssm GetMaintenanceWindow returns it", lambda: ssm.get_maintenance_window(WindowId=win)["Name"] == f"w-{sfx}")
    check("ssm DescribeMaintenanceWindows lists it", lambda: win in [
        w["WindowId"] for w in ssm.describe_maintenance_windows()["WindowIdentities"]])
    ssm.delete_maintenance_window(WindowId=win)
    check("ssm DeleteMaintenanceWindow removes it", lambda: win not in [
        w["WindowId"] for w in ssm.describe_maintenance_windows()["WindowIdentities"]])
    bl = ssm.create_patch_baseline(Name=f"b-{sfx}", OperatingSystem="AMAZON_LINUX_2")["BaselineId"]
    check("ssm GetPatchBaseline returns it", lambda: ssm.get_patch_baseline(BaselineId=bl)["Name"] == f"b-{sfx}")
    check("ssm DescribePatchBaselines lists it", lambda: bl in [
        b["BaselineId"] for b in ssm.describe_patch_baselines()["BaselineIdentities"]])
    ssm.delete_patch_baseline(BaselineId=bl)
    check("ssm DeletePatchBaseline removes it", lambda: bl not in [
        b["BaselineId"] for b in ssm.describe_patch_baselines()["BaselineIdentities"]])
    kin.delete_stream(StreamName=name, EnforceConsumerDeletion=True)
    sys.exit(1 if failed else 0)


main()
