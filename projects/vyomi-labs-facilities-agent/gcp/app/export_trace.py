import uuid
from datetime import datetime, timezone

from google.cloud import trace_v2
from google.protobuf import timestamp_pb2

import gcp
from agents import ask

result = ask("Boiler B-12 is at 34 psi. What does the SOP say, and please raise a work order for it. How many work orders are open?", "maria")
spans = result["spans"]
P = f"projects/{gcp.PROJECT}"
trace_id = uuid.uuid4().hex


def ts(t):
    x = timestamp_pb2.Timestamp()
    x.FromDatetime(datetime.fromtimestamp(t, timezone.utc))
    return x


root = uuid.uuid4().hex[:16]
out = [trace_v2.Span(name=f"{P}/traces/{trace_id}/spans/{root}", span_id=root, display_name=trace_v2.TruncatableString(value="facilities-supervisor"),
                     start_time=ts(spans[0]["start"]), end_time=ts(spans[-1]["end"]))]
for s in spans:
    sid = uuid.uuid4().hex[:16]
    out.append(trace_v2.Span(name=f"{P}/traces/{trace_id}/spans/{sid}", span_id=sid, parent_span_id=root, display_name=trace_v2.TruncatableString(value=s["name"]),
                             start_time=ts(s["start"]), end_time=ts(s["end"]),
                             attributes=trace_v2.Span.Attributes(attribute_map={"kind": trace_v2.AttributeValue(string_value=trace_v2.TruncatableString(value=s["kind"]))})))
gcp.rest(trace_v2.TraceServiceClient).batch_write_spans(request={"name": P, "spans": out})
open("trace_id.txt", "w").write(trace_id)
open("tool_count.txt", "w").write(str(len(result["tools"])))
print(f"{len(out)} spans exported in trace {trace_id}")
