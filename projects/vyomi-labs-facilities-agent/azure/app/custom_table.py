import json
import uuid
from datetime import timedelta
import requests
from azure.monitor.query import LogsQueryClient
from azlab import DevToken, ENDPOINT, rid

obs = json.load(open("obs.json"))
run_id = uuid.uuid4().hex
rows = [{"run": run_id, "tool": t, "via": "function"} for t in ("kb_search", "asset_status", "asset_status", "work_order_stats")]
r = requests.post(f"{ENDPOINT}{rid('Microsoft.OperationalInsights', 'workspaces', 'facilities-law')}/api/logs", headers={"Log-Type": "AgentRun"}, json=rows, timeout=20)
print("ingest HTTP", r.status_code)
client = LogsQueryClient(DevToken(), endpoint=ENDPOINT + "/azure-data/loganalytics")
res = client.query_workspace(obs["workspace_id"], f"AgentRun_CL | where run_s == '{run_id}' | summarize n=count() by tool_s | order by tool_s asc", timespan=timedelta(hours=2))
print("calls per tool:", {r[0]: r[1] for r in res.tables[0].rows})
