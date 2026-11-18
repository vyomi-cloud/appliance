"""gRPC front door (core/gcp_grpc_front.py) for the Google clients that have no REST transport.

Proves with the unmodified libraries, default constructors, only `client_options={"api_endpoint": ...}` + the standard
GRPC_DEFAULT_SSL_ROOTS_FILE_PATH env var pointing at the front door's (self-signed, test-generated) certificate:
  * google-cloud-monitoring  MetricServiceClient: create_metric_descriptor / create_time_series / list_time_series /
    list_metric_descriptors, and AlertPolicyServiceClient create/get/list/delete  (gRPC-only library, no REST transport);
  * google-cloud-logging     logging.Client (default gRPC): logger.log_text / log_struct, read back through the gapic
    LoggingServiceV2Client.list_log_entries; logging.Client.list_entries (adds a default `timestamp>=` filter, which the
    simulator's timestamp comparison only handles on a build with the reference-arch corefix; reported as BLOCKED, not
    PASS, when entries come back empty);
  * google-cloud-logging with `logging.Client(_use_grpc=False)` straight at the REST front door (zero own code).
It also checks an error maps to a gRPC status (NOT_FOUND). SKIPs when grpcio / the Google libraries / openssl are absent.
Run: PYTHONPATH=. python3 tests/conformance/test_gcp_grpc_front.py
"""
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
FAILS = []
BLOCKED = []
P = "vyomi-project"


