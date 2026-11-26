import time

from google.cloud import monitoring_v3

import gcp

TYPE = "custom.googleapis.com/facilities/tool_calls"
P = f"projects/{gcp.PROJECT}"
n = int(open("tool_count.txt").read())
client = monitoring_v3.MetricServiceClient(credentials=gcp.AnonymousCredentials(), client_options=gcp.grpc_options())
client.create_metric_descriptor(request={"name": P, "metric_descriptor": {"type": TYPE, "metric_kind": "GAUGE", "value_type": "INT64", "description": "tool calls per run"}}, timeout=15, retry=None)
series = monitoring_v3.TimeSeries(metric={"type": TYPE, "labels": {"agent": "facilities-supervisor"}}, resource={"type": "global", "labels": {"project_id": gcp.PROJECT}},
                                  points=[monitoring_v3.Point(interval={"end_time": {"seconds": int(time.time())}}, value={"int64_value": n})])
client.create_time_series(request={"name": P, "time_series": [series]}, timeout=15, retry=None)
rows = list(client.list_time_series(request={"name": P, "filter": f'metric.type="{TYPE}"', "interval": {"start_time": {"seconds": int(time.time()) - 600}, "end_time": {"seconds": int(time.time()) + 60}},
                                             "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL}, timeout=15, retry=None))
print("metric read back:", rows[0].points[0].value.int64_value, "tool calls")
assert rows[0].points[0].value.int64_value == n
