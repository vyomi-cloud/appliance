import time

import gcp

trace_id = open("trace_id.txt").read().strip()
client = gcp.logging_client()
logger = client.logger("facilities-agent")
logger.log_struct({"event": "agent_run", "agent": "facilities-supervisor", "trace": f"projects/{gcp.PROJECT}/traces/{trace_id}",
                   "route": ["facilities", "maintenance", "analytics"]}, severity="INFO")
mine = []
for _ in range(20):
    entries = list(client.list_entries(filter_=f'logName="projects/{gcp.PROJECT}/logs/facilities-agent"'))
    mine = [e for e in entries if isinstance(e.payload, dict) and e.payload.get("event") == "agent_run"]
    if mine:
        break
    time.sleep(0.5)
assert mine, "log entry not found"
print("log entry read back; trace field ends with the trace id:", (mine[0].trace or "").endswith(trace_id))
