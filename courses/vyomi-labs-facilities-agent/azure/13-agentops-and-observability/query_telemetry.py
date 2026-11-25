import json
import time
from datetime import timedelta
from azure.monitor.query import LogsQueryClient
from azlab import DevToken, ENDPOINT

obs, tr = json.load(open("obs.json")), json.load(open("trace.json"))
client = LogsQueryClient(DevToken(), endpoint=ENDPOINT + "/azure-data/loganalytics")


def q(text):
    r = client.query_workspace(obs["workspace_id"], text, timespan=timedelta(hours=2))
    return r.tables[0].rows if r.tables else []


rows = []
for _ in range(20):
    rows = q(f"AppDependencies | where OperationId == '{tr['trace_id']}' | project Name | order by Name asc")
    if rows:
        break
    time.sleep(1)
names = sorted({r[0] for r in rows})
print("spans read back:", names)
print("log lines:", len(q(f"AppTraces | where Message has '{tr['tag']}' | project Message")))
total = q("AppMetrics | where Name == 'facilities.tool_calls' | summarize total=sum(Sum)")[0][0]
print("facilities.tool_calls total:", total)
