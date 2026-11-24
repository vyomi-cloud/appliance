from google.cloud import trace_v1

import gcp

trace_id = open("trace_id.txt").read().strip()
client = gcp.rest(trace_v1.TraceServiceClient)
trace = client.get_trace(request={"project_id": gcp.PROJECT, "trace_id": trace_id})
names = sorted(s.name for s in trace.spans)
print("spans:", names)
assert "agent:facilities" in names and "agent:maintenance" in names
listed = {t.trace_id for t in client.list_traces(request={"project_id": gcp.PROJECT})}
print("trace listed by list_traces:", trace_id in listed)
assert trace_id in listed
