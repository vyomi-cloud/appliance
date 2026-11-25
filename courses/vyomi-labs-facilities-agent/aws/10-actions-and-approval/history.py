import boto3

sf = boto3.client("stepfunctions")
sm = next(s for s in sf.list_state_machines()["stateMachines"] if s["name"] == "work-order-approval")["stateMachineArn"]
ex = next(e for e in sf.list_executions(stateMachineArn=sm)["executions"] if e["status"] == "SUCCEEDED")["executionArn"]
events = sf.get_execution_history(executionArn=ex)["events"]
print("history:", ", ".join(e["type"] for e in events[:8]))