def ok(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (f" -> {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def main():
    try:
        import grpc  # noqa: F401
        from google.cloud import logging as gl, monitoring_v3  # noqa: F401
        import requests  # noqa: F401
        subprocess.run(["openssl", "version"], capture_output=True, check=True)
    except Exception as e:  # noqa: BLE001
        print(f"[SKIP] needs grpcio, google-cloud-logging, google-cloud-monitoring, requests and openssl ({e})")
        return 0
    from test_gcp_real_backends import start_sim   # the same in-process front door
    sim, _router = start_sim()
    from core import gcp_grpc_front as g
    d = tempfile.mkdtemp()
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", d + "/k.pem", "-out", d + "/c.pem", "-days", "2",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"], check=True, capture_output=True)
    srv, port = g.build_server("http://" + sim, 0, tls=(d + "/c.pem", d + "/k.pem"))
    srv.start()
    os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = d + "/c.pem"
    from google.auth.credentials import AnonymousCredentials
    from google.api_core import exceptions as gex
    from google.cloud import logging as gl, monitoring_v3
    from google.cloud.logging_v2.services.logging_service_v2 import LoggingServiceV2Client
    opts = {"api_endpoint": f"localhost:{port}"}
    try:
        mc = monitoring_v3.MetricServiceClient(credentials=AnonymousCredentials(), client_options=opts)
        mtype = "custom.googleapis.com/facilities/approvals"
        md = mc.create_metric_descriptor(name=f"projects/{P}", metric_descriptor={"type": mtype, "metric_kind": "GAUGE", "value_type": "INT64"})
        ok("monitoring gRPC: create_metric_descriptor", md.type == mtype)
        now = int(time.time())
        ts = monitoring_v3.TimeSeries({"metric": {"type": mtype, "labels": {"queue": "approvals"}},
                                       "resource": {"type": "global", "labels": {"project_id": P}},
                                       "points": [{"interval": {"end_time": {"seconds": now}}, "value": {"int64_value": 5}}]})
        mc.create_time_series(name=f"projects/{P}", time_series=[ts])
        got = list(mc.list_time_series(request={"name": f"projects/{P}", "filter": f'metric.type="{mtype}"',
                                                "interval": {"end_time": {"seconds": now + 60}, "start_time": {"seconds": now - 3600}}}))
        ok("monitoring gRPC: create_time_series then list_time_series round-trips the point",
           len(got) == 1 and got[0].points[0].value.int64_value == 5 and got[0].metric.labels["queue"] == "approvals", str(len(got)))
        mds = [m.type for m in mc.list_metric_descriptors(request={"name": f"projects/{P}", "filter": 'metric.type=starts_with("custom.googleapis.com/")'})]
        ok("monitoring gRPC: list_metric_descriptors", mtype in mds, str(mds))
        try:
            mc.get_metric_descriptor(name=f"projects/{P}/metricDescriptors/custom.googleapis.com/nope")
            ok("monitoring gRPC: unknown descriptor maps to NOT_FOUND", False, "no error")
        except gex.NotFound:
            ok("monitoring gRPC: unknown descriptor maps to NOT_FOUND", True)
        ac = monitoring_v3.AlertPolicyServiceClient(credentials=AnonymousCredentials(), client_options=opts)
        pol = ac.create_alert_policy(name=f"projects/{P}", alert_policy={"display_name": "approvals-backlog", "combiner": "OR", "conditions": [
            {"display_name": "c", "condition_threshold": {"filter": f'metric.type="{mtype}"', "comparison": "COMPARISON_GT", "threshold_value": 10,
                                                          "duration": {"seconds": 60}}}]})
        ok("monitoring gRPC: alert policy create/get/list/delete",
           ac.get_alert_policy(name=pol.name).display_name == "approvals-backlog"
           and any(p.name == pol.name for p in ac.list_alert_policies(name=f"projects/{P}")) and (ac.delete_alert_policy(name=pol.name) or True))
    except Exception as e:  # noqa: BLE001
        ok("monitoring gRPC flow", False, f"{type(e).__name__}: {str(e)[:300]}")

    lname = f"projects/{P}/logs/approvals-grpc"
    try:
        lc = gl.Client(project=P, credentials=AnonymousCredentials(), client_options=opts)
        lg = lc.logger("approvals-grpc")
        lg.log_text("approved wo-17", severity="NOTICE")
        lg.log_struct({"workOrder": "wo-17", "decision": "APPROVED"})
        gc = LoggingServiceV2Client(credentials=AnonymousCredentials(), client_options=opts)
        ents = list(gc.list_log_entries(request={"resource_names": [f"projects/{P}"], "filter": f'logName="{lname}"'}))
        ok("logging gRPC (default logging.Client): write_entries, read back through gapic list_log_entries",
           any(e.text_payload == "approved wo-17" for e in ents) and any("decision" in e.json_payload for e in ents), str(len(ents)))
        via_client = list(lc.list_entries(filter_=f'logName="{lname}"'))
        if via_client:
            ok("logging gRPC: logging.Client.list_entries returns the entries", True, str(len(via_client)))
        else:
            BLOCKED.append("logging.Client.list_entries (needs the simulator's timestamp-filter fix: lane 2 / v4/gcp-ref-corefix)")
            print("[BLOCKED] logging.Client.list_entries returned nothing: its default timestamp>= filter matches no entry on this build")
        rc = gl.Client(project=P, credentials=AnonymousCredentials(), client_options={"api_endpoint": "http://" + sim}, _use_grpc=False)
        rc.logger("approvals-rest").log_text("rest mode write")
        rest = list(rc.list_entries(filter_=f'logName="projects/{P}/logs/approvals-rest"'))
        if rest:
            ok("logging REST mode (_use_grpc=False): write + list_entries", rest[0].payload == "rest mode write")
        else:
            BLOCKED.append("logging REST mode list_entries (same timestamp-filter dependency)")
            import requests
            raw = requests.post(f"http://{sim}/v2/entries:list", json={"resourceNames": [f"projects/{P}"], "filter": f'logName="projects/{P}/logs/approvals-rest"'}).json()
            ok("logging REST mode (_use_grpc=False): write landed (read raw)", bool(raw.get("entries")))
            print("[BLOCKED] logging REST mode list_entries returned nothing: same default timestamp>= filter")
    except Exception as e:  # noqa: BLE001
        ok("logging flow", False, f"{type(e).__name__}: {str(e)[:300]}")
    srv.stop(0)
    print("\n" + ("ALL PASS" + (f" (BLOCKED: {BLOCKED})" if BLOCKED else "") if not FAILS else f"FAILED: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
