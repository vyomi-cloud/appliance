"""Test harness plumbing: step recorder and PASS/BLOCKED/FAIL status model (cloud-neutral), plus the AWS client factory.
The status model, Blocked, Ctx.step and Ctx.verdict are shared by every cloud (the GCP context in facilities/gcp/runtime.py subclasses Ctx);
boto3 is imported lazily so a GCP-only environment does not need it."""
import json, os, time, traceback

PASS, BLOCKED, FAIL = "PASS", "BLOCKED", "FAIL"
ACCOUNT = "123456789012"

# resource names fixed by the cross-lane reference contract
NAMES = dict(pool="facilities-users", kb="facilities-kb", gateway="facilities-gateway", memory="facilities-memory",
             sm="work-order-approval", ledger="approval-ledger", topic="approver-inbox", guardrail="facilities-guardrail",
             runtime="facilities-supervisor", bucket="facilities-docs", assets="facilities-assets", work_orders="facilities-work-orders",
             inbox_queue="approver-inbox-queue", role=f"arn:aws:iam::{ACCOUNT}:role/facilities-role")

COMPONENTS = {1: "Access and perimeter security (Cognito, API Gateway, WAF)", 2: "Channels and input guardrails, approver inbox",
              3: "AgentCore Runtime: supervisor + 3 sub-agents", 4: "AgentCore Gateway (tool catalog)", 5: "Actions and approval (Step Functions)",
              6: "Knowledge search (Bedrock KB RAG)", 7: "Tools (Lambda)", 8: "AgentOps and observability", 9: "AgentCore Memory",
              10: "Foundation models (Bedrock)", 11: "Response generation (grounded, cited, guarded)", 12: "Knowledge processing pipeline",
              13: "Governance and security (KMS, CloudTrail)"}
RUN_ORDER = [1, 2, 12, 6, 7, 4, 3, 9, 5, 10, 11, 8, 13]


class Blocked(Exception):
    """Raise to report a step as blocked by a missing capability (the message names the lane)."""
    def __init__(self, lane, why):
        super().__init__(why); self.lane = lane; self.why = why


def unsupported(e):
    """True when the simulator does not implement the API at all (as opposed to the app being wrong)."""
    from botocore.exceptions import ClientError
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "")
        msg = str(e)
        return (code in ("UnknownOperationException", "UnsupportedOperation", "UnrecognizedClientException", "NotImplemented", "ModelNotReadyException")
                or "Missing bucket" in msg or "not implemented" in msg.lower() or "is not simulated" in msg or "Unsupported AgentCore operation" in msg
                or "does not run AgentCore runtime containers" in msg or "Local LLM endpoint" in msg)
    return False


class Ctx:
    COMPONENTS = COMPONENTS      # per-cloud subclasses replace the component titles

    def __init__(self, endpoint, region="us-east-1", out=print):
        self.endpoint, self.region, self.out = endpoint, region, out
        self._c = {}
        self.state = {}          # ids passed between components (pool id, kb id, ...)
        self.subs = []           # recorded sub-steps
        self.current = None
        self.calls = []

    def client(self, svc):
        if svc not in self._c:
            import boto3
            from botocore.config import Config
            self._c[svc] = boto3.client(svc, region_name=self.region, endpoint_url=self.endpoint,
                                        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
                                        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
                                        config=Config(retries={"max_attempts": 1}, connect_timeout=5, read_timeout=int(__import__("os").environ.get("FACILITIES_READ_TIMEOUT", "60"))))
        return self._c[svc]

    def blocked_lane(self, e, lane):
        """The lane that owes the missing capability when the step failed because the simulator lacks the API, else None."""
        return lane if lane and unsupported(e) else None

    def step(self, name, fn, lane=None):
        """Run one SDK-level step. Returns its value, or None when blocked/failed (recorded, never raised)."""
        t0 = time.time()
        status, detail, val = PASS, "", None
        try:
            val = fn()
            detail = val if isinstance(val, str) else ""
        except Blocked as b:
            status, detail = BLOCKED, f"waiting for {b.lane}: {b.why}"
        except Exception as e:
            bl = self.blocked_lane(e, lane)
            if bl:
                status, detail = BLOCKED, f"waiting for {bl}: {type(e).__name__}: {str(e)[:140]}"
            else:
                status, detail = FAIL, f"{type(e).__name__}: {str(e)[:int(os.environ.get('FACILITIES_DETAIL', '220'))]}"
                if os.environ.get("E2E_TRACE"):
                    traceback.print_exc()
        rec = dict(component=self.current, name=name, status=status, detail=detail, secs=round(time.time() - t0, 2))
        self.subs.append(rec)
        self.out(f"    [{status:7}] {name}" + (f"  - {detail}" if detail else ""))
        return val if status == PASS else None

    def verdict(self, comp):
        s = [x["status"] for x in self.subs if x["component"] == comp]
        return FAIL if FAIL in s else BLOCKED if BLOCKED in s else PASS if s else BLOCKED


def aws_json(item):
    """Flatten a DynamoDB attribute map."""
    return {k: list(v.values())[0] for k, v in item.items()}
