import boto3

ev = boto3.client("bedrock-agentcore-control").list_evaluators()
print("evaluators available:", len(ev["evaluators"]))
assert ev["evaluators"], "the account must offer at least one evaluator"
