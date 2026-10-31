# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AWS CloudFormation core — substrate-independent stack/change-set/stack-set engine on
the NATIVE AWS CloudFormation wire: the **Query protocol** (form-encoded `Action=...`,
XML responses, http://cloudformation.amazonaws.com/doc/2010-05-15/), so an unmodified
AWS SDK / `aws cloudformation` client works with only the endpoint changed. NO fastapi /
boto3 / socket imports -> loads under Pyodide (Nano) and on the appliance alike.

Templates (JSON or a YAML subset — see `_parse_yaml`) are REALLY provisioned: each
`Resources` entry whose `Type` is in RESOURCE_TYPES is created/updated/deleted through
the proven core for that service (S3/DynamoDB/SNS/SQS/IAM/CloudWatch Logs), sharing the
SAME stores the rest of the AWS wire uses — so a stack's bucket/table/topic/queue/role/
log group is the identical resource the S3/DynamoDB/SNS/SQS/IAM/Logs consoles and SDKs
see. A resource type outside that set fails CreateStack/UpdateStack with the real
rollback semantics (never a silent success) — see the module docstring note in
consoles/src/aws/services/cloudformation/.

Drift detection also compares PROPERTIES, not just existence: each provisioner that
registers a `read` function has its live state snapshotted right after create/update
(`PropertiesBaseline`); DetectStackDrift re-reads the same live state and diffs it
against that baseline, so a property changed out-of-band through the owning service's
own console/API (DynamoDB billing mode, SNS display name, SQS visibility timeout, an
IAM role's trust policy, a log group's retention) is reported as MODIFIED with
PropertyDifferences — not just DELETED/IN_SYNC. S3 buckets have no provisioner-managed
mutable property, so they remain existence-only.

Scope (v1 slice): CreateStack/UpdateStack/DeleteStack with dependency ordering, Ref/
Fn::GetAtt/Fn::Sub/Fn::Join/Fn::Select/Fn::Split/Fn::FindInMap/Fn::Base64/Fn::ImportValue/
Fn::If/Fn::Equals/Fn::And/Fn::Or/Fn::Not/Fn::GetAZs/Conditions, Outputs + Exports
(global-uniqueness enforced), ChangeSets (create/describe/execute/delete/list),
DescribeStackEvents/Resources, ListExports, ValidateTemplate, StackSets (control-plane
only — no multi-account/region deployment, matching the real console's "StackSets" being
largely a cross-account feature Vyomi doesn't model), stack drift (detects a resource
deleted independently through its own service's store), termination protection,
ContinueUpdateRollback, stack refactors (CreateStackRefactor/ExecuteStackRefactor really
move a resource's runtime state — ref/physical id/properties — between two existing
stacks; no new-stack StackDefinitions), the registry's ListTypes/DescribeType (the
resource types above, the real activated-extension catalog, PUBLIC/RESOURCE only).
"""
from __future__ import annotations

import base64
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

from core import s3_object_core as s3mod
from core import dynamodb_core as ddbmod
from core import sns_core as snsmod
from core import sqs_core as sqsmod
from core import iam_core as iammod
from core import logs_core as logsmod

CFN_NS = "http://cloudformation.amazonaws.com/doc/2010-05-15/"
REGION = "us-east-1"
DEFAULT_ACCOUNT_ID = "123456789012"
TERMINAL_DELETED = {"DELETE_COMPLETE"}
UPDATABLE_STATUSES = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}


@dataclass
class CfnResponse:
    status: int = 200
    body: str = ""          # XML text
    headers: dict = field(default_factory=dict)
    media_type: str = "text/xml"


class CfnError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


class CloudFormationStore:
    """In-memory CloudFormation control plane: stacks, change sets, stack sets."""

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID) -> None:
        self.stacks: dict[str, dict] = {}          # stack_id -> stack record (kept after delete, for history)
        self.stack_names: dict[str, str] = {}      # name -> stack_id, ACTIVE (non-deleted) stacks only
        self.change_sets: dict[str, dict] = {}
        self.stack_sets: dict[str, dict] = {}
        self.stack_set_instances: dict[str, list] = {}
        self.stack_refactors: dict[str, dict] = {}
        self.drift_detections: dict[str, dict] = {}
        self.account_id = account_id

    def persist(self) -> None:
        """Flush state to durable storage (appliance ctx in Pro/Max, IDB in Nano)."""


# ── response builders (native CloudFormation Query-protocol XML) ───────────
def _xe(s) -> str:
    return _xml_escape(str(s))


def _el(tag: str, value) -> str:
    if value is None or value == "":
        return ""
    return f"<{tag}>{_xe(value)}</{tag}>"


def _envelope(action: str, inner: str = "") -> CfnResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<{action}Response xmlns="{CFN_NS}">'
           f'<{action}Result>{inner}</{action}Result>'
           f'<ResponseMetadata><RequestId>{uuid.uuid4()}</RequestId></ResponseMetadata>'
           f'</{action}Response>')
    return CfnResponse(body=xml)


def _error(code: str, message: str, status: int = 400) -> CfnResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<ErrorResponse xmlns="{CFN_NS}"><Error><Type>Sender</Type>'
           f'<Code>{_xe(code)}</Code><Message>{_xe(message)}</Message></Error>'
           f'<RequestId>{uuid.uuid4()}</RequestId></ErrorResponse>')
    return CfnResponse(status=status, body=xml)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _bool(v) -> bool:
    return str(v).strip().lower() == "true"


def _p(params: dict, key: str, default: str = "") -> str:
    v = params.get(key, default)
    return v if v is not None else default


def _members(params: dict, prefix: str) -> list:
    out, i = [], 1
    while f"{prefix}.member.{i}" in params:
        out.append(params[f"{prefix}.member.{i}"])
        i += 1
    return out


def _param_pairs(params: dict, prefix: str = "Parameters") -> dict:
    out, i = {}, 1
    while f"{prefix}.member.{i}.ParameterKey" in params:
        out[params[f"{prefix}.member.{i}.ParameterKey"]] = params.get(f"{prefix}.member.{i}.ParameterValue", "")
        i += 1
    return out


def _tag_pairs(params: dict, prefix: str = "Tags") -> dict:
    out, i = {}, 1
    while f"{prefix}.member.{i}.Key" in params:
        out[params[f"{prefix}.member.{i}.Key"]] = params.get(f"{prefix}.member.{i}.Value", "")
        i += 1
    return out


def _stack_arn(name: str, stack_uid: str) -> str:
    return f"arn:aws:cloudformation:{REGION}:{DEFAULT_ACCOUNT_ID}:stack/{name}/{stack_uid}"


# ── template body / S3 URL fetch ────────────────────────────────────────────
_S3_URL_RE = re.compile(
    r"^https?://(?:s3[.\-][\w.\-]*\.amazonaws\.com/(?P<b1>[^/]+)/(?P<k1>.+)"
    r"|(?P<b2>[^./]+)\.s3[.\-][\w.\-]*\.amazonaws\.com/(?P<k2>.+))$")


def _fetch_template_url(stores: dict, url: str) -> str:
    url = str(url)
    if url.startswith("s3://"):
        bucket, _, key = url[5:].partition("/")
    else:
        m = _S3_URL_RE.match(url)
        if not m:
            raise CfnError("ValidationError", f"TemplateURL must be an Amazon S3 URL: {url}", 400)
        bucket = m.group("b1") or m.group("b2")
        key = m.group("k1") or m.group("k2")
    s3_store = stores.get("s3")
    r = s3mod.dispatch(s3_store, "GET", f"/{bucket}/{key}", {}, {}, b"")
    if r.status != 200:
        raise CfnError("ValidationError", f"Unable to retrieve template from S3 URL: {url}", 400)
    body = r.body or b""
    return body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)


def _template_body(params: dict, stores: dict) -> str:
    body = params.get("TemplateBody")
    if body:
        return str(body)
    url = params.get("TemplateURL")
    if url:
        return _fetch_template_url(stores, url)
    raise CfnError("ValidationError", "Either TemplateBody or TemplateURL must be specified.", 400)


# ── template parsing: JSON, else a YAML subset (block maps/seqs + short-form !Tags) ─
_YAML_TAGS = {"!Ref": "Ref", "!Condition": "Condition"}
_YAML_FN_TAGS = {
    "!GetAtt": "Fn::GetAtt", "!Sub": "Fn::Sub", "!Join": "Fn::Join", "!Select": "Fn::Select",
    "!Split": "Fn::Split", "!FindInMap": "Fn::FindInMap", "!Base64": "Fn::Base64",
    "!ImportValue": "Fn::ImportValue", "!Equals": "Fn::Equals", "!If": "Fn::If",
    "!And": "Fn::And", "!Or": "Fn::Or", "!Not": "Fn::Not", "!GetAZs": "Fn::GetAZs",
    "!Cidr": "Fn::Cidr",
}
_KEY_RE = r'^([A-Za-z0-9_.\-]+|"[^"]*"|\'[^\']*\')\s*:(\s.*|)$'


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _split_flow(s: str) -> list:
    out, depth, cur, q = [], 0, "", None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
            cur += ch
            continue
        if ch in "[{":
            depth += 1
            cur += ch
            continue
        if ch in "]}":
            depth -= 1
            cur += ch
            continue
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        cur += ch
    if cur.strip():
        out.append(cur)
    return out


def _yaml_scalar(raw: str):
    s = raw.strip()
    if s == "":
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    low = s.lower()
    if low in ("null", "~"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    for tag, key in list(_YAML_TAGS.items()) + list(_YAML_FN_TAGS.items()):
        if s == tag:
            return {key: None}
        if s.startswith(tag + " "):
            arg = s[len(tag):].strip()
            parsed = _yaml_flow_or_scalar(arg)
            if key == "Fn::GetAtt" and isinstance(parsed, str) and "." in parsed:
                parsed = parsed.split(".", 1)
            return {key: parsed}
    if re.match(r"^-?\d+$", s):
        return int(s)
    if re.match(r"^-?\d+\.\d+$", s):
        return float(s)
    return s


def _yaml_flow_or_scalar(s: str):
    s = s.strip()
    if s.startswith("[") or s.startswith("{"):
        try:
            return json.loads(s)
        except Exception:
            pass
        if s.startswith("[") and s.endswith("]"):
            inner = s[1:-1].strip()
            return [_yaml_scalar(x) for x in _split_flow(inner)] if inner else []
    return _yaml_scalar(s)


def _strip_comment(line: str) -> str:
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] == " "):
            return line[:i]
    return line


def _yaml_lines(text: str) -> list:
    out = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        bare = line.strip()
        if not bare or bare.startswith("#") or bare in ("---", "..."):
            continue
        stripped = _strip_comment(line)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        out.append((indent, stripped.strip()))
    return out


def _yaml_parse_map(lines: list, i: int, indent: int):
    obj = {}
    n = len(lines)
    while i < n and lines[i][0] == indent:
        m = re.match(_KEY_RE, lines[i][1])
        if not m:
            break
        key = _unquote(m.group(1))
        valtxt = m.group(2).strip()
        if valtxt in ("|", ">", "|-", ">-", "|+", ">+"):
            block, j = [], i + 1
            while j < n and lines[j][0] > indent:
                block.append(lines[j][1])
                j += 1
            obj[key] = ("\n".join(block) if valtxt[0] == "|" else " ".join(block))
            i = j
            continue
        if valtxt:
            obj[key] = _yaml_scalar(valtxt)
            i += 1
        else:
            i += 1
            if i < n and lines[i][0] > indent:
                nested, i = _yaml_parse_block(lines, i, lines[i][0])
                obj[key] = nested
            else:
                obj[key] = None
    return obj, i


def _yaml_fill_map_from(obj: dict, first_match, lines: list, i: int, item_indent: int) -> int:
    key = _unquote(first_match.group(1))
    valtxt = first_match.group(2).strip()
    n = len(lines)
    if valtxt:
        obj[key] = _yaml_scalar(valtxt)
        i += 1
    else:
        i += 1
        if i < n and lines[i][0] > item_indent - 1 and lines[i][0] >= item_indent:
            nested, i = _yaml_parse_block(lines, i, lines[i][0])
            obj[key] = nested
        else:
            obj[key] = None
    while i < n and lines[i][0] == item_indent:
        mm = re.match(_KEY_RE, lines[i][1])
        if not mm:
            break
        i = _yaml_fill_map_from(obj, mm, lines, i, item_indent)
    return i


def _yaml_parse_seq(lines: list, i: int, indent: int):
    items = []
    n = len(lines)
    while i < n and lines[i][0] == indent and (lines[i][1] == "-" or lines[i][1].startswith("- ")):
        content = lines[i][1]
        rest = content[1:].strip() if content != "-" else ""
        item_indent = indent + 2
        if not rest:
            i += 1
            if i < n and lines[i][0] >= item_indent:
                val, i = _yaml_parse_block(lines, i, lines[i][0])
            else:
                val = None
            items.append(val)
            continue
        m = re.match(_KEY_RE, rest)
        if m and not rest.startswith(("!", "[", "{", '"', "'")):
            obj = {}
            i = _yaml_fill_map_from(obj, m, lines, i, item_indent)
            items.append(obj)
            continue
        items.append(_yaml_scalar(rest))
        i += 1
    return items, i


def _yaml_parse_block(lines: list, i: int, indent: int):
    if i >= len(lines) or lines[i][0] < indent:
        return None, i
    base = lines[i][0]
    if lines[i][1] == "-" or lines[i][1].startswith("- "):
        return _yaml_parse_seq(lines, i, base)
    return _yaml_parse_map(lines, i, base)


def _parse_yaml(text: str) -> dict:
    lines = _yaml_lines(text)
    if not lines:
        return {}
    val, _ = _yaml_parse_block(lines, 0, lines[0][0])
    if not isinstance(val, dict):
        raise CfnError("ValidationError", "Template format error: top level must be a mapping", 400)
    return val


def _parse_template(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        raise CfnError("ValidationError", "Template body is empty.", 400)
    try:
        doc = json.loads(raw)
    except Exception:
        try:
            doc = _parse_yaml(raw)
        except CfnError:
            raise
        except Exception as e:
            raise CfnError("ValidationError", f"Template format error: unable to parse as JSON or YAML ({e})", 400)
    if not isinstance(doc, dict):
        raise CfnError("ValidationError", "Template format error: template body must be a JSON/YAML object.", 400)
    return doc


# ── resource provisioners: each creates/deletes/checks through the REAL core ───
def _gen_physical_name(stack_name: str, logical_id: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9-]", "-", f"{stack_name}-{logical_id}").strip("-").lower()
    suffix = uuid.uuid4().hex[:8]
    name = f"{base}-{suffix}"[:63].strip("-")
    return name or f"cfn-{suffix}"


def _wire_message(body) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or body.get("Message") or body.get("__type") or "request failed")
    m = re.search(r"<Message>(.*?)</Message>", str(body), re.S)
    return m.group(1) if m else "request failed"


def _prov_s3_bucket(stores, name, props):
    r = s3mod.dispatch(stores["s3"], "PUT", f"/{name}", {}, {}, b"")
    if r.status != 200:
        raise CfnError("CREATE_FAILED", _wire_message(r.body), 400)
    return {"ref": name, "physical_id": name,
            "attrs": {"Arn": f"arn:aws:s3:::{name}", "DomainName": f"{name}.s3.amazonaws.com",
                      "RegionalDomainName": f"{name}.s3.{REGION}.amazonaws.com"}}


def _teardown_s3_bucket(stores, physical_id):
    r = s3mod.dispatch(stores["s3"], "DELETE", f"/{physical_id}", {}, {}, b"")
    if r.status not in (200, 204, 404):
        raise CfnError("DELETE_FAILED", _wire_message(r.body), 400)


def _exists_s3_bucket(stores, physical_id):
    return stores["s3"].bucket_exists(physical_id)


def _prov_ddb_table(stores, name, props):
    payload = dict(props)
    payload["TableName"] = name
    if "BillingMode" not in payload and "ProvisionedThroughput" not in payload:
        payload["BillingMode"] = "PAY_PER_REQUEST"
    r = ddbmod.dispatch(stores["ddb"], "DynamoDB_20120810.CreateTable", payload)
    if r.status != 200:
        raise CfnError("CREATE_FAILED", _wire_message(r.body), 400)
    desc = (r.body or {}).get("TableDescription", {})
    return {"ref": name, "physical_id": name,
            "attrs": {"Arn": desc.get("TableArn", ""), "StreamArn": desc.get("LatestStreamArn", "")}}


def _update_ddb_table(stores, table_name, props):
    payload = {"TableName": table_name}
    for k in ("BillingMode", "ProvisionedThroughput", "SSESpecification"):
        if k in props:
            payload[k] = props[k]
    if len(payload) == 1:
        return {"attrs": {}}
    r = ddbmod.dispatch(stores["ddb"], "DynamoDB_20120810.UpdateTable", payload)
    if r.status != 200:
        raise CfnError("UPDATE_FAILED", _wire_message(r.body), 400)
    desc = (r.body or {}).get("TableDescription", {})
    return {"attrs": {"Arn": desc.get("TableArn", "")}}


def _teardown_ddb_table(stores, physical_id):
    r = ddbmod.dispatch(stores["ddb"], "DynamoDB_20120810.DeleteTable", {"TableName": physical_id})
    if r.status != 200 and (r.body or {}).get("__type") != "ResourceNotFoundException":
        raise CfnError("DELETE_FAILED", _wire_message(r.body), 400)


def _exists_ddb_table(stores, physical_id):
    return stores["ddb"].get_table(physical_id) is not None


def _read_ddb_table(stores, physical_id):
    t = stores["ddb"].get_table(physical_id)
    if not t:
        return None
    return {"BillingMode": t.get("billing_mode", "PAY_PER_REQUEST"),
            "ProvisionedThroughput": t.get("provisioned_throughput") or {}}


def _prov_sns_topic(stores, name, props):
    msg_store = stores["msg"]
    params = {"Action": "CreateTopic", "Name": name}
    attrs_in = {}
    if props.get("FifoTopic") or name.endswith(".fifo"):
        attrs_in["FifoTopic"] = "true"
    if props.get("DisplayName"):
        attrs_in["DisplayName"] = str(props["DisplayName"])
    for i, (k, v) in enumerate(attrs_in.items(), start=1):
        params[f"Attributes.entry.{i}.key"] = k
        params[f"Attributes.entry.{i}.value"] = v
    r = snsmod.dispatch(msg_store, params)
    if r.status != 200:
        raise CfnError("CREATE_FAILED", _wire_message(r.body), 400)
    arn = f"arn:aws:sns:{REGION}:{DEFAULT_ACCOUNT_ID}:{name}"
    return {"ref": arn, "physical_id": arn, "attrs": {"TopicName": name}}


def _teardown_sns_topic(stores, physical_id):
    r = snsmod.dispatch(stores["msg"], {"Action": "DeleteTopic", "TopicArn": physical_id})
    if r.status != 200:
        raise CfnError("DELETE_FAILED", _wire_message(r.body), 400)


def _exists_sns_topic(stores, physical_id):
    return stores["msg"].get_topic(physical_id) is not None


def _read_sns_topic(stores, physical_id):
    t = stores["msg"].get_topic(physical_id)
    if not t:
        return None
    attrs = t.get("attributes") or {}
    return {"DisplayName": attrs.get("DisplayName", ""),
            "FifoTopic": str(attrs.get("FifoTopic", "false")).lower() == "true"}


def _prov_sqs_queue(stores, name, props):
    msg_store = stores["msg"]
    attrs = {}
    if props.get("FifoQueue"):
        attrs["FifoQueue"] = "true"
    if props.get("ContentBasedDeduplication"):
        attrs["ContentBasedDeduplication"] = "true"
    if props.get("VisibilityTimeout") is not None:
        attrs["VisibilityTimeout"] = str(props["VisibilityTimeout"])
    if props.get("MessageRetentionPeriod") is not None:
        attrs["MessageRetentionPeriod"] = str(props["MessageRetentionPeriod"])
    r = sqsmod.dispatch(msg_store, "AmazonSQS.CreateQueue", {"QueueName": name, "Attributes": attrs})
    if r.status != 200:
        raise CfnError("CREATE_FAILED", _wire_message(r.body), 400)
    q = msg_store.get_queue(name) or {}
    url = (r.body or {}).get("QueueUrl", "")
    return {"ref": url, "physical_id": name, "attrs": {"Arn": q.get("queue_arn", ""), "QueueName": name}}


def _teardown_sqs_queue(stores, physical_id):
    msg_store = stores["msg"]
    q = msg_store.get_queue(physical_id)
    url = q["queue_url"] if q else physical_id
    r = sqsmod.dispatch(msg_store, "AmazonSQS.DeleteQueue", {"QueueUrl": url})
    if r.status != 200 and (r.body or {}).get("__type") not in (None, "com.amazonaws.sqs#QueueDoesNotExist"):
        raise CfnError("DELETE_FAILED", _wire_message(r.body), 400)


def _exists_sqs_queue(stores, physical_id):
    return stores["msg"].get_queue(physical_id) is not None


def _read_sqs_queue(stores, physical_id):
    q = stores["msg"].get_queue(physical_id)
    if not q:
        return None
    attrs = q.get("attributes") or {}
    return {"VisibilityTimeout": int(q.get("visibility_timeout", 30)),
            "MessageRetentionPeriod": int(attrs.get("MessageRetentionPeriod", 345600)),
            "FifoQueue": bool(q.get("fifo", False)),
            "ContentBasedDeduplication": bool(q.get("content_based_dedup", False))}


def _prov_iam_role(stores, name, props):
    iam_store = stores["iam"]
    params = {"Action": "CreateRole", "RoleName": name}
    doc = props.get("AssumeRolePolicyDocument")
    if doc is not None:
        params["AssumeRolePolicyDocument"] = json.dumps(doc) if isinstance(doc, (dict, list)) else str(doc)
    if props.get("Description"):
        params["Description"] = str(props["Description"])
    if props.get("Path"):
        params["Path"] = str(props["Path"])
    r = iammod.dispatch(iam_store, params)
    if r.status != 200:
        raise CfnError("CREATE_FAILED", _wire_message(r.body), 400)
    role = iam_store.get_role(name) or {}
    return {"ref": name, "physical_id": name, "attrs": {"Arn": role.get("arn", ""), "RoleId": role.get("role_id", "")}}


def _teardown_iam_role(stores, physical_id):
    r = iammod.dispatch(stores["iam"], {"Action": "DeleteRole", "RoleName": physical_id})
    if r.status != 200:
        raise CfnError("DELETE_FAILED", _wire_message(r.body), 400)


def _exists_iam_role(stores, physical_id):
    return stores["iam"].get_role(physical_id) is not None


def _read_iam_role(stores, physical_id):
    role = stores["iam"].get_role(physical_id)
    if not role:
        return None
    return {"AssumeRolePolicyDocument": role.get("assume_role_policy_document") or {},
            "Description": role.get("description", ""), "Path": role.get("path", "/")}


def _prov_log_group(stores, name, props):
    logs_store = stores["logs"]
    r = logsmod.dispatch(logs_store, "Logs_20140328.CreateLogGroup", {"logGroupName": name})
    if r.status != 200:
        raise CfnError("CREATE_FAILED", _wire_message(r.body), 400)
    if props.get("RetentionInDays") is not None:
        rr = logsmod.dispatch(logs_store, "Logs_20140328.PutRetentionPolicy",
                              {"logGroupName": name, "retentionInDays": int(props["RetentionInDays"])})
        if rr.status != 200:
            raise CfnError("CREATE_FAILED", _wire_message(rr.body), 400)
    g = logs_store.log_groups.get(name) or {}
    return {"ref": name, "physical_id": name, "attrs": {"Arn": g.get("arn", "")}}


def _update_log_group(stores, name, props):
    logs_store = stores["logs"]
    if props.get("RetentionInDays") is not None:
        r = logsmod.dispatch(logs_store, "Logs_20140328.PutRetentionPolicy",
                             {"logGroupName": name, "retentionInDays": int(props["RetentionInDays"])})
    else:
        r = logsmod.dispatch(logs_store, "Logs_20140328.DeleteRetentionPolicy", {"logGroupName": name})
    if r.status != 200:
        raise CfnError("UPDATE_FAILED", _wire_message(r.body), 400)
    return {"attrs": {}}


def _teardown_log_group(stores, physical_id):
    r = logsmod.dispatch(stores["logs"], "Logs_20140328.DeleteLogGroup", {"logGroupName": physical_id})
    if r.status != 200 and (r.body or {}).get("__type") != "ResourceNotFoundException":
        raise CfnError("DELETE_FAILED", _wire_message(r.body), 400)


def _exists_log_group(stores, physical_id):
    return stores["logs"].log_groups.get(physical_id) is not None


def _read_log_group(stores, physical_id):
    g = stores["logs"].log_groups.get(physical_id)
    if not g:
        return None
    return {"RetentionInDays": g.get("retentionInDays")}


def _prov_virtual(kind):
    def _create(stores, name, props):
        token = uuid.uuid4().hex
        return {"ref": f"arn:aws:cloudformation:{REGION}:{DEFAULT_ACCOUNT_ID}:{kind}/{name}/{token}",
                "physical_id": f"{name}-{token[:8]}", "attrs": {}}
    return _create


def _teardown_virtual(stores, physical_id):
    pass


def _exists_virtual(stores, physical_id):
    return True


RESOURCE_TYPES = {
    "AWS::S3::Bucket": {"create": _prov_s3_bucket, "delete": _teardown_s3_bucket,
                        "exists": _exists_s3_bucket, "name_prop": "BucketName"},
    "AWS::DynamoDB::Table": {"create": _prov_ddb_table, "delete": _teardown_ddb_table,
                             "exists": _exists_ddb_table, "update": _update_ddb_table,
                             "read": _read_ddb_table, "name_prop": "TableName"},
    "AWS::SNS::Topic": {"create": _prov_sns_topic, "delete": _teardown_sns_topic,
                        "exists": _exists_sns_topic, "read": _read_sns_topic, "name_prop": "TopicName"},
    "AWS::SQS::Queue": {"create": _prov_sqs_queue, "delete": _teardown_sqs_queue,
                        "exists": _exists_sqs_queue, "read": _read_sqs_queue, "name_prop": "QueueName"},
    "AWS::IAM::Role": {"create": _prov_iam_role, "delete": _teardown_iam_role,
                       "exists": _exists_iam_role, "read": _read_iam_role, "name_prop": "RoleName"},
    "AWS::Logs::LogGroup": {"create": _prov_log_group, "delete": _teardown_log_group,
                            "exists": _exists_log_group, "update": _update_log_group,
                            "read": _read_log_group, "name_prop": "LogGroupName"},
    "AWS::CloudFormation::WaitConditionHandle": {
        "create": _prov_virtual("waitconditionhandle"), "delete": _teardown_virtual,
        "exists": _exists_virtual, "name_prop": None},
    "AWS::CloudFormation::WaitCondition": {
        "create": _prov_virtual("waitcondition"), "delete": _teardown_virtual,
        "exists": _exists_virtual, "name_prop": None},
}


# ── intrinsic-function resolver ─────────────────────────────────────────────
def _pseudo(name, ctx):
    return {
        "AWS::Region": ctx["region"], "AWS::AccountId": ctx["account_id"],
        "AWS::StackName": ctx["stack_name"], "AWS::StackId": ctx["stack_id"],
        "AWS::Partition": "aws", "AWS::URLSuffix": "amazonaws.com",
        "AWS::NoValue": None, "AWS::NotificationARNs": [],
    }[name]


_PSEUDO_NAMES = {"AWS::Region", "AWS::AccountId", "AWS::StackName", "AWS::StackId",
                  "AWS::Partition", "AWS::URLSuffix", "AWS::NoValue", "AWS::NotificationARNs"}


def _resolve_ref(name, ctx):
    if name in _PSEUDO_NAMES:
        return _pseudo(name, ctx)
    if name in ctx["params"]:
        return ctx["params"][name]
    if name in ctx["resources"]:
        return ctx["resources"][name]["ref"]
    raise CfnError("ValidationError", f"Template error: instance of Ref doesn't exist {name}", 400)


def _resolve_getatt(v, ctx):
    if isinstance(v, list):
        logical, attr = v[0], ".".join(str(x) for x in v[1:])
    else:
        logical, _, attr = str(v).partition(".")
    res = ctx["resources"].get(logical)
    if res is None:
        raise CfnError("ValidationError",
                        f"Template error: instance of Fn::GetAtt references undefined resource {logical}", 400)
    if attr in res.get("attrs", {}):
        return res["attrs"][attr]
    return res["ref"]


_SUB_RE = re.compile(r"\$\{([^}!][^}]*)\}")


def _resolve_sub(v, ctx):
    if isinstance(v, list):
        template_str, var_map = v[0], (v[1] if len(v) > 1 else {})
    else:
        template_str, var_map = v, {}
    var_map = _resolve(var_map, ctx) if var_map else {}

    def repl(m):
        key = m.group(1).strip()
        if key in var_map:
            return str(var_map[key])
        if "." in key:
            return str(_resolve_getatt(key, ctx))
        return str(_resolve_ref(key, ctx))

    return _SUB_RE.sub(repl, template_str)


def _lookup_export(ctx, name):
    store = ctx.get("store")
    if store:
        for st in store.stacks.values():
            if st["stack_id"] == ctx.get("stack_id") or st["status"] in TERMINAL_DELETED:
                continue
            for o in st.get("outputs", []):
                if o.get("ExportName") == name:
                    return o.get("OutputValue")
    raise CfnError("ValidationError", f"No export named {name} found.", 400)


def _resolve(value, ctx):
    if isinstance(value, dict):
        if len(value) == 1:
            k, v = next(iter(value.items()))
            if k == "Ref":
                return _resolve_ref(v, ctx)
            if k == "Fn::GetAtt":
                return _resolve_getatt(v, ctx)
            if k == "Fn::Sub":
                return _resolve_sub(v, ctx)
            if k == "Fn::Join":
                delim, items = _resolve(v, ctx)
                return delim.join(str(x) for x in items if x is not None)
            if k == "Fn::Select":
                idx, items = _resolve(v, ctx)
                return items[int(idx)]
            if k == "Fn::Split":
                delim, s = _resolve(v, ctx)
                return str(s).split(delim)
            if k == "Fn::FindInMap":
                mname, k1, k2 = _resolve(v, ctx)
                mp = ctx["mappings"].get(mname, {})
                return (mp.get(k1) or {}).get(k2)
            if k == "Fn::Base64":
                return base64.b64encode(str(_resolve(v, ctx)).encode()).decode()
            if k == "Fn::ImportValue":
                return _lookup_export(ctx, _resolve(v, ctx))
            if k == "Fn::GetAZs":
                return [f"{ctx['region']}a", f"{ctx['region']}b", f"{ctx['region']}c"]
            if k == "Fn::If":
                cond, t, f = v
                return _resolve(t, ctx) if ctx["conditions"].get(cond) else _resolve(f, ctx)
            if k == "Fn::Equals":
                a, b = _resolve(v, ctx)
                return str(a) == str(b)
            if k == "Fn::Not":
                return not _resolve(v[0] if isinstance(v, list) else v, ctx)
            if k == "Fn::And":
                return all(_resolve(x, ctx) for x in v)
            if k == "Fn::Or":
                return any(_resolve(x, ctx) for x in v)
            if k == "Condition":
                return ctx["conditions"].get(v, False)
            if k == "Fn::Cidr":
                return []
        return {kk: _resolve(vv, ctx) for kk, vv in value.items()}
    if isinstance(value, list):
        return [_resolve(x, ctx) for x in value]
    return value


def _stringify(value) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


# ── parameters / conditions / dependency order ──────────────────────────────
def _coerce_param(pdef, value):
    allowed = pdef.get("AllowedValues")
    if allowed and str(value) not in [str(a) for a in allowed]:
        raise CfnError("ValidationError", f"Parameter value {value} is not one of the allowed values", 400)
    pattern = pdef.get("AllowedPattern")
    if pattern and not re.match(pattern, str(value)):
        raise CfnError("ValidationError", f"Parameter value {value} does not match pattern {pattern}", 400)
    return value


def _resolve_parameters(template, supplied):
    defs = template.get("Parameters") or {}
    out, missing = {}, []
    for key, pdef in defs.items():
        if key in supplied and supplied[key] != "":
            out[key] = _coerce_param(pdef, supplied[key])
        elif "Default" in pdef:
            out[key] = pdef["Default"]
        else:
            missing.append(key)
    if missing:
        raise CfnError("ValidationError", f"Parameters: [{', '.join(missing)}] must have values", 400)
    extra = sorted(set(supplied) - set(defs))
    if extra:
        raise CfnError("ValidationError", f"Parameters: [{', '.join(extra)}] do not exist in the template", 400)
    return out


def _eval_conditions(template, params_ctx):
    conds_def = template.get("Conditions") or {}
    ctx = {"params": params_ctx, "resources": {}, "mappings": template.get("Mappings") or {},
           "conditions": {}, "region": REGION, "account_id": DEFAULT_ACCOUNT_ID,
           "stack_name": "", "stack_id": ""}
    resolved = {}

    def ev(name, seen):
        if name in resolved:
            return resolved[name]
        if name in seen:
            raise CfnError("ValidationError", f"Circular condition dependency: {name}", 400)
        seen.add(name)
        expr = conds_def.get(name)
        if expr is None:
            raise CfnError("ValidationError", f"Unresolved condition: {name}", 400)
        ctx["conditions"] = resolved
        val = bool(_resolve(expr, ctx))
        resolved[name] = val
        return val

    for name in conds_def:
        ev(name, set())
    return resolved


def _topo_order(resources_def):
    deps = {lid: set() for lid in resources_def}

    def scan(node, lid):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "Ref" and isinstance(v, str) and v in resources_def and v != lid:
                    deps[lid].add(v)
                elif k == "Fn::GetAtt":
                    target = v[0] if isinstance(v, list) else str(v).split(".")[0]
                    if target in resources_def and target != lid:
                        deps[lid].add(target)
                else:
                    scan(v, lid)
        elif isinstance(node, list):
            for it in node:
                scan(it, lid)

    for lid, rdef in resources_def.items():
        scan(rdef.get("Properties") or {}, lid)
        dep_on = rdef.get("DependsOn")
        if dep_on:
            for d in (dep_on if isinstance(dep_on, list) else [dep_on]):
                if d in resources_def:
                    deps[lid].add(d)

    order, visited, path = [], set(), set()

    def visit(lid):
        if lid in visited:
            return
        if lid in path:
            raise CfnError("ValidationError", f"Circular dependency between resources: [{lid}]", 400)
        path.add(lid)
        for d in sorted(deps.get(lid, ())):
            visit(d)
        path.discard(lid)
        visited.add(lid)
        order.append(lid)

    for lid in sorted(resources_def):
        visit(lid)
    return order


def _check_capabilities(resources_def, capabilities):
    iam_defs = [r for r in resources_def.values() if str(r.get("Type", "")).startswith("AWS::IAM::")]
    if not iam_defs:
        return
    named = any(isinstance(r.get("Properties"), dict) and
                any(r["Properties"].get(k) for k in ("RoleName", "UserName", "GroupName", "PolicyName"))
                for r in iam_defs)
    need = "CAPABILITY_NAMED_IAM" if named else "CAPABILITY_IAM"
    if need not in capabilities and "CAPABILITY_NAMED_IAM" not in capabilities:
        raise CfnError("InsufficientCapabilitiesException", f"Requires capabilities : [{need}]", 400)


# ── events ───────────────────────────────────────────────────────────────────
def _emit_event(stack, logical_id, status, reason="", rtype=None, physical_id=None):
    is_stack_level = logical_id == stack["stack_name"]
    stack["events"].insert(0, {
        "EventId": uuid.uuid4().hex, "StackId": stack["stack_id"], "StackName": stack["stack_name"],
        "LogicalResourceId": logical_id,
        "PhysicalResourceId": physical_id if physical_id is not None else (stack["stack_id"] if is_stack_level else ""),
        "ResourceType": rtype or "AWS::CloudFormation::Stack",
        "Timestamp": _now_iso(), "ResourceStatus": status, "ResourceStatusReason": reason,
    })
    del stack["events"][500:]


# ── stack record / resource application ─────────────────────────────────────
def _new_stack_record(stack_id, name, stack_uid):
    now = _now_iso()
    return {"stack_id": stack_id, "stack_name": name, "stack_uid": stack_uid,
            "status": "CREATE_IN_PROGRESS", "status_reason": "", "description": "",
            "creation_time": now, "last_updated_time": now, "deletion_time": "",
            "parameters": {}, "outputs": [], "tags": {}, "capabilities": [],
            "role_arn": "", "on_failure": "ROLLBACK", "disable_rollback": False,
            "termination_protection": False, "template_body": "", "resources": {},
            "events": [], "drift_status": "NOT_CHECKED", "drift_checked_time": ""}


def _build_ctx(stack, template, params_ctx, store=None):
    return {"params": params_ctx,
            "resources": {lid: {"ref": r["ref"], "attrs": r["attrs"]} for lid, r in stack["resources"].items()},
            "mappings": template.get("Mappings") or {}, "conditions": {},
            "region": REGION, "account_id": DEFAULT_ACCOUNT_ID,
            "stack_name": stack["stack_name"], "stack_id": stack["stack_id"], "store": store}


def _check_export_unique(store, stack_id, export_name):
    for st in store.stacks.values():
        if st["stack_id"] == stack_id or st["status"] in TERMINAL_DELETED:
            continue
        for o in st.get("outputs", []):
            if o.get("ExportName") == export_name:
                raise CfnError("ValidationError",
                                f"Export {export_name} is already exported by stack {st['stack_name']}", 400)


def _apply_outputs(store, stack, template, ctx):
    outputs_def = template.get("Outputs") or {}
    outs = []
    for key, odef in outputs_def.items():
        cond = odef.get("Condition")
        if cond and not ctx["conditions"].get(cond, True):
            continue
        value = _resolve(odef.get("Value"), ctx)
        export = None
        if "Export" in odef:
            export = str(_resolve(odef["Export"].get("Name"), ctx))
            _check_export_unique(store, stack["stack_id"], export)
        outs.append({"OutputKey": key, "OutputValue": _stringify(value),
                     "Description": odef.get("Description", ""), "ExportName": export or ""})
    stack["outputs"] = outs


def _capture_baseline(provisioner, stores, physical_id):
    reader = provisioner.get("read")
    return reader(stores, physical_id) if reader else None


def _apply_resources(stack, template, params_ctx, stores, store=None):
    resources_def = template.get("Resources")
    if not isinstance(resources_def, dict) or not resources_def:
        raise CfnError("ValidationError", "Template format error: At least one Resources member must be defined.", 400)
    conditions = _eval_conditions(template, params_ctx)
    order = _topo_order(resources_def)
    ctx = _build_ctx(stack, template, params_ctx, store)
    ctx["conditions"] = conditions
    for logical_id in order:
        rdef = resources_def[logical_id]
        cond = rdef.get("Condition")
        if cond and not conditions.get(cond, True):
            continue
        rtype = rdef.get("Type", "")
        provisioner = RESOURCE_TYPES.get(rtype)
        if provisioner is None:
            raise CfnError("CREATE_FAILED",
                            f"{logical_id}: resource type {rtype} is not supported by Vyomi's "
                            f"CloudFormation simulation. Supported types: {', '.join(sorted(RESOURCE_TYPES))}.", 400)
        props = _resolve(rdef.get("Properties") or {}, ctx)
        name_prop = provisioner.get("name_prop")
        phys_name = props.get(name_prop) if name_prop else None
        if not phys_name:
            phys_name = _gen_physical_name(stack["stack_name"], logical_id)
        try:
            result = provisioner["create"](stores, phys_name, props)
        except CfnError:
            raise
        except Exception as e:
            raise CfnError("CREATE_FAILED", f"{logical_id} ({rtype}): {e}", 400)
        stack["resources"][logical_id] = {
            "LogicalResourceId": logical_id, "PhysicalResourceId": result["physical_id"],
            "ResourceType": rtype, "ResourceStatus": "CREATE_COMPLETE", "ResourceStatusReason": "",
            "Properties": props, "ref": result["ref"], "attrs": result.get("attrs", {}), "Module": "",
            "PropertiesBaseline": _capture_baseline(provisioner, stores, result["physical_id"])}
        ctx["resources"][logical_id] = {"ref": result["ref"], "attrs": result.get("attrs", {})}
        _emit_event(stack, logical_id, "CREATE_COMPLETE", "", rtype, result["physical_id"])
    stack["_ctx"] = ctx


def _rollback_resources(stack, stores):
    for logical_id, rec in reversed(list(stack["resources"].items())):
        prov = RESOURCE_TYPES.get(rec["ResourceType"])
        if prov:
            try:
                prov["delete"](stores, rec["PhysicalResourceId"])
            except Exception:
                pass
        _emit_event(stack, logical_id, "DELETE_COMPLETE", "", rec["ResourceType"], rec["PhysicalResourceId"])
        del stack["resources"][logical_id]


def _apply_update(stack, template, params_ctx, stores, store=None):
    resources_def = template.get("Resources") or {}
    if not resources_def:
        raise CfnError("ValidationError", "Template format error: At least one Resources member must be defined.", 400)
    conditions = _eval_conditions(template, params_ctx)
    order = _topo_order(resources_def)
    current = stack["resources"]
    ctx = _build_ctx(stack, template, params_ctx, store)
    ctx["conditions"] = conditions
    new_resources = {}
    for logical_id in order:
        rdef = resources_def[logical_id]
        cond = rdef.get("Condition")
        if cond and not conditions.get(cond, True):
            continue
        rtype = rdef.get("Type", "")
        provisioner = RESOURCE_TYPES.get(rtype)
        if provisioner is None:
            raise CfnError("UPDATE_FAILED",
                            f"{logical_id}: resource type {rtype} is not supported by Vyomi's "
                            f"CloudFormation simulation. Supported types: {', '.join(sorted(RESOURCE_TYPES))}.", 400)
        props = _resolve(rdef.get("Properties") or {}, ctx)
        existing = current.get(logical_id)
        if existing and existing["ResourceType"] == rtype and existing.get("Properties") == props:
            new_resources[logical_id] = existing
            ctx["resources"][logical_id] = {"ref": existing["ref"], "attrs": existing["attrs"]}
            continue
        if existing and existing["ResourceType"] == rtype and provisioner.get("update"):
            result = provisioner["update"](stores, existing["PhysicalResourceId"], props)
            rec = {**existing, "Properties": props, "ResourceStatus": "UPDATE_COMPLETE",
                   "ResourceStatusReason": "", "attrs": {**existing["attrs"], **result.get("attrs", {})},
                   "PropertiesBaseline": _capture_baseline(provisioner, stores, existing["PhysicalResourceId"])}
            new_resources[logical_id] = rec
            ctx["resources"][logical_id] = {"ref": rec["ref"], "attrs": rec["attrs"]}
            _emit_event(stack, logical_id, "UPDATE_COMPLETE", "", rtype, rec["PhysicalResourceId"])
            continue
        if existing and existing["ResourceType"] == rtype:
            reason = "Vyomi tracks this property change but does not re-provision the underlying resource."
            rec = {**existing, "Properties": props, "ResourceStatus": "UPDATE_COMPLETE", "ResourceStatusReason": reason}
            new_resources[logical_id] = rec
            ctx["resources"][logical_id] = {"ref": rec["ref"], "attrs": rec["attrs"]}
            _emit_event(stack, logical_id, "UPDATE_COMPLETE", reason, rtype, rec["PhysicalResourceId"])
            continue
        name_prop = provisioner.get("name_prop")
        phys_name = props.get(name_prop) if name_prop else None
        if not phys_name:
            phys_name = _gen_physical_name(stack["stack_name"], logical_id)
        try:
            result = provisioner["create"](stores, phys_name, props)
        except CfnError:
            raise
        except Exception as e:
            raise CfnError("UPDATE_FAILED", f"{logical_id} ({rtype}): {e}", 400)
        rec = {"LogicalResourceId": logical_id, "PhysicalResourceId": result["physical_id"],
               "ResourceType": rtype, "ResourceStatus": "CREATE_COMPLETE", "ResourceStatusReason": "",
               "Properties": props, "ref": result["ref"], "attrs": result.get("attrs", {}), "Module": "",
               "PropertiesBaseline": _capture_baseline(provisioner, stores, result["physical_id"])}
        new_resources[logical_id] = rec
        ctx["resources"][logical_id] = {"ref": result["ref"], "attrs": result.get("attrs", {})}
        _emit_event(stack, logical_id, "CREATE_COMPLETE", "", rtype, result["physical_id"])
        if existing:
            old_prov = RESOURCE_TYPES.get(existing["ResourceType"])
            if old_prov:
                try:
                    old_prov["delete"](stores, existing["PhysicalResourceId"])
                except Exception:
                    pass
            _emit_event(stack, logical_id, "DELETE_COMPLETE", "replaced", existing["ResourceType"],
                        existing["PhysicalResourceId"])
    for logical_id, rec in list(current.items()):
        if logical_id not in new_resources:
            prov = RESOURCE_TYPES.get(rec["ResourceType"])
            if prov:
                try:
                    prov["delete"](stores, rec["PhysicalResourceId"])
                except Exception as e:
                    raise CfnError("UPDATE_FAILED", f"{logical_id}: failed to remove — {e}", 400)
            _emit_event(stack, logical_id, "DELETE_COMPLETE", "", rec["ResourceType"], rec["PhysicalResourceId"])
    stack["resources"] = new_resources
    stack["_ctx"] = ctx


# ── stack-level actions ──────────────────────────────────────────────────────
def _require_stack(store, name):
    stack_id = store.stack_names.get(name)
    if not stack_id and name in store.stacks:
        stack_id = name
    if not stack_id:
        # DescribeStacks (unlike CreateStack's uniqueness check) must still find a
        # recently DELETE_COMPLETE stack by name, matching real AWS's retention window.
        candidates = sorted((s for s in store.stacks.values() if s["stack_name"] == name),
                            key=lambda s: s["creation_time"])
        if candidates:
            stack_id = candidates[-1]["stack_id"]
    if not stack_id or stack_id not in store.stacks:
        raise CfnError("ValidationError", f"Stack with id {name} does not exist", 400)
    return store.stacks[stack_id]


def _create_stack(store, params, stores):
    name = _p(params, "StackName")
    if not name or not re.match(r"^[A-Za-z][A-Za-z0-9-]{0,127}$", name):
        raise CfnError("ValidationError",
                        "Stack name must satisfy regular expression pattern: [a-zA-Z][-a-zA-Z0-9]*", 400)
    if name in store.stack_names:
        raise CfnError("AlreadyExistsException", f"Stack [{name}] already exists", 400)
    raw_template = _template_body(params, stores)
    template = _parse_template(raw_template)
    capabilities = set(_members(params, "Capabilities"))
    _check_capabilities(template.get("Resources") or {}, capabilities)
    on_failure = _p(params, "OnFailure", "ROLLBACK")
    disable_rollback = _bool(params.get("DisableRollback"))
    supplied = _param_pairs(params)
    stack_uid = uuid.uuid4().hex
    stack_id = _stack_arn(name, stack_uid)
    stack = _new_stack_record(stack_id, name, stack_uid)
    stack["description"] = str(template.get("Description", ""))[:1024]
    stack["tags"] = _tag_pairs(params)
    stack["capabilities"] = sorted(capabilities)
    stack["on_failure"] = on_failure
    stack["disable_rollback"] = disable_rollback
    stack["termination_protection"] = _bool(params.get("EnableTerminationProtection"))
    stack["role_arn"] = _p(params, "RoleARN")
    stack["template_body"] = raw_template
    store.stacks[stack_id] = stack
    store.stack_names[name] = stack_id
    _emit_event(stack, name, "CREATE_IN_PROGRESS", "User Initiated")
    try:
        params_ctx = _resolve_parameters(template, supplied)
        stack["parameters"] = params_ctx
        _apply_resources(stack, template, params_ctx, stores, store)
        _apply_outputs(store, stack, template, stack.pop("_ctx"))
        stack["status"] = "CREATE_COMPLETE"
        _emit_event(stack, name, "CREATE_COMPLETE")
    except CfnError as e:
        stack["status_reason"] = e.message
        if disable_rollback or on_failure == "DO_NOTHING":
            stack["status"] = "CREATE_FAILED"
            _emit_event(stack, name, "CREATE_FAILED", e.message)
        else:
            _emit_event(stack, name, "ROLLBACK_IN_PROGRESS", e.message)
            _rollback_resources(stack, stores)
            if on_failure == "DELETE":
                del store.stacks[stack_id]
                store.stack_names.pop(name, None)
                store.persist()
                raise CfnError("CREATE_FAILED", e.message, 400)
            stack["status"] = "ROLLBACK_COMPLETE"
            _emit_event(stack, name, "ROLLBACK_COMPLETE")
    store.persist()
    return _envelope("CreateStack", _el("StackId", stack_id))


def _update_stack(store, params, stores):
    name = _p(params, "StackName")
    stack = _require_stack(store, name)
    if stack["status"] not in UPDATABLE_STATUSES:
        raise CfnError("ValidationError", f"Stack [{name}] is in {stack['status']} state and can not be updated.", 400)
    use_previous = _bool(params.get("UsePreviousTemplate"))
    raw_template = stack["template_body"] if use_previous else _template_body(params, stores)
    template = _parse_template(raw_template)
    supplied = _param_pairs(params)
    for k, v in stack.get("parameters", {}).items():
        supplied.setdefault(k, v)
    capabilities = set(_members(params, "Capabilities")) or set(stack.get("capabilities", []))
    _check_capabilities(template.get("Resources") or {}, capabilities)
    new_tags = _tag_pairs(params)
    stack["status"] = "UPDATE_IN_PROGRESS"
    _emit_event(stack, name, "UPDATE_IN_PROGRESS", "User Initiated")
    try:
        params_ctx = _resolve_parameters(template, supplied)
        _apply_update(stack, template, params_ctx, stores, store)
        stack["parameters"] = params_ctx
        stack["template_body"] = raw_template
        stack["capabilities"] = sorted(capabilities)
        stack["description"] = str(template.get("Description", ""))[:1024]
        if new_tags:
            stack["tags"] = new_tags
        _apply_outputs(store, stack, template, stack.pop("_ctx"))
        stack["status"] = "UPDATE_COMPLETE"
        stack["last_updated_time"] = _now_iso()
        _emit_event(stack, name, "UPDATE_COMPLETE")
    except CfnError as e:
        stack["status_reason"] = e.message
        stack["status"] = "UPDATE_ROLLBACK_FAILED"
        _emit_event(stack, name, "UPDATE_ROLLBACK_FAILED", e.message)
        store.persist()
        raise
    store.persist()
    return _envelope("UpdateStack", _el("StackId", stack["stack_id"]))


def _continue_update_rollback(store, params, stores):
    stack = _require_stack(store, _p(params, "StackName"))
    if stack["status"] != "UPDATE_ROLLBACK_FAILED":
        raise CfnError("ValidationError",
                        f"Stack [{stack['stack_name']}] is in {stack['status']} state and can not be rolled back.", 400)
    stack["status"] = "UPDATE_ROLLBACK_COMPLETE"
    _emit_event(stack, stack["stack_name"], "UPDATE_ROLLBACK_COMPLETE")
    store.persist()
    return _envelope("ContinueUpdateRollback")


def _update_termination_protection(store, params, stores):
    stack = _require_stack(store, _p(params, "StackName"))
    stack["termination_protection"] = _bool(params.get("EnableTerminationProtection"))
    store.persist()
    return _envelope("UpdateTerminationProtection", _el("StackId", stack["stack_id"]))


def _delete_stack(store, params, stores):
    name = _p(params, "StackName")
    stack_id = store.stack_names.get(name) or (name if name in store.stacks else None)
    if not stack_id:
        return _envelope("DeleteStack")
    stack = store.stacks[stack_id]
    if stack["status"] == "DELETE_COMPLETE":
        return _envelope("DeleteStack")
    if stack.get("termination_protection"):
        raise CfnError("ValidationError", f"Stack [{name}] cannot be deleted while TerminationProtection is enabled", 400)
    stack["status"] = "DELETE_IN_PROGRESS"
    _emit_event(stack, stack["stack_name"], "DELETE_IN_PROGRESS", "User Initiated")
    failures = []
    for logical_id, rec in list(stack["resources"].items()):
        prov = RESOURCE_TYPES.get(rec["ResourceType"])
        if not prov:
            continue
        try:
            prov["delete"](stores, rec["PhysicalResourceId"])
            _emit_event(stack, logical_id, "DELETE_COMPLETE", "", rec["ResourceType"], rec["PhysicalResourceId"])
            del stack["resources"][logical_id]
        except Exception as e:
            failures.append(logical_id)
            _emit_event(stack, logical_id, "DELETE_FAILED", str(e), rec["ResourceType"], rec["PhysicalResourceId"])
    if failures:
        stack["status"] = "DELETE_FAILED"
        stack["status_reason"] = f"Failed to delete: {', '.join(failures)}"
    else:
        stack["status"] = "DELETE_COMPLETE"
        stack["deletion_time"] = _now_iso()
        store.stack_names.pop(name, None)
        _emit_event(stack, stack["stack_name"], "DELETE_COMPLETE")
    store.persist()
    return _envelope("DeleteStack")


# ── describe / list ──────────────────────────────────────────────────────────
def _stack_xml(stack, detail=True):
    parts = [_el("StackId", stack["stack_id"]), _el("StackName", stack["stack_name"]),
             _el("StackStatus", stack["status"]), _el("CreationTime", stack["creation_time"]),
             _el("LastUpdatedTime", stack["last_updated_time"]),
             _el("StackStatusReason", stack.get("status_reason")),
             _el("Description", stack.get("description")),
             _el("DeletionTime", stack.get("deletion_time")),
             _el("EnableTerminationProtection", "true" if stack["termination_protection"] else "false"),
             _el("DisableRollback", "true" if stack["disable_rollback"] else "false"),
             _el("RoleARN", stack.get("role_arn"))]
    parts.append("<Tags>" + "".join("<member>" + _el("Key", k) + _el("Value", v) + "</member>"
                                     for k, v in stack.get("tags", {}).items()) + "</Tags>")
    parts.append("<Capabilities>" + "".join(_el("member", c) for c in stack.get("capabilities", [])) + "</Capabilities>")
    if detail:
        parts.append("<Outputs>" + "".join(
            "<member>" + _el("OutputKey", o["OutputKey"]) + _el("OutputValue", o["OutputValue"]) +
            _el("Description", o.get("Description")) +
            (_el("ExportName", o["ExportName"]) if o.get("ExportName") else "") + "</member>"
            for o in stack.get("outputs", [])) + "</Outputs>")
        parts.append("<Parameters>" + "".join(
            "<member>" + _el("ParameterKey", k) + _el("ParameterValue", v) + "</member>"
            for k, v in stack.get("parameters", {}).items()) + "</Parameters>")
        parts.append("<DriftInformation><StackDriftStatus>" + _xe(stack.get("drift_status", "NOT_CHECKED")) +
                     "</StackDriftStatus>" +
                     (_el("LastCheckTimestamp", stack["drift_checked_time"]) if stack.get("drift_checked_time") else "") +
                     "</DriftInformation>")
    return "".join(parts)


def _describe_stacks(store, params, stores):
    name = _p(params, "StackName")
    if name:
        stack = _require_stack(store, name)
        body = "<Stacks><member>" + _stack_xml(stack) + "</member></Stacks>"
    else:
        active = [s for s in store.stacks.values() if s["status"] not in TERMINAL_DELETED]
        body = "<Stacks>" + "".join("<member>" + _stack_xml(s) + "</member>" for s in active) + "</Stacks>"
    return _envelope("DescribeStacks", body)


def _list_stacks(store, params, stores):
    filt = set(_members(params, "StackStatusFilter"))
    items = [s for s in store.stacks.values() if not filt or s["status"] in filt]
    items.sort(key=lambda s: s["creation_time"], reverse=True)
    body = "<StackSummaries>" + "".join(
        "<member>" + _el("StackId", s["stack_id"]) + _el("StackName", s["stack_name"]) +
        _el("StackStatus", s["status"]) + _el("CreationTime", s["creation_time"]) +
        _el("LastUpdatedTime", s["last_updated_time"]) + _el("TemplateDescription", s.get("description")) +
        _el("DeletionTime", s.get("deletion_time")) + _el("StackStatusReason", s.get("status_reason")) +
        _el("EnableTerminationProtection", "true" if s["termination_protection"] else "false") +
        "<DriftInformation><StackDriftStatus>" + _xe(s.get("drift_status", "NOT_CHECKED")) + "</StackDriftStatus></DriftInformation>" +
        "</member>" for s in items) + "</StackSummaries>"
    return _envelope("ListStacks", body)


def _get_template(store, params, stores):
    stack = _require_stack(store, _p(params, "StackName"))
    return _envelope("GetTemplate", _el("TemplateBody", stack["template_body"]))


def _describe_stack_events(store, params, stores):
    stack = _require_stack(store, _p(params, "StackName"))
    body = "<StackEvents>" + "".join(
        "<member>" + _el("StackId", e["StackId"]) + _el("EventId", e["EventId"]) + _el("StackName", e["StackName"]) +
        _el("LogicalResourceId", e["LogicalResourceId"]) + _el("PhysicalResourceId", e["PhysicalResourceId"]) +
        _el("ResourceType", e["ResourceType"]) + _el("Timestamp", e["Timestamp"]) +
        _el("ResourceStatus", e["ResourceStatus"]) + _el("ResourceStatusReason", e.get("ResourceStatusReason")) +
        "</member>" for e in stack["events"]) + "</StackEvents>"
    return _envelope("DescribeStackEvents", body)


def _stack_resource_inner(stack, r):
    return (_el("StackId", stack["stack_id"]) + _el("StackName", stack["stack_name"]) +
            _el("LogicalResourceId", r["LogicalResourceId"]) + _el("PhysicalResourceId", r["PhysicalResourceId"]) +
            _el("ResourceType", r["ResourceType"]) + _el("Timestamp", stack["last_updated_time"]) +
            _el("ResourceStatus", r["ResourceStatus"]) + _el("ResourceStatusReason", r.get("ResourceStatusReason")) +
            "<DriftInformation><StackResourceDriftStatus>" + _xe(r.get("DriftStatus", "NOT_CHECKED")) +
            "</StackResourceDriftStatus></DriftInformation>")


def _describe_stack_resources(store, params, stores):
    stack = _require_stack(store, _p(params, "StackName"))
    lid = _p(params, "LogicalResourceId")
    recs = list(stack["resources"].values())
    if lid:
        recs = [r for r in recs if r["LogicalResourceId"] == lid]
    body = "<StackResources>" + "".join(
        "<member>" + _stack_resource_inner(stack, r) + "</member>" for r in recs) + "</StackResources>"
    return _envelope("DescribeStackResources", body)


def _describe_stack_resource(store, params, stores):
    stack = _require_stack(store, _p(params, "StackName"))
    lid = _p(params, "LogicalResourceId")
    rec = stack["resources"].get(lid)
    if not rec:
        raise CfnError("ValidationError", f"Resource {lid} does not exist for stack {stack['stack_name']}", 400)
    body = "<StackResourceDetail>" + _stack_resource_inner(stack, rec) + "</StackResourceDetail>"
    return _envelope("DescribeStackResource", body)


def _list_stack_resources(store, params, stores):
    stack = _require_stack(store, _p(params, "StackName"))
    body = "<StackResourceSummaries>" + "".join(
        "<member>" + _el("LogicalResourceId", r["LogicalResourceId"]) + _el("PhysicalResourceId", r["PhysicalResourceId"]) +
        _el("ResourceType", r["ResourceType"]) + _el("LastUpdatedTimestamp", stack["last_updated_time"]) +
        _el("ResourceStatus", r["ResourceStatus"]) + _el("ResourceStatusReason", r.get("ResourceStatusReason")) +
        "<DriftInformation><StackResourceDriftStatus>" + _xe(r.get("DriftStatus", "NOT_CHECKED")) +
        "</StackResourceDriftStatus></DriftInformation></member>" for r in stack["resources"].values()
    ) + "</StackResourceSummaries>"
    return _envelope("ListStackResources", body)


def _list_exports(store, params, stores):
    pairs = [(s, o) for s in store.stacks.values() if s["status"] not in TERMINAL_DELETED
             for o in s.get("outputs", []) if o.get("ExportName")]
    body = "<Exports>" + "".join(
        "<member>" + _el("ExportingStackId", s["stack_id"]) + _el("Name", o["ExportName"]) +
        _el("Value", o["OutputValue"]) + "</member>" for s, o in pairs) + "</Exports>"
    return _envelope("ListExports", body)


def _validate_template(store, params, stores):
    raw = _template_body(params, stores)
    template = _parse_template(raw)
    resources = template.get("Resources")
    if not isinstance(resources, dict) or not resources:
        raise CfnError("ValidationError", "Template format error: At least one Resources member must be defined.", 400)
    unsupported = sorted({r.get("Type") for r in resources.values() if r.get("Type") not in RESOURCE_TYPES})
    if unsupported:
        raise CfnError("ValidationError",
                        "Template format error: Unsupported resource type(s): " + ", ".join(unsupported) +
                        ". Vyomi's CloudFormation simulation supports: " + ", ".join(sorted(RESOURCE_TYPES)), 400)
    parts = ["<Parameters>" + "".join(
        "<member>" + _el("ParameterKey", k) + _el("DefaultValue", v.get("Default")) +
        _el("NoEcho", "true" if v.get("NoEcho") else "false") + _el("Description", v.get("Description")) +
        "</member>" for k, v in (template.get("Parameters") or {}).items()) + "</Parameters>"]
    parts.append(_el("Description", template.get("Description")))
    iam_types = sorted({r["Type"] for r in resources.values() if str(r.get("Type", "")).startswith("AWS::IAM::")})
    if iam_types:
        parts.append("<Capabilities><member>CAPABILITY_IAM</member></Capabilities>" +
                      _el("CapabilitiesReason", f"The following resource(s) require capabilities: {iam_types}"))
    return _envelope("ValidateTemplate", "".join(parts))


# ── change sets ──────────────────────────────────────────────────────────────
def _diff_resources(current, proposed_def, ctx):
    changes = []
    cur_ids, prop_ids = set(current), set(proposed_def)
    for lid in sorted(prop_ids - cur_ids):
        changes.append({"ResourceChange": {"Action": "Add", "LogicalResourceId": lid,
                        "ResourceType": proposed_def[lid].get("Type", "")}})
    for lid in sorted(cur_ids - prop_ids):
        changes.append({"ResourceChange": {"Action": "Remove", "LogicalResourceId": lid,
                        "ResourceType": current[lid]["ResourceType"],
                        "PhysicalResourceId": current[lid]["PhysicalResourceId"]}})
    for lid in sorted(cur_ids & prop_ids):
        try:
            new_props = _resolve(proposed_def[lid].get("Properties") or {}, ctx)
        except CfnError:
            new_props = None
        same_type = current[lid]["ResourceType"] == proposed_def[lid].get("Type")
        if not same_type or json.dumps(new_props, sort_keys=True, default=str) != \
                json.dumps(current[lid].get("Properties") or {}, sort_keys=True, default=str):
            changes.append({"ResourceChange": {
                "Action": "Modify", "LogicalResourceId": lid, "ResourceType": proposed_def[lid].get("Type", ""),
                "PhysicalResourceId": current[lid]["PhysicalResourceId"],
                "Replacement": "False" if same_type else "True"}})
    return changes


def _change_xml(c):
    rc = c["ResourceChange"]
    inner = (_el("Action", rc["Action"]) + _el("LogicalResourceId", rc["LogicalResourceId"]) +
             _el("ResourceType", rc["ResourceType"]) + _el("PhysicalResourceId", rc.get("PhysicalResourceId")) +
             _el("Replacement", rc.get("Replacement")))
    return "<member><Type>Resource</Type><ResourceChange>" + inner + "</ResourceChange></member>"


def _create_change_set(store, params, stores):
    name = _p(params, "StackName")
    cs_name = _p(params, "ChangeSetName")
    if not cs_name:
        raise CfnError("ValidationError", "ChangeSetName is required", 400)
    cs_type = _p(params, "ChangeSetType", "UPDATE" if name in store.stack_names else "CREATE")
    stack_id = store.stack_names.get(name)
    raw_template = None
    if params.get("TemplateBody") or params.get("TemplateURL"):
        raw_template = _template_body(params, stores)
    if cs_type == "CREATE":
        if stack_id:
            raise CfnError("ValidationError", f"Stack [{name}] already exists", 400)
        stack_uid = uuid.uuid4().hex
        stack_id = _stack_arn(name, stack_uid)
        stack = _new_stack_record(stack_id, name, stack_uid)
        stack["status"] = "REVIEW_IN_PROGRESS"
        store.stacks[stack_id] = stack
        store.stack_names[name] = stack_id
    else:
        if not stack_id:
            raise CfnError("ValidationError", f"Stack [{name}] does not exist", 400)
        stack = store.stacks[stack_id]
        if raw_template is None:
            raw_template = stack["template_body"]
    template = _parse_template(raw_template)
    supplied = _param_pairs(params)
    if cs_type != "CREATE":
        for k, v in stack.get("parameters", {}).items():
            supplied.setdefault(k, v)
    try:
        params_ctx = _resolve_parameters(template, supplied)
        conditions = _eval_conditions(template, params_ctx)
    except CfnError:
        params_ctx, conditions = {}, {}
    ctx = _build_ctx(stack, template, params_ctx, store)
    ctx["conditions"] = conditions
    changes = _diff_resources(stack["resources"], template.get("Resources") or {}, ctx)
    cs_id = f"{stack_id}/changeset/{cs_name}/{uuid.uuid4().hex}"
    cs = {"ChangeSetId": cs_id, "ChangeSetName": cs_name, "StackId": stack_id, "StackName": name,
          "Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE" if changes else "UNAVAILABLE",
          "Changes": changes, "CreationTime": _now_iso(), "Description": _p(params, "Description"),
          "ChangeSetType": cs_type, "template_body": raw_template, "parameters": supplied,
          "capabilities": sorted(_members(params, "Capabilities")), "tags": _tag_pairs(params),
          "StatusReason": "" if changes else "The submitted information didn't contain changes."}
    store.change_sets[cs_id] = cs
    store.persist()
    return _envelope("CreateChangeSet", _el("Id", cs_id) + _el("StackId", stack_id))


def _find_change_set(store, params):
    csid = _p(params, "ChangeSetName")
    stack_name = _p(params, "StackName")
    if csid in store.change_sets:
        return store.change_sets[csid]
    for cs in store.change_sets.values():
        if cs["ChangeSetName"] == csid and (not stack_name or cs["StackName"] == stack_name):
            return cs
    raise CfnError("ChangeSetNotFoundException", f"ChangeSet [{csid}] does not exist", 400)


def _describe_change_set(store, params, stores):
    cs = _find_change_set(store, params)
    body = (_el("ChangeSetId", cs["ChangeSetId"]) + _el("ChangeSetName", cs["ChangeSetName"]) +
            _el("StackId", cs["StackId"]) + _el("StackName", cs["StackName"]) +
            _el("Status", cs["Status"]) + _el("ExecutionStatus", cs["ExecutionStatus"]) +
            _el("StatusReason", cs.get("StatusReason")) + _el("CreationTime", cs["CreationTime"]) +
            _el("Description", cs.get("Description")) +
            "<Changes>" + "".join(_change_xml(c) for c in cs["Changes"]) + "</Changes>")
    return _envelope("DescribeChangeSet", body)


def _list_change_sets(store, params, stores):
    stack = _require_stack(store, _p(params, "StackName"))
    items = [cs for cs in store.change_sets.values() if cs["StackId"] == stack["stack_id"]]
    body = "<Summaries>" + "".join(
        "<member>" + _el("ChangeSetId", cs["ChangeSetId"]) + _el("ChangeSetName", cs["ChangeSetName"]) +
        _el("StackId", cs["StackId"]) + _el("StackName", cs["StackName"]) + _el("Status", cs["Status"]) +
        _el("ExecutionStatus", cs["ExecutionStatus"]) + _el("CreationTime", cs["CreationTime"]) +
        _el("Description", cs.get("Description")) + "</member>" for cs in items) + "</Summaries>"
    return _envelope("ListChangeSets", body)


def _delete_change_set(store, params, stores):
    cs = _find_change_set(store, params)
    store.change_sets.pop(cs["ChangeSetId"], None)
    if cs["ChangeSetType"] == "CREATE" and cs["ExecutionStatus"] != "EXECUTE_COMPLETE":
        stack = store.stacks.get(cs["StackId"])
        if stack and stack["status"] == "REVIEW_IN_PROGRESS":
            del store.stacks[cs["StackId"]]
            store.stack_names.pop(stack["stack_name"], None)
    store.persist()
    return _envelope("DeleteChangeSet")


def _execute_change_set(store, params, stores):
    cs = _find_change_set(store, params)
    if cs["ExecutionStatus"] != "AVAILABLE":
        raise CfnError("InvalidChangeSetStatus",
                        f"ChangeSet [{cs['ChangeSetId']}] cannot be executed in its current status of "
                        f"[{cs['ExecutionStatus']}]", 400)
    stack = store.stacks[cs["StackId"]]
    template = _parse_template(cs["template_body"])
    supplied = cs["parameters"]
    capabilities = set(cs["capabilities"])
    _check_capabilities(template.get("Resources") or {}, capabilities)
    stack["template_body"] = cs["template_body"]
    if cs["tags"]:
        stack["tags"] = cs["tags"]
    try:
        params_ctx = _resolve_parameters(template, supplied)
        stack["parameters"] = params_ctx
        stack["description"] = str(template.get("Description", ""))[:1024]
        if cs["ChangeSetType"] == "CREATE":
            stack["status"] = "CREATE_IN_PROGRESS"
            _emit_event(stack, stack["stack_name"], "CREATE_IN_PROGRESS", "User Initiated")
            _apply_resources(stack, template, params_ctx, stores, store)
            _apply_outputs(store, stack, template, stack.pop("_ctx"))
            stack["status"] = "CREATE_COMPLETE"
            _emit_event(stack, stack["stack_name"], "CREATE_COMPLETE")
        else:
            stack["status"] = "UPDATE_IN_PROGRESS"
            _emit_event(stack, stack["stack_name"], "UPDATE_IN_PROGRESS", "User Initiated")
            _apply_update(stack, template, params_ctx, stores, store)
            _apply_outputs(store, stack, template, stack.pop("_ctx"))
            stack["status"] = "UPDATE_COMPLETE"
            stack["last_updated_time"] = _now_iso()
            _emit_event(stack, stack["stack_name"], "UPDATE_COMPLETE")
        stack["capabilities"] = sorted(capabilities)
    except CfnError as e:
        stack["status_reason"] = e.message
        if cs["ChangeSetType"] == "CREATE":
            _emit_event(stack, stack["stack_name"], "ROLLBACK_IN_PROGRESS", e.message)
            _rollback_resources(stack, stores)
            stack["status"] = "ROLLBACK_COMPLETE"
            _emit_event(stack, stack["stack_name"], "ROLLBACK_COMPLETE")
        else:
            stack["status"] = "UPDATE_ROLLBACK_FAILED"
            _emit_event(stack, stack["stack_name"], "UPDATE_ROLLBACK_FAILED", e.message)
        cs["ExecutionStatus"] = "EXECUTE_FAILED"
        store.persist()
        return _envelope("ExecuteChangeSet")
    cs["ExecutionStatus"] = "EXECUTE_COMPLETE"
    store.persist()
    return _envelope("ExecuteChangeSet")


# ── drift ─────────────────────────────────────────────────────────────────
def _property_diffs(expected: dict, actual: dict) -> list:
    diffs = []
    for key in sorted(set(expected) | set(actual)):
        e, a = expected.get(key), actual.get(key)
        if json.dumps(e, sort_keys=True, default=str) != json.dumps(a, sort_keys=True, default=str):
            diffs.append({"PropertyPath": f"/{key}", "ExpectedValue": e, "ActualValue": a})
    return diffs


def _drift_check_resource(stores, rec):
    """Existence drift for every provisioned type; PROPERTY drift too for any type whose
    provisioner registers a `read` (live-state) function — compared against the
    `PropertiesBaseline` snapshot taken right after the resource was created/updated, so a
    property changed out-of-band through the owning service's own console/API (DynamoDB
    billing mode, SNS display name, SQS visibility timeout, an IAM role's trust policy, a log
    group's retention) is reported as MODIFIED with concrete PropertyDifferences."""
    prov = RESOURCE_TYPES.get(rec["ResourceType"])
    if not prov:
        return "NOT_CHECKED", []
    try:
        if not prov["exists"](stores, rec["PhysicalResourceId"]):
            return "DELETED", []
        reader = prov.get("read")
        baseline = rec.get("PropertiesBaseline")
        if not reader or baseline is None:
            return "IN_SYNC", []
        live = reader(stores, rec["PhysicalResourceId"])
        if live is None:
            return "DELETED", []
        diffs = _property_diffs(baseline, live)
        return ("MODIFIED", diffs) if diffs else ("IN_SYNC", [])
    except Exception:
        return "NOT_CHECKED", []


def _detect_stack_drift(store, params, stores):
    stack = _require_stack(store, _p(params, "StackName"))
    any_drift = False
    for rec in stack["resources"].values():
        status, diffs = _drift_check_resource(stores, rec)
        rec["DriftStatus"] = status
        rec["PropertyDifferences"] = diffs
        if status not in ("IN_SYNC", "NOT_CHECKED"):
            any_drift = True
    stack["drift_status"] = "DRIFTED" if any_drift else "IN_SYNC"
    stack["drift_checked_time"] = _now_iso()
    detection_id = uuid.uuid4().hex
    store.drift_detections[detection_id] = {"StackId": stack["stack_id"], "Status": "DETECTION_COMPLETE",
                                            "StackDriftStatus": stack["drift_status"]}
    store.persist()
    return _envelope("DetectStackDrift", _el("StackDriftDetectionId", detection_id))


def _describe_drift_status(store, params, stores):
    detid = _p(params, "StackDriftDetectionId")
    d = store.drift_detections.get(detid)
    if not d:
        raise CfnError("ValidationError", f"DriftDetectionId {detid} does not exist", 400)
    body = (_el("StackId", d["StackId"]) + _el("StackDriftDetectionId", detid) +
            _el("StackDriftStatus", d["StackDriftStatus"]) + _el("DetectionStatus", d["Status"]))
    return _envelope("DescribeStackDriftDetectionStatus", body)


def _describe_resource_drifts(store, params, stores):
    stack = _require_stack(store, _p(params, "StackName"))

    def _diff_xml(d):
        return ("<member>" + _el("PropertyPath", d["PropertyPath"]) +
                _el("ExpectedValue", json.dumps(d["ExpectedValue"], default=str)) +
                _el("ActualValue", json.dumps(d["ActualValue"], default=str)) + "</member>")

    body = "<StackResourceDrifts>" + "".join(
        "<member>" + _el("StackId", stack["stack_id"]) + _el("LogicalResourceId", r["LogicalResourceId"]) +
        _el("PhysicalResourceId", r["PhysicalResourceId"]) + _el("ResourceType", r["ResourceType"]) +
        _el("StackResourceDriftStatus", r.get("DriftStatus", "NOT_CHECKED")) +
        "<PropertyDifferences>" + "".join(_diff_xml(d) for d in r.get("PropertyDifferences") or []) +
        "</PropertyDifferences></member>"
        for r in stack["resources"].values()) + "</StackResourceDrifts>"
    return _envelope("DescribeStackResourceDrifts", body)


# ── stack sets / refactors (control-plane shell — see module docstring) ─────
def _create_stack_set(store, params, stores):
    name = _p(params, "StackSetName")
    if not name:
        raise CfnError("ValidationError", "StackSetName is required", 400)
    if name in store.stack_sets:
        raise CfnError("NameAlreadyExistsException", f"StackSet {name} already exists", 400)
    raw_template = _template_body(params, stores)
    _parse_template(raw_template)
    ss_id = f"{name}:{uuid.uuid4()}"
    store.stack_sets[name] = {
        "StackSetId": ss_id, "StackSetName": name, "Description": _p(params, "Description"),
        "Status": "ACTIVE", "TemplateBody": raw_template, "Parameters": _param_pairs(params),
        "Tags": _tag_pairs(params), "PermissionModel": _p(params, "PermissionModel", "SELF_MANAGED"),
        "Capabilities": sorted(_members(params, "Capabilities"))}
    store.persist()
    return _envelope("CreateStackSet", _el("StackSetId", ss_id))


def _describe_stack_set(store, params, stores):
    ss = store.stack_sets.get(_p(params, "StackSetName"))
    if not ss:
        raise CfnError("StackSetNotFoundException", f"StackSet {_p(params, 'StackSetName')} not found", 400)
    body = ("<StackSet>" + _el("StackSetId", ss["StackSetId"]) + _el("StackSetName", ss["StackSetName"]) +
            _el("Description", ss["Description"]) + _el("Status", ss["Status"]) +
            _el("TemplateBody", ss["TemplateBody"]) + _el("PermissionModel", ss["PermissionModel"]) + "</StackSet>")
    return _envelope("DescribeStackSet", body)


def _list_stack_sets(store, params, stores):
    body = "<Summaries>" + "".join(
        "<member>" + _el("StackSetId", ss["StackSetId"]) + _el("StackSetName", ss["StackSetName"]) +
        _el("Description", ss["Description"]) + _el("Status", ss["Status"]) +
        _el("PermissionModel", ss["PermissionModel"]) + "</member>" for ss in store.stack_sets.values()) + "</Summaries>"
    return _envelope("ListStackSets", body)


def _delete_stack_set(store, params, stores):
    name = _p(params, "StackSetName")
    if store.stack_set_instances.get(name):
        raise CfnError("OperationInProgressException", f"StackSet {name} still has stack instances", 400)
    if store.stack_sets.pop(name, None) is None:
        raise CfnError("StackSetNotFoundException", f"StackSet {name} not found", 400)
    store.persist()
    return _envelope("DeleteStackSet")


def _list_stack_instances(store, params, stores):
    name = _p(params, "StackSetName")
    body = "<Summaries>" + "".join("<member></member>" for _ in store.stack_set_instances.get(name, [])) + "</Summaries>"
    return _envelope("ListStackInstances", body)


def _list_stack_refactors(store, params, stores):
    body = "<StackRefactorSummaries>" + "".join(
        "<member>" + _el("StackRefactorId", r["StackRefactorId"]) + _el("Status", r["Status"]) +
        _el("StatusReason", r.get("StatusReason")) + _el("ExecutionStatus", r.get("ExecutionStatus")) +
        _el("ExecutionStatusReason", r.get("ExecutionStatusReason")) + _el("Description", r.get("Description")) +
        "</member>"
        for r in store.stack_refactors.values()) + "</StackRefactorSummaries>"
    return _envelope("ListStackRefactors", body)


def _resource_mappings(params: dict) -> list:
    out, i = [], 1
    while f"ResourceMappings.member.{i}.Source.LogicalResourceId" in params:
        out.append({
            "source_stack": _p(params, f"ResourceMappings.member.{i}.Source.StackName"),
            "source_lid": _p(params, f"ResourceMappings.member.{i}.Source.LogicalResourceId"),
            "dest_stack": _p(params, f"ResourceMappings.member.{i}.Destination.StackName"),
            "dest_lid": _p(params, f"ResourceMappings.member.{i}.Destination.LogicalResourceId"),
        })
        i += 1
    return out


def _create_stack_refactor(store, params, stores):
    mappings = _resource_mappings(params)
    if not mappings:
        raise CfnError("ValidationError", "At least one resource mapping is required.", 400)
    stack_ids = []
    for m in mappings:
        src = _require_stack(store, m["source_stack"])
        dst = _require_stack(store, m["dest_stack"])
        if m["source_lid"] not in src["resources"]:
            raise CfnError("ValidationError",
                            f"Resource {m['source_lid']} not found in stack {m['source_stack']}", 400)
        for sid in (src["stack_id"], dst["stack_id"]):
            if sid not in stack_ids:
                stack_ids.append(sid)
    refactor_id = str(uuid.uuid4())
    store.stack_refactors[refactor_id] = {
        "StackRefactorId": refactor_id, "StackIds": stack_ids, "Description": _p(params, "Description"),
        "Status": "CREATE_COMPLETE", "StatusReason": "",
        "ExecutionStatus": "AVAILABLE", "ExecutionStatusReason": "",
        "ResourceMappings": mappings,
    }
    store.persist()
    return _envelope("CreateStackRefactor", _el("StackRefactorId", refactor_id))


def _describe_stack_refactor(store, params, stores):
    rid = _p(params, "StackRefactorId")
    r = store.stack_refactors.get(rid)
    if not r:
        raise CfnError("StackRefactorNotFoundException", f"Stack refactor {rid} not found", 400)
    ids = "".join(_el("member", sid) for sid in r["StackIds"])
    body = (_el("StackRefactorId", r["StackRefactorId"]) + f"<StackIds>{ids}</StackIds>" +
            _el("Description", r["Description"]) + _el("ExecutionStatus", r["ExecutionStatus"]) +
            _el("ExecutionStatusReason", r["ExecutionStatusReason"]) + _el("Status", r["Status"]) +
            _el("StatusReason", r["StatusReason"]))
    return _envelope("DescribeStackRefactor", body)


def _execute_stack_refactor(store, params, stores):
    rid = _p(params, "StackRefactorId")
    r = store.stack_refactors.get(rid)
    if not r:
        raise CfnError("StackRefactorNotFoundException", f"Stack refactor {rid} not found", 400)
    if r["ExecutionStatus"] != "AVAILABLE":
        raise CfnError("ValidationError",
                        f"Stack refactor {rid} is not available for execution (status: {r['ExecutionStatus']})", 400)
    for m in r["ResourceMappings"]:
        src = _require_stack(store, m["source_stack"])
        dst = _require_stack(store, m["dest_stack"])
        rec = src["resources"].pop(m["source_lid"], None)
        if rec is None:
            continue
        moved = dict(rec, LogicalResourceId=m["dest_lid"])
        dst["resources"][m["dest_lid"]] = moved
        _emit_event(src, m["source_lid"], "DELETE_COMPLETE",
                    f"Resource moved to stack {dst['stack_name']} by stack refactor {rid}",
                    rec["ResourceType"], rec["PhysicalResourceId"])
        _emit_event(dst, m["dest_lid"], "IMPORT_COMPLETE",
                    f"Resource moved from stack {src['stack_name']} by stack refactor {rid}",
                    rec["ResourceType"], rec["PhysicalResourceId"])
    r["ExecutionStatus"] = "EXECUTE_COMPLETE"
    store.persist()
    return _envelope("ExecuteStackRefactor")


# ── registry (extensions: the resource types this engine actually provisions) ──
_TYPE_DESCRIPTIONS = {
    "AWS::S3::Bucket": "An Amazon S3 bucket, provisioned through Vyomi's S3 engine.",
    "AWS::DynamoDB::Table": "A DynamoDB table, provisioned through Vyomi's DynamoDB engine.",
    "AWS::SNS::Topic": "An SNS topic, provisioned through Vyomi's SNS engine.",
    "AWS::SQS::Queue": "An SQS queue, provisioned through Vyomi's SQS engine.",
    "AWS::IAM::Role": "An IAM role, provisioned through Vyomi's IAM engine.",
    "AWS::Logs::LogGroup": "A CloudWatch Logs log group, provisioned through Vyomi's Logs engine.",
    "AWS::CloudFormation::WaitCondition": "A CloudFormation-internal signaling resource (no underlying infrastructure in real AWS either).",
    "AWS::CloudFormation::WaitConditionHandle": "A CloudFormation-internal signaling handle (no underlying infrastructure in real AWS either).",
}


def _type_arn(type_name: str) -> str:
    return f"arn:aws:cloudformation:{REGION}::type/resource/{type_name.replace('::', '-')}/00000001"


def _list_types(store, params, stores):
    visibility = _p(params, "Visibility", "PUBLIC")
    type_filter = _p(params, "Type", "RESOURCE")
    if type_filter != "RESOURCE" or visibility != "PUBLIC":
        return _envelope("ListTypes", "<TypeSummaries></TypeSummaries>")
    body = "<TypeSummaries>" + "".join(
        "<member>" + _el("Type", "RESOURCE") + _el("TypeName", t) + _el("DefaultVersionId", "00000001") +
        _el("TypeArn", _type_arn(t)) + _el("IsActivated", "true") + _el("LastUpdated", _now_iso()) +
        _el("Description", _TYPE_DESCRIPTIONS.get(t, f"{t} resource provider")) + "</member>"
        for t in sorted(RESOURCE_TYPES)) + "</TypeSummaries>"
    return _envelope("ListTypes", body)


def _describe_type(store, params, stores):
    type_name = _p(params, "TypeName")
    if type_name not in RESOURCE_TYPES:
        raise CfnError("TypeNotFoundException", f"Type {type_name} not found", 404)
    name_prop = RESOURCE_TYPES[type_name].get("name_prop")
    schema = json.dumps({
        "typeName": type_name,
        "description": _TYPE_DESCRIPTIONS.get(type_name, ""),
        "properties": {name_prop: {"type": "string"}} if name_prop else {},
        "additionalProperties": False,
    })
    body = (_el("Arn", _type_arn(type_name)) + _el("Type", "RESOURCE") + _el("TypeName", type_name) +
            _el("DefaultVersionId", "00000001") + _el("IsDefaultVersion", "true") +
            _el("Description", _TYPE_DESCRIPTIONS.get(type_name, "")) + _el("Schema", schema) +
            _el("ProvisioningType", "FULLY_MUTABLE") + _el("DeprecatedStatus", "LIVE") +
            _el("Visibility", "PUBLIC") + _el("LastUpdated", _now_iso()) + _el("TimeCreated", _now_iso()) +
            _el("IsActivated", "true"))
    return _envelope("DescribeType", body)


# ── dispatch ──────────────────────────────────────────────────────────────────
_ACTIONS = {
    "CreateStack": _create_stack, "UpdateStack": _update_stack, "DeleteStack": _delete_stack,
    "DescribeStacks": _describe_stacks, "ListStacks": _list_stacks,
    "ContinueUpdateRollback": _continue_update_rollback,
    "UpdateTerminationProtection": _update_termination_protection,
    "GetTemplate": _get_template, "DescribeStackEvents": _describe_stack_events,
    "DescribeStackResources": _describe_stack_resources, "DescribeStackResource": _describe_stack_resource,
    "ListStackResources": _list_stack_resources, "ListExports": _list_exports,
    "ValidateTemplate": _validate_template,
    "CreateChangeSet": _create_change_set, "DescribeChangeSet": _describe_change_set,
    "ExecuteChangeSet": _execute_change_set, "DeleteChangeSet": _delete_change_set,
    "ListChangeSets": _list_change_sets,
    "DetectStackDrift": _detect_stack_drift, "DescribeStackDriftDetectionStatus": _describe_drift_status,
    "DescribeStackResourceDrifts": _describe_resource_drifts,
    "CreateStackSet": _create_stack_set, "DescribeStackSet": _describe_stack_set,
    "ListStackSets": _list_stack_sets, "DeleteStackSet": _delete_stack_set,
    "ListStackInstances": _list_stack_instances, "ListStackRefactors": _list_stack_refactors,
    "CreateStackRefactor": _create_stack_refactor, "DescribeStackRefactor": _describe_stack_refactor,
    "ExecuteStackRefactor": _execute_stack_refactor,
    "ListTypes": _list_types, "DescribeType": _describe_type,
}


def dispatch(store: CloudFormationStore, params: dict | None = None,
             s3_store=None, ddb_store=None, iam_store=None, msg_store=None, logs_store=None) -> CfnResponse:
    params = params or {}
    action = str(params.get("Action", "")).strip()
    if not action:
        return _error("MissingAction", "The request must include an Action.", 400)
    fn = _ACTIONS.get(action)
    if fn is None:
        return _error("InvalidAction", f"The action {action} is not implemented.", 400)
    stores = {"s3": s3_store, "ddb": ddb_store, "iam": iam_store, "msg": msg_store, "logs": logs_store}
    try:
        return fn(store, params, stores)
    except CfnError as e:
        return _error(e.code, e.message, e.status)
