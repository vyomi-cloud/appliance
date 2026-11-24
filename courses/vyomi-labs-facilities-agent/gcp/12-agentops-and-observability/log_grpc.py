import time

from google.cloud import logging as gcl

import gcp

trace_id = open("trace_id.txt").read().strip()
client = gcl.Client(project=gcp.PROJECT, credentials=gcp.AnonymousCredentials(), client_options=gcp.grpc_options())
client.logger("facilities-agent-grpc").log_struct({"event": "agent_run_grpc", "trace": f"projects/{gcp.PROJECT}/traces/{trace_id}"}, severity="INFO")
mine = []
for _ in range(20):
    entries = list(client.list_entries(filter_=f'logName="projects/{gcp.PROJECT}/logs/facilities-agent-grpc"'))
    mine = [e for e in entries if isinstance(e.payload, dict) and e.payload.get("event") == "agent_run_grpc"]
    if mine:
        break
    time.sleep(0.5)
assert mine
print("gRPC log entry written and read back")
