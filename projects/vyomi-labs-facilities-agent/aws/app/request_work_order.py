import boto3

from ask_agent import ask

res = ask("facilities-session-" + "e" * 20)
ap = res["approval"]
print("agent submitted request:", ap["request_id"], ap["status"])

sf, ddb = boto3.client("stepfunctions"), boto3.client("dynamodb")
print("execution status:", sf.describe_execution(executionArn=ap["execution_arn"])["status"])
row = ddb.get_item(TableName="approval-ledger", Key={"request_id": {"S": ap["request_id"]}})["Item"]
print("ledger status:", row["status"]["S"])
mine = [i for i in ddb.scan(TableName="facilities-work-orders")["Items"] if i["requester"]["S"] == "maria.ops@example.com"]
print("work orders written before approval:", len(mine))
