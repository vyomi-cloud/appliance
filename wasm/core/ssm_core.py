"""AWS Systems Manager (SSM) core — substrate-independent engine for the control
plane developers use most: Parameter Store, Documents, Run Command, State Manager
associations, Maintenance Windows and Patch Baselines (botocore `ssm`, 2014-11-06,
awsJson1.1, `X-Amz-Target: AmazonSSM.<Operation>`).

Speaks the native wire so an unmodified aws-sdk-java-v2 / aws-sdk-go-v2 / aws CLI
`ssm` client works with only the endpoint changed: PascalCase members, epoch-seconds
timestamps, `{"__type", "message"}` errors, MaxResults/NextToken pagination.

NO fastapi / boto3 / socket imports → loads under Pyodide (Nano) and on host CPython.
State lives on a plain store object (`SsmStore`, public dict attrs only) so
core/nano_persist captures it like every other store.

Simulation notes: SecureString values are kept in the store and returned as an opaque
`kms:<key>:<base64>` blob unless WithDecryption is set. Run Command has no SSM agent
behind it offline, so a command completes immediately as `Success` per instance.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field

REGION = "us-east-1"
ACCOUNT = "000000000000"
DEFAULT_KEY = "alias/aws/ssm"
_NAME_RE = re.compile(r"^[a-zA-Z0-9_.\-/]+$")
_DOC_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-.:/]{3,128}$")
_LABEL_RE = re.compile(r"^[a-zA-Z0-9_.\-]{1,100}$")
_TYPES = ("String", "StringList", "SecureString")


class SsmStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.parameters: dict = {}      # name -> {"versions": [...], "tags": {}, "policies": [...]}
        self.documents: dict = {}       # name -> document record (versions inside)
        self.commands: dict = {}        # command id -> command (invocations inside)
        self.associations: dict = {}
        self.windows: dict = {}         # window id -> window (targets inside)
        self.baselines: dict = {}
        self._seeded = False


_SHARED: SsmStore | None = None


def shared_store() -> SsmStore:
    """The appliance-wide store: the native wire and the console REST
    (/api/ssm/...) both read/write this one instance."""
    global _SHARED
    if _SHARED is None:
        _SHARED = SsmStore()
    return _SHARED


@dataclass
class SsmResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class SsmError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


def _now() -> float:
    return round(time.time(), 3)


def _req_id() -> str:
    return str(uuid.uuid4())


def _hex(n: int) -> str:
    return uuid.uuid4().hex[:n]


# ── helpers ────────────────────────────────────────────────────────────────
def _page(items: list, body: dict, key: str, default_max: int = 50, hard_max: int = 50) -> dict:
    """MaxResults / NextToken (offset token) pagination."""
    mx = body.get("MaxResults")
    if mx is not None and (not isinstance(mx, int) or mx < 1 or mx > hard_max):
        raise SsmError("ValidationException", f"1 validation error detected: Value '{mx}' at 'maxResults' failed to satisfy constraint: Member must have value less than or equal to {hard_max}")
    mx = mx or default_max
    try:
        start = int(base64.b64decode(body["NextToken"]).decode()) if body.get("NextToken") else 0
    except Exception:
        raise SsmError("InvalidNextToken", "The specified token is not valid.")
    chunk = items[start:start + mx]
    out = {key: chunk}
    if start + mx < len(items):
        out["NextToken"] = base64.b64encode(str(start + mx).encode()).decode()
    return out


def _tags_in(tags) -> dict:
    out = {}
    for t in tags or []:
        k = str((t or {}).get("Key") or "")
        if not k:
            raise SsmError("ValidationException", "Tag key must not be empty.")
        out[k] = str((t or {}).get("Value") or "")
    return out


def _tag_list(tags: dict) -> list:
    return [{"Key": k, "Value": v} for k, v in sorted((tags or {}).items())]


def _need(body: dict, *names: str) -> None:
    missing = [n for n in names if body.get(n) in (None, "")]
    if missing:
        raise SsmError("ValidationException", f"1 validation error detected: Value null at '{missing[0][0].lower() + missing[0][1:]}' failed to satisfy constraint: Member must not be null")


# ═══════════════════════════════════════════════════════════════════════════
# Parameter Store
# ═══════════════════════════════════════════════════════════════════════════
def _param_arn(name: str) -> str:
    return f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter{name if name.startswith('/') else '/' + name}"


def _norm_name(name: str) -> str:
    """Parameter names are stored as given; ARNs resolve to the name."""
    name = str(name or "")
    if name.startswith("arn:aws:ssm:") and ":parameter" in name:
        name = name.split(":parameter", 1)[1]
    return name


def _validate_name(name: str) -> None:
    if not name:
        raise SsmError("ValidationException", "1 validation error detected: Value '' at 'name' failed to satisfy constraint: Member must have length greater than or equal to 1")
    if len(name) > 2048 or not _NAME_RE.match(name):
        raise SsmError("ValidationException", "Parameter name: can't be empty or longer than 2048 characters and may contain only a-zA-Z0-9_.-/")
    low = name.lstrip("/").lower()
    if low.startswith(("aws", "ssm")):
        raise SsmError("ValidationException", 'Parameter name: can\'t be prefixed with "ssm" or "aws" (case-insensitive).')
    if name.startswith("/") and name.count("/") > 15:
        raise SsmError("ValidationException", "Parameter hierarchy can have a maximum of 15 levels.")


def _current(rec: dict) -> dict:
    return rec["versions"][-1]


def _parse_selector(name: str) -> tuple[str, str | None]:
    """`/a/b:3` or `/a/b:label` → (name, selector)."""
    name = _norm_name(name)
    if ":" in name:
        base, sel = name.rsplit(":", 1)
        return base, sel
    return name, None


def _get_version(store: SsmStore, raw_name: str) -> tuple[str, dict, dict]:
    name, sel = _parse_selector(raw_name)
    rec = store.parameters.get(name)
    if not rec:
        raise SsmError("ParameterNotFound", f"Parameter {name} not found.")
    if sel is None:
        return name, rec, _current(rec)
    if sel.isdigit():
        for v in rec["versions"]:
            if v["version"] == int(sel):
                return name, rec, v
    else:
        for v in rec["versions"]:
            if sel in v.get("labels", []):
                return name, rec, v
    raise SsmError("ParameterVersionNotFound", f"Systems Manager could not find version {sel} of {name}. Verify the version and try again.")


def _value_out(v: dict, decrypt: bool) -> str:
    if v["type"] == "SecureString" and not decrypt:
        return f"kms:{v.get('key_id') or DEFAULT_KEY}:" + base64.b64encode(v["value"].encode()).decode()
    return v["value"]


def _parameter(name: str, v: dict, decrypt: bool, sel: str | None = None) -> dict:
    out = {"Name": name, "Type": v["type"], "Value": _value_out(v, decrypt), "Version": v["version"],
           "LastModifiedDate": v["last_modified"], "ARN": _param_arn(name), "DataType": v.get("data_type", "text")}
    if sel:
        out["Selector"] = ":" + sel
    return out


def _put_parameter(store: SsmStore, b: dict) -> dict:
    _need(b, "Name", "Value")
    name = _norm_name(b["Name"])
    _validate_name(name)
    overwrite = bool(b.get("Overwrite"))
    value = b["Value"]
    if not isinstance(value, str):
        raise SsmError("ValidationException", "Value must be a string.")
    rec = store.parameters.get(name)
    ptype = b.get("Type")
    if ptype is not None and ptype not in _TYPES:
        raise SsmError("ValidationException", f"1 validation error detected: Value '{ptype}' at 'type' failed to satisfy constraint: Member must satisfy enum value set: [String, StringList, SecureString]")
    if b.get("Tags") and overwrite:
        raise SsmError("InvalidParameters", "Invalid request: tags and overwrite can't be used together. To create a parameter with tags, please remove overwrite. To update tags for an existing parameter, please use AddTagsToResource.")
    if rec and not overwrite:
        raise SsmError("ParameterAlreadyExists", "The parameter already exists. To overwrite this value, set the overwrite option in the request to true.")
    if not rec and not ptype:
        raise SsmError("ValidationException", "A parameter type is required when you create a parameter. Specify String, StringList or SecureString.")
    prev = _current(rec) if rec else {}
    ptype = ptype or prev.get("type", "String")
    if rec and ptype != prev["type"]:
        raise SsmError("InvalidParameters", "Invalid request: you can't change the type of an existing parameter.")
    tier = b.get("Tier") or prev.get("tier") or "Standard"
    if tier not in ("Standard", "Advanced", "Intelligent-Tiering"):
        raise SsmError("ValidationException", f"1 validation error detected: Value '{tier}' at 'tier' failed to satisfy constraint: Member must satisfy enum value set: [Standard, Advanced, Intelligent-Tiering]")
    limit = 8192 if tier == "Advanced" else 4096
    if tier == "Intelligent-Tiering":
        tier = "Advanced" if len(value) > 4096 or b.get("Policies") else "Standard"
        limit = 8192
    if prev.get("tier") == "Advanced" and tier == "Standard":
        tier = "Advanced"   # advanced parameters can't be downgraded
        limit = 8192
    if len(value) > limit:
        raise SsmError("ValidationException",
                       f"Standard tier parameters support values up to 4096 characters. This parameter is {len(value)} characters long. To store larger values, use the advanced-parameter tier."
                       if limit == 4096 else f"Advanced tier parameters support values up to 8192 characters. This parameter is {len(value)} characters long.")
    pattern = b.get("AllowedPattern", prev.get("allowed_pattern", ""))
    if pattern:
        try:
            ok = re.fullmatch(pattern, value) is not None
        except re.error:
            raise SsmError("InvalidAllowedPatternException", "The request does not meet the regular expression requirement.")
        if not ok:
            raise SsmError("ParameterPatternMismatchException", f"Parameter value, '{value}', does not match pattern '{pattern}'.")
    dtype = b.get("DataType") or prev.get("data_type") or "text"
    if dtype not in ("text", "aws:ec2:image", "aws:ssm:integration"):
        raise SsmError("ValidationException", f"The following data type is not supported: {dtype} (Data type names are all lowercase.)")
    version = (prev.get("version", 0)) + 1
    labels = []
    entry = {"version": version, "value": value, "type": ptype,
             "key_id": (b.get("KeyId") or prev.get("key_id") or DEFAULT_KEY) if ptype == "SecureString" else "",
             "description": b.get("Description", prev.get("description", "")) or "",
             "allowed_pattern": pattern or "", "tier": tier, "data_type": dtype,
             "last_modified": _now(), "last_modified_user": f"arn:aws:iam::{ACCOUNT}:root", "labels": labels}
    if not rec:
        rec = store.parameters[name] = {"versions": [], "tags": _tags_in(b.get("Tags")), "policies": []}
    if b.get("Policies"):
        try:
            rec["policies"] = json.loads(b["Policies"])
        except Exception:
            raise SsmError("InvalidPolicyDocument", "The content for the policy is not valid.")
    rec["versions"].append(entry)
    if len(rec["versions"]) > 100:   # real Parameter Store keeps the latest 100 versions
        rec["versions"] = rec["versions"][-100:]
    return {"Version": version, "Tier": tier}


def _get_parameter(store: SsmStore, b: dict) -> dict:
    _need(b, "Name")
    name, _rec, v = _get_version(store, b["Name"])
    sel = _parse_selector(b["Name"])[1]
    return {"Parameter": _parameter(name, v, bool(b.get("WithDecryption")), sel)}


def _get_parameters(store: SsmStore, b: dict) -> dict:
    names = b.get("Names")
    if not names:
        _need(b, "Names")
    if len(names) > 10:
        raise SsmError("ValidationException", f"1 validation error detected: Value '{names}' at 'names' failed to satisfy constraint: Member must have length less than or equal to 10")
    found, invalid = [], []
    for n in names:
        try:
            name, _r, v = _get_version(store, n)
            found.append(_parameter(name, v, bool(b.get("WithDecryption")), _parse_selector(n)[1]))
        except SsmError:
            invalid.append(n)
    return {"Parameters": found, "InvalidParameters": invalid}


def _in_path(name: str, path: str, recursive: bool) -> bool:
    if path == "/":
        return name.startswith("/") and (recursive or name.count("/") == 1)
    pfx = path.rstrip("/") + "/"
    if not name.startswith(pfx):
        return False
    return recursive or "/" not in name[len(pfx):]


def _filter_match(name: str, rec: dict, f: dict) -> bool:
    key, opt, vals = f.get("Key"), f.get("Option") or "Equals", [str(x) for x in f.get("Values") or []]
    cur = _current(rec)
    if key == "Name":
        return any((name.lstrip("/") == v.lstrip("/")) if opt == "Equals" else
                   (name.lstrip("/").startswith(v.lstrip("/")) if opt == "BeginsWith" else v in name) for v in vals)
    if key == "Type":
        return cur["type"] in vals
    if key == "KeyId":
        return cur.get("key_id") in vals
    if key == "Tier":
        return cur["tier"] in vals
    if key == "DataType":
        return cur.get("data_type", "text") in vals
    if key == "Label":
        return any(set(vals) & set(v.get("labels", [])) for v in rec["versions"])
    if key == "Path":
        return any(_in_path(name, v, opt == "Recursive") for v in vals)
    if key and key.startswith("tag:"):
        return rec["tags"].get(key[4:]) in vals
    if key == "Version":
        return str(cur["version"]) in vals
    return True


def _get_by_path(store: SsmStore, b: dict) -> dict:
    _need(b, "Path")
    path = b["Path"]
    if not path.startswith("/") or not _NAME_RE.match(path):
        raise SsmError("ValidationException", f"The parameter doesn't meet the parameter name requirements. The parameter name must begin with a forward slash \"/\". It can't be prefixed with \"aws\" or \"ssm\" (case-insensitive). It must use only letters, numbers, or the following symbols: . (period), - (hyphen), _ (underscore). Special characters are not allowed. All sub-paths, if specified, must use the forward slash symbol \"/\". Valid example: /get/parameters2-/by1./path0_.")
    recursive = bool(b.get("Recursive"))
    filters = b.get("ParameterFilters") or []
    names = sorted(n for n, r in store.parameters.items()
                   if _in_path(n, path, recursive) and all(_filter_match(n, r, f) for f in filters))
    dec = bool(b.get("WithDecryption"))
    items = [_parameter(n, _current(store.parameters[n]), dec) for n in names]
    return _page(items, b, "Parameters", default_max=10, hard_max=10)


def _metadata(name: str, rec: dict) -> dict:
    v = _current(rec)
    out = {"Name": name, "ARN": _param_arn(name), "Type": v["type"], "LastModifiedDate": v["last_modified"],
           "LastModifiedUser": v["last_modified_user"], "Version": v["version"], "Tier": v["tier"],
           "Policies": [{"PolicyText": json.dumps(p), "PolicyType": p.get("Type", "Expiration"), "PolicyStatus": "Pending"}
                        for p in rec.get("policies") or []],
           "DataType": v.get("data_type", "text")}
    if v.get("description"):
        out["Description"] = v["description"]
    if v.get("allowed_pattern"):
        out["AllowedPattern"] = v["allowed_pattern"]
    if v["type"] == "SecureString":
        out["KeyId"] = v.get("key_id") or DEFAULT_KEY
    return out


def _describe_parameters(store: SsmStore, b: dict) -> dict:
    flt = list(b.get("ParameterFilters") or [])
    for f in b.get("Filters") or []:   # legacy equality filters
        flt.append({"Key": f.get("Key"), "Option": "Equals", "Values": f.get("Values")})
    names = sorted(n for n, r in store.parameters.items() if all(_filter_match(n, r, f) for f in flt))
    return _page([_metadata(n, store.parameters[n]) for n in names], b, "Parameters", 10, 50)


def _delete_parameter(store: SsmStore, b: dict) -> dict:
    _need(b, "Name")
    name = _norm_name(b["Name"])
    if name not in store.parameters:
        raise SsmError("ParameterNotFound", f"Parameter {name} not found.")
    del store.parameters[name]
    return {}


def _delete_parameters(store: SsmStore, b: dict) -> dict:
    if not b.get("Names"):
        _need(b, "Names")
    if len(b["Names"]) > 10:
        raise SsmError("ValidationException", "1 validation error detected: Value at 'names' failed to satisfy constraint: Member must have length less than or equal to 10")
    deleted, invalid = [], []
    for n in b["Names"]:
        n = _norm_name(n)
        if n in store.parameters:
            del store.parameters[n]
            deleted.append(n)
        else:
            invalid.append(n)
    return {"DeletedParameters": deleted, "InvalidParameters": invalid}


def _parameter_history(store: SsmStore, b: dict) -> dict:
    _need(b, "Name")
    name = _norm_name(b["Name"])
    rec = store.parameters.get(name)
    if not rec:
        raise SsmError("ParameterNotFound", f"Parameter {name} not found.")
    dec = bool(b.get("WithDecryption"))
    items = []
    for v in rec["versions"]:
        h = {"Name": name, "Type": v["type"], "LastModifiedDate": v["last_modified"], "LastModifiedUser": v["last_modified_user"],
             "Value": _value_out(v, dec), "Version": v["version"], "Labels": list(v.get("labels", [])), "Tier": v["tier"],
             "Policies": [], "DataType": v.get("data_type", "text")}
        if v.get("description"):
            h["Description"] = v["description"]
        if v.get("allowed_pattern"):
            h["AllowedPattern"] = v["allowed_pattern"]
        if v["type"] == "SecureString":
            h["KeyId"] = v.get("key_id") or DEFAULT_KEY
        items.append(h)
    return _page(items, b, "Parameters", 50, 50)


def _label_version(store: SsmStore, b: dict) -> dict:
    _need(b, "Name", "Labels")
    name = _norm_name(b["Name"])
    rec = store.parameters.get(name)
    if not rec:
        raise SsmError("ParameterNotFound", f"Parameter {name} not found.")
    if len(b["Labels"]) > 10:
        raise SsmError("ParameterVersionLabelLimitExceeded", "A label can be attached to a parameter a maximum of 10 times.")
    ver = b.get("ParameterVersion") or _current(rec)["version"]
    target = next((v for v in rec["versions"] if v["version"] == ver), None)
    if not target:
        raise SsmError("ParameterVersionNotFound", f"Systems Manager could not find version {ver} of {name}. Verify the version and try again.")
    invalid = [l for l in b["Labels"] if not _LABEL_RE.match(l) or l.isdigit() or l.lower().startswith(("aws", "ssm"))]
    if invalid:
        return {"InvalidLabels": invalid, "ParameterVersion": ver}
    for l in b["Labels"]:
        for v in rec["versions"]:   # a label points at exactly one version
            if l in v.get("labels", []):
                v["labels"].remove(l)
        if l not in target["labels"]:
            target["labels"].append(l)
    return {"InvalidLabels": [], "ParameterVersion": ver}


def _unlabel_version(store: SsmStore, b: dict) -> dict:
    _need(b, "Name", "ParameterVersion", "Labels")
    name = _norm_name(b["Name"])
    rec = store.parameters.get(name)
    if not rec:
        raise SsmError("ParameterNotFound", f"Parameter {name} not found.")
    target = next((v for v in rec["versions"] if v["version"] == b["ParameterVersion"]), None)
    if not target:
        raise SsmError("ParameterVersionNotFound", f"Systems Manager could not find version {b['ParameterVersion']} of {name}. Verify the version and try again.")
    removed = [l for l in b["Labels"] if l in target["labels"]]
    target["labels"] = [l for l in target["labels"] if l not in removed]
    return {"RemovedLabels": removed, "InvalidLabels": [l for l in b["Labels"] if l not in removed]}


# ═══════════════════════════════════════════════════════════════════════════
# Tags (Parameter / Document / MaintenanceWindow / PatchBaseline)
# ═══════════════════════════════════════════════════════════════════════════
def _tag_holder(store: SsmStore, rtype: str, rid: str) -> dict:
    if rtype not in ("Parameter", "Document", "MaintenanceWindow", "PatchBaseline", "ManagedInstance", "Automation", "OpsItem", "OpsMetadata"):
        raise SsmError("InvalidResourceType", "The resource type is not valid. For example, if you are attempting to tag an EC2 instance, the instance must be a registered managed instance.")
    table = {"Parameter": store.parameters, "Document": store.documents, "MaintenanceWindow": store.windows,
             "PatchBaseline": store.baselines}.get(rtype)
    if table is None:
        raise SsmError("InvalidResourceId", "The resource ID is not valid. Verify that you entered the correct ID and try again.")
    key = _norm_name(rid) if rtype == "Parameter" else rid
    if key not in table:
        raise SsmError("InvalidResourceId", "The resource ID is not valid. Verify that you entered the correct ID and try again.")
    rec = table[key]
    rec.setdefault("tags", {})
    return rec


def _add_tags(store: SsmStore, b: dict) -> dict:
    _need(b, "ResourceType", "ResourceId", "Tags")
    rec = _tag_holder(store, b["ResourceType"], b["ResourceId"])
    merged = {**rec["tags"], **_tags_in(b["Tags"])}
    if len(merged) > 50:
        raise SsmError("TooManyTagsError", "The Targets parameter includes too many tags. Remove one or more tags and try the command again.")
    rec["tags"] = merged
    return {}


def _remove_tags(store: SsmStore, b: dict) -> dict:
    _need(b, "ResourceType", "ResourceId", "TagKeys")
    rec = _tag_holder(store, b["ResourceType"], b["ResourceId"])
    for k in b["TagKeys"]:
        rec["tags"].pop(k, None)
    return {}


def _list_tags(store: SsmStore, b: dict) -> dict:
    _need(b, "ResourceType", "ResourceId")
    return {"TagList": _tag_list(_tag_holder(store, b["ResourceType"], b["ResourceId"])["tags"])}


# ═══════════════════════════════════════════════════════════════════════════
# Documents
# ═══════════════════════════════════════════════════════════════════════════
_DOC_TYPES = ("Command", "Policy", "Automation", "Session", "Package", "ApplicationConfiguration",
              "ApplicationConfigurationSchema", "DeploymentStrategy", "ChangeCalendar", "Automation.ChangeTemplate",
              "ProblemAnalysis", "ProblemAnalysisTemplate", "CloudFormation", "ConformancePackTemplate", "QuickSetup")


def _parse_doc(content: str, fmt: str) -> dict:
    """Extract schemaVersion / description / parameters from a document body."""
    if fmt == "JSON":
        try:
            d = json.loads(content)
        except Exception:
            raise SsmError("InvalidDocumentContent", "The content for the document is not valid.")
        if not isinstance(d, dict) or "schemaVersion" not in d:
            raise SsmError("InvalidDocumentContent", "The content for the document is not valid.")
        return d
    if not content.strip() or "schemaVersion" not in content:
        raise SsmError("InvalidDocumentContent", "The content for the document is not valid.")
    d = {}
    m = re.search(r"^schemaVersion:\s*['\"]?([\d.]+)", content, re.M)
    d["schemaVersion"] = m.group(1) if m else "2.2"
    m = re.search(r"^description:\s*(.+)$", content, re.M)
    if m:
        d["description"] = m.group(1).strip().strip("'\"")
    params = {}
    pm = re.search(r"^parameters:\s*\n((?:[ \t]+.*\n?)+)", content, re.M)
    if pm:
        for name in re.findall(r"^  (\w+):\s*$", pm.group(1), re.M):
            params[name] = {}
    if params:
        d["parameters"] = params
    return d


def _doc_desc(name: str, doc: dict, ver: dict) -> dict:
    parsed = ver["parsed"]
    out = {"Hash": ver["hash"], "HashType": "Sha256", "Name": name, "Owner": doc["owner"], "CreatedDate": ver["created"],
           "Status": ver["status"], "DocumentVersion": str(ver["version"]), "PlatformTypes": ["Windows", "Linux", "MacOS"],
           "DocumentType": doc["type"], "SchemaVersion": str(parsed.get("schemaVersion", "2.2")),
           "LatestVersion": str(doc["versions"][-1]["version"]), "DefaultVersion": str(doc["default"]),
           "DocumentFormat": doc["format"], "Tags": _tag_list(doc.get("tags", {}))}
    if parsed.get("description"):
        out["Description"] = parsed["description"]
    if ver.get("version_name"):
        out["VersionName"] = ver["version_name"]
    if doc.get("target_type"):
        out["TargetType"] = doc["target_type"]
    out["Parameters"] = [{"Name": k, "Type": str((v or {}).get("type", "String")), "Description": str((v or {}).get("description", "")),
                          "DefaultValue": str((v or {}).get("default", ""))} for k, v in (parsed.get("parameters") or {}).items()]
    return out


def _add_doc_version(doc: dict, content: str, version_name: str | None = None) -> dict:
    parsed = _parse_doc(content, doc["format"])
    ver = {"version": (doc["versions"][-1]["version"] + 1) if doc["versions"] else 1, "content": content, "parsed": parsed,
           "hash": hashlib.sha256(content.encode()).hexdigest(), "created": _now(), "status": "Active",
           "version_name": version_name or ""}
    doc["versions"].append(ver)
    return ver


def _seed(store: SsmStore) -> None:
    """The Amazon-owned documents every account has."""
    if store._seeded:
        return
    store._seeded = True
    seeds = {
        "AWS-RunShellScript": ("Run a shell script or specify the commands to run.", "Command"),
        "AWS-RunPowerShellScript": ("Run a PowerShell script or specify the commands to run.", "Command"),
        "AWS-UpdateSSMAgent": ("Update the SSM Agent to the latest version.", "Command"),
        "AWS-RunPatchBaseline": ("Scan for or install patches on a managed node.", "Command"),
        "AWS-StopEC2Instance": ("Stop an Amazon EC2 instance.", "Automation"),
        "AWS-StartEC2Instance": ("Start an Amazon EC2 instance.", "Automation"),
    }
    for name, (desc, typ) in seeds.items():
        if name in store.documents:
            continue
        content = json.dumps({"schemaVersion": "2.2", "description": desc, "parameters": {"commands": {"type": "StringList", "description": "The commands to run."}}, "mainSteps": []})
        doc = {"owner": "Amazon", "type": typ, "format": "JSON", "default": 1, "versions": [], "tags": {}, "target_type": ""}
        _add_doc_version(doc, content)
        store.documents[name] = doc


def _need_doc(store: SsmStore, name: str) -> dict:
    doc = store.documents.get(name)
    if not doc:
        raise SsmError("InvalidDocument", "The specified document does not exist.")
    return doc


def _pick_version(doc: dict, ver: str | None, vname: str | None = None) -> dict:
    if vname:
        for v in doc["versions"]:
            if v.get("version_name") == vname:
                return v
        raise SsmError("InvalidDocument", "The specified document does not exist.")
    if not ver or ver == "$DEFAULT":
        ver = str(doc["default"])
    if ver == "$LATEST":
        return doc["versions"][-1]
    for v in doc["versions"]:
        if str(v["version"]) == str(ver):
            return v
    raise SsmError("InvalidDocument", "The specified document version does not exist.")


def _create_document(store: SsmStore, b: dict) -> dict:
    _need(b, "Content", "Name")
    name = b["Name"]
    if not _DOC_NAME_RE.match(name) or name.lower().startswith(("aws", "amazon")):
        raise SsmError("ValidationException", "Document names must be 3-128 characters of a-zA-Z0-9_-. and can't begin with aws or amazon.")
    if name in store.documents:
        raise SsmError("DocumentAlreadyExists", "The specified document already exists.")
    fmt = b.get("DocumentFormat") or "JSON"
    if fmt not in ("JSON", "YAML", "TEXT"):
        raise SsmError("ValidationException", f"1 validation error detected: Value '{fmt}' at 'documentFormat' failed to satisfy constraint: Member must satisfy enum value set: [YAML, JSON, TEXT]")
    typ = b.get("DocumentType") or "Command"
    if typ not in _DOC_TYPES:
        raise SsmError("ValidationException", f"1 validation error detected: Value '{typ}' at 'documentType' failed to satisfy constraint: Member must satisfy enum value set: {_DOC_TYPES}")
    if len(store.documents) >= 500:
        raise SsmError("MaxDocumentSizeExceeded", "The size limit of a document is 64 KB.")
    doc = {"owner": ACCOUNT, "type": typ, "format": fmt, "default": 1, "versions": [], "tags": _tags_in(b.get("Tags")),
           "target_type": b.get("TargetType", "")}
    ver = _add_doc_version(doc, b["Content"], b.get("VersionName"))
    store.documents[name] = doc
    return {"DocumentDescription": _doc_desc(name, doc, ver)}


def _get_document(store: SsmStore, b: dict) -> dict:
    _need(b, "Name")
    doc = _need_doc(store, b["Name"])
    ver = _pick_version(doc, b.get("DocumentVersion"), b.get("VersionName"))
    out = {"Name": b["Name"], "CreatedDate": ver["created"], "DocumentVersion": str(ver["version"]), "Status": ver["status"],
           "Content": ver["content"], "DocumentType": doc["type"], "DocumentFormat": doc["format"]}
    if ver.get("version_name"):
        out["VersionName"] = ver["version_name"]
    return out


def _describe_document(store: SsmStore, b: dict) -> dict:
    _need(b, "Name")
    doc = _need_doc(store, b["Name"])
    return {"Document": _doc_desc(b["Name"], doc, _pick_version(doc, b.get("DocumentVersion"), b.get("VersionName")))}


def _list_documents(store: SsmStore, b: dict) -> dict:
    flt = b.get("Filters") or b.get("DocumentFilterList") or []
    items = []
    for name in sorted(store.documents):
        doc = store.documents[name]
        ok = True
        for f in flt:
            key, vals = f.get("Key") or f.get("key"), f.get("Values") or [f.get("value")]
            if key == "Owner":
                ok &= any((doc["owner"] == ACCOUNT) if v == "Self" else (doc["owner"] == "Amazon") if v == "Amazon" else (doc["owner"] == v) for v in vals)
            elif key == "DocumentType":
                ok &= doc["type"] in vals
            elif key == "Name":
                ok &= name in vals
            elif key and key.startswith("tag:"):
                ok &= doc.get("tags", {}).get(key[4:]) in vals
        if not ok:
            continue
        cur = next(v for v in doc["versions"] if v["version"] == doc["default"])
        out = {"Name": name, "Owner": doc["owner"], "VersionName": cur.get("version_name", ""), "PlatformTypes": ["Windows", "Linux", "MacOS"],
               "DocumentVersion": str(doc["default"]), "DocumentType": doc["type"], "SchemaVersion": str(cur["parsed"].get("schemaVersion", "2.2")),
               "DocumentFormat": doc["format"], "Tags": _tag_list(doc.get("tags", {}))}
        if doc.get("target_type"):
            out["TargetType"] = doc["target_type"]
        items.append(out)
    return _page(items, b, "DocumentIdentifiers", 10, 50)


def _update_document(store: SsmStore, b: dict) -> dict:
    _need(b, "Content", "Name")
    doc = _need_doc(store, b["Name"])
    if doc["owner"] == "Amazon":
        raise SsmError("InvalidDocumentOperation", "You can't modify an Amazon-owned document.")
    base = b.get("DocumentVersion")
    if base and base != "$LATEST" and str(doc["versions"][-1]["version"]) != str(base):
        raise SsmError("InvalidDocumentVersion", "The document version is not valid or does not exist.")
    if any(v["content"] == b["Content"] for v in doc["versions"][-1:]):
        raise SsmError("DuplicateDocumentContent", "The content of the association document matches another document. Change the content of the document and try again.")
    if b.get("DocumentFormat"):
        doc["format"] = b["DocumentFormat"]
    ver = _add_doc_version(doc, b["Content"], b.get("VersionName"))
    return {"DocumentDescription": _doc_desc(b["Name"], doc, ver)}


def _update_default_version(store: SsmStore, b: dict) -> dict:
    _need(b, "Name", "DocumentVersion")
    doc = _need_doc(store, b["Name"])
    ver = _pick_version(doc, b["DocumentVersion"])
    doc["default"] = ver["version"]
    return {"Description": {"Name": b["Name"], "NewDefaultVersion": str(ver["version"])}}


def _list_doc_versions(store: SsmStore, b: dict) -> dict:
    _need(b, "Name")
    doc = _need_doc(store, b["Name"])
    items = [{"Name": b["Name"], "DocumentVersion": str(v["version"]), "VersionName": v.get("version_name", ""), "CreatedDate": v["created"],
              "IsDefaultVersion": v["version"] == doc["default"], "DocumentFormat": doc["format"], "Status": v["status"]}
             for v in doc["versions"]]
    return _page(items, b, "DocumentVersions", 50, 50)


def _delete_document(store: SsmStore, b: dict) -> dict:
    _need(b, "Name")
    doc = _need_doc(store, b["Name"])
    if doc["owner"] == "Amazon":
        raise SsmError("InvalidDocumentOperation", "You can't delete an Amazon-owned document.")
    if not b.get("Force") and any(a["name"] == b["Name"] for a in store.associations.values()):
        raise SsmError("AssociatedInstances", "You must disassociate the document from all instances before you can delete it.")
    del store.documents[b["Name"]]
    return {}


# ═══════════════════════════════════════════════════════════════════════════
# Run Command (completes immediately — no SSM agent offline)
# ═══════════════════════════════════════════════════════════════════════════
def _command_view(c: dict) -> dict:
    n = len(c["instance_ids"])
    out = {"CommandId": c["id"], "DocumentName": c["document"], "DocumentVersion": c["document_version"], "Comment": c.get("comment", ""),
           "ExpiresAfter": c["requested"] + c["timeout"], "Parameters": c.get("parameters", {}), "InstanceIds": list(c["instance_ids"]),
           "Targets": c.get("targets", []), "RequestedDateTime": c["requested"], "Status": c["status"], "StatusDetails": c["status_details"],
           "OutputS3BucketName": c.get("output_bucket", ""), "OutputS3KeyPrefix": c.get("output_prefix", ""), "MaxConcurrency": c.get("max_concurrency", "50"),
           "MaxErrors": c.get("max_errors", "0"), "TargetCount": n, "CompletedCount": n if c["status"] == "Success" else 0,
           "ErrorCount": 0, "DeliveryTimedOutCount": 0, "ServiceRole": "", "TimeoutSeconds": c["timeout"]}
    return out


def _send_command(store: SsmStore, b: dict) -> dict:
    _need(b, "DocumentName")
    doc = _need_doc(store, b["DocumentName"])
    ids = list(b.get("InstanceIds") or [])
    targets = b.get("Targets") or []
    if not ids and not targets:
        raise SsmError("ValidationException", "Either InstanceIds or Targets must be specified.")
    bad = [i for i in ids if not re.match(r"^(i-[0-9a-f]{8,17}|mi-[0-9a-f]{17})$", i)]
    if bad:
        raise SsmError("InvalidInstanceId", f"Instances not in a valid state for account {ACCOUNT}")
    for t in targets:   # resolve instance-id targets; tag targets match no instances offline
        if t.get("Key") == "InstanceIds":
            ids += [v for v in t.get("Values", []) if v not in ids]
    ver = _pick_version(doc, b.get("DocumentVersion"))
    cid = str(uuid.uuid4())
    now = _now()
    cmd = {"id": cid, "document": b["DocumentName"], "document_version": b.get("DocumentVersion") or str(ver["version"]), "comment": b.get("Comment", ""),
           "parameters": b.get("Parameters") or {}, "instance_ids": ids, "targets": targets, "requested": now,
           "timeout": int(b.get("TimeoutSeconds") or 3600), "status": "Success", "status_details": "Success",
           "output_bucket": b.get("OutputS3BucketName", ""), "output_prefix": b.get("OutputS3KeyPrefix", ""),
           "max_concurrency": b.get("MaxConcurrency", "50"), "max_errors": b.get("MaxErrors", "0"), "doc_type": doc["type"],
           "invocations": {i: {"status": "Success", "status_details": "Success", "response_code": 0, "start": now, "end": now,
                               "output": "", "error": ""} for i in ids}}
    if not ids:
        cmd["status"] = cmd["status_details"] = "Success"
    store.commands[cid] = cmd
    return {"Command": _command_view(cmd)}


def _list_commands(store: SsmStore, b: dict) -> dict:
    items = sorted(store.commands.values(), key=lambda c: -c["requested"])
    if b.get("CommandId"):
        items = [c for c in items if c["id"] == b["CommandId"]]
    if b.get("InstanceId"):
        items = [c for c in items if b["InstanceId"] in c["instance_ids"]]
    for f in b.get("Filters") or []:
        if f.get("key") == "DocumentName":
            items = [c for c in items if c["document"] == f.get("value")]
        elif f.get("key") == "Status":
            items = [c for c in items if c["status"] == f.get("value")]
    return _page([_command_view(c) for c in items], b, "Commands", 50, 50)


def _invocation_view(c: dict, iid: str, inv: dict, details: bool) -> dict:
    out = {"CommandId": c["id"], "InstanceId": iid, "InstanceName": "", "Comment": c.get("comment", ""), "DocumentName": c["document"],
           "DocumentVersion": c["document_version"], "RequestedDateTime": c["requested"], "Status": inv["status"],
           "StatusDetails": inv["status_details"], "StandardOutputUrl": "", "StandardErrorUrl": "",
           "ServiceRole": "", "NotificationConfig": {"NotificationArn": "", "NotificationEvents": [], "NotificationType": ""}}
    if details:
        out["CommandPlugins"] = [{"Name": "aws:runShellScript", "Status": inv["status"], "StatusDetails": inv["status_details"],
                                  "ResponseCode": inv["response_code"], "ResponseStartDateTime": inv["start"],
                                  "ResponseFinishDateTime": inv["end"], "Output": inv["output"], "StandardOutputUrl": "",
                                  "StandardErrorUrl": "", "OutputS3Region": REGION, "OutputS3BucketName": c.get("output_bucket", ""),
                                  "OutputS3KeyPrefix": c.get("output_prefix", "")}]
    return out


def _list_invocations(store: SsmStore, b: dict) -> dict:
    items = []
    for c in sorted(store.commands.values(), key=lambda c: -c["requested"]):
        if b.get("CommandId") and c["id"] != b["CommandId"]:
            continue
        for iid, inv in c["invocations"].items():
            if b.get("InstanceId") and iid != b["InstanceId"]:
                continue
            items.append(_invocation_view(c, iid, inv, bool(b.get("Details"))))
    return _page(items, b, "CommandInvocations", 50, 50)


def _get_invocation(store: SsmStore, b: dict) -> dict:
    _need(b, "CommandId", "InstanceId")
    c = store.commands.get(b["CommandId"])
    if not c:
        raise SsmError("InvalidCommandId", "The specified command ID is not valid. Verify the ID and try again.")
    inv = c["invocations"].get(b["InstanceId"])
    if not inv:
        raise SsmError("InvocationDoesNotExist", "The command ID and instance ID you specified did not match any invocations. Verify the command ID and the instance ID and try again.")
    return {"CommandId": c["id"], "InstanceId": b["InstanceId"], "Comment": c.get("comment", ""), "DocumentName": c["document"],
            "DocumentVersion": c["document_version"], "PluginName": b.get("PluginName") or "aws:runShellScript", "ResponseCode": inv["response_code"],
            "ExecutionStartDateTime": str(inv["start"]), "ExecutionElapsedTime": "PT0.001S", "ExecutionEndDateTime": str(inv["end"]),
            "Status": inv["status"], "StatusDetails": inv["status_details"], "StandardOutputContent": inv["output"],
            "StandardOutputUrl": "", "StandardErrorContent": inv["error"], "StandardErrorUrl": ""}


def _cancel_command(store: SsmStore, b: dict) -> dict:
    _need(b, "CommandId")
    if b["CommandId"] not in store.commands:
        raise SsmError("InvalidCommandId", "The specified command ID is not valid. Verify the ID and try again.")
    return {}   # already terminal (Success) — cancelling a finished command is a no-op, as on AWS


def _describe_instance_info(store: SsmStore, b: dict) -> dict:
    return {"InstanceInformationList": []}   # no SSM agents register against the simulator


# ═══════════════════════════════════════════════════════════════════════════
# State Manager associations
# ═══════════════════════════════════════════════════════════════════════════
def _assoc_view(a: dict) -> dict:
    out = {"Name": a["name"], "AssociationId": a["id"], "AssociationVersion": "1", "DocumentVersion": a["document_version"],
           "Targets": a["targets"], "LastExecutionDate": a["created"], "Overview": {"Status": "Pending", "DetailedStatus": "Creating", "AssociationStatusAggregatedCount": {}},
           "ScheduleExpression": a.get("schedule", ""), "AssociationName": a.get("association_name", ""), "Date": a["created"],
           "LastUpdateAssociationDate": a["created"], "Status": {"Date": a["created"], "Name": "Pending", "Message": "Creating association", "AdditionalInfo": ""},
           "Parameters": a.get("parameters", {}), "ApplyOnlyAtCronInterval": False}
    if a.get("instance_id"):
        out["InstanceId"] = a["instance_id"]
    return out


def _create_association(store: SsmStore, b: dict) -> dict:
    _need(b, "Name")
    doc = _need_doc(store, b["Name"])
    targets = list(b.get("Targets") or [])
    if b.get("InstanceId"):
        targets.append({"Key": "InstanceIds", "Values": [b["InstanceId"]]})
    if not targets:
        raise SsmError("InvalidTarget", "The target is not valid or does not exist. It might not be configured for Systems Manager or you might not have permission to perform the operation.")
    if b.get("AssociationName") and any(a.get("association_name") == b["AssociationName"] for a in store.associations.values()):
        raise SsmError("AssociationAlreadyExists", "The specified association already exists.")
    aid = str(uuid.uuid4())
    a = {"id": aid, "name": b["Name"], "document_version": b.get("DocumentVersion") or str(doc["default"]), "targets": targets,
         "schedule": b.get("ScheduleExpression", ""), "association_name": b.get("AssociationName", ""), "created": _now(),
         "parameters": b.get("Parameters") or {}, "instance_id": b.get("InstanceId", "")}
    store.associations[aid] = a
    return {"AssociationDescription": _assoc_view(a)}


def _describe_association(store: SsmStore, b: dict) -> dict:
    a = store.associations.get(b.get("AssociationId") or "")
    if not a:
        raise SsmError("AssociationDoesNotExist", "The specified association does not exist.")
    return {"AssociationDescription": _assoc_view(a)}


def _list_associations(store: SsmStore, b: dict) -> dict:
    items = sorted(store.associations.values(), key=lambda a: a["created"])
    for f in b.get("AssociationFilterList") or []:
        if f.get("key") == "Name":
            items = [a for a in items if a["name"] == f.get("value")]
        elif f.get("key") == "AssociationName":
            items = [a for a in items if a.get("association_name") == f.get("value")]
    view = [{k: v for k, v in _assoc_view(a).items() if k in ("Name", "InstanceId", "AssociationId", "DocumentVersion", "Targets", "LastExecutionDate", "Overview", "ScheduleExpression", "AssociationName")} for a in items]
    return _page(view, b, "Associations", 50, 50)


def _delete_association(store: SsmStore, b: dict) -> dict:
    a = store.associations.get(b.get("AssociationId") or "")
    if not a:
        raise SsmError("AssociationDoesNotExist", "The specified association does not exist.")
    del store.associations[a["id"]]
    return {}


# ═══════════════════════════════════════════════════════════════════════════
# Maintenance windows
# ═══════════════════════════════════════════════════════════════════════════
def _need_window(store: SsmStore, wid: str) -> dict:
    w = store.windows.get(wid or "")
    if not w:
        raise SsmError("DoesNotExistException", f"Maintenance window {wid} does not exist")
    return w


def _window_next(w: dict) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(w["created"] + 86400))


def _create_window(store: SsmStore, b: dict) -> dict:
    _need(b, "Name", "Schedule", "Duration", "Cutoff")
    if "AllowUnassociatedTargets" not in b:
        _need(b, "AllowUnassociatedTargets")
    if not re.match(r"^[a-zA-Z0-9_\-.]{3,128}$", b["Name"]):
        raise SsmError("ValidationException", f"1 validation error detected: Value '{b['Name']}' at 'name' failed to satisfy constraint: Member must satisfy regular expression pattern: ^[a-zA-Z0-9_\\-.]{{3,128}}$")
    if not (1 <= int(b["Duration"]) <= 24) or not (0 <= int(b["Cutoff"]) <= 23):
        raise SsmError("ValidationException", "Duration must be 1-24 hours and Cutoff 0-23 hours.")
    if int(b["Cutoff"]) >= int(b["Duration"]):
        raise SsmError("ValidationException", "Cutoff must be less than Duration.")
    if not re.match(r"^(cron|rate|at)\(.*\)$", b["Schedule"]):
        raise SsmError("ValidationException", "Schedule must be a cron(), rate() or at() expression.")
    ct = b.get("ClientToken")
    if ct:
        for w in store.windows.values():
            if w.get("client_token") == ct:
                return {"WindowId": w["id"]}
    wid = "mw-" + _hex(17)
    store.windows[wid] = {"id": wid, "name": b["Name"], "description": b.get("Description", ""), "schedule": b["Schedule"], "duration": int(b["Duration"]),
                          "cutoff": int(b["Cutoff"]), "allow_unassociated": bool(b["AllowUnassociatedTargets"]), "enabled": True, "created": _now(),
                          "modified": _now(), "timezone": b.get("ScheduleTimezone", "UTC"), "tags": _tags_in(b.get("Tags")),
                          "client_token": ct or "", "targets": {}}
    return {"WindowId": wid}


def _window_view(w: dict, full: bool) -> dict:
    out = {"Name": w["name"], "Enabled": w["enabled"], "Duration": w["duration"], "Cutoff": w["cutoff"], "Schedule": w["schedule"],
           "ScheduleTimezone": w["timezone"], "NextExecutionTime": _window_next(w)}
    if w.get("description"):
        out["Description"] = w["description"]
    if full:
        out.update({"WindowId": w["id"], "AllowUnassociatedTargets": w["allow_unassociated"], "CreatedDate": w["created"], "ModifiedDate": w["modified"]})
    else:
        out["WindowId"] = w["id"]
    return out


def _get_window(store: SsmStore, b: dict) -> dict:
    _need(b, "WindowId")
    return _window_view(_need_window(store, b["WindowId"]), True)


def _describe_windows(store: SsmStore, b: dict) -> dict:
    items = sorted(store.windows.values(), key=lambda w: w["created"])
    for f in b.get("Filters") or []:
        vals = f.get("Values") or []
        if f.get("Key") == "Name":
            items = [w for w in items if w["name"] in vals]
        elif f.get("Key") == "Enabled":
            items = [w for w in items if str(w["enabled"]).lower() in [v.lower() for v in vals]]
    return _page([_window_view(w, False) for w in items], b, "WindowIdentities", 10, 50)


def _update_window(store: SsmStore, b: dict) -> dict:
    _need(b, "WindowId")
    w = _need_window(store, b["WindowId"])
    for src, dst in (("Name", "name"), ("Description", "description"), ("Schedule", "schedule"), ("Duration", "duration"), ("Cutoff", "cutoff"),
                     ("AllowUnassociatedTargets", "allow_unassociated"), ("Enabled", "enabled"), ("ScheduleTimezone", "timezone")):
        if b.get(src) is not None:
            w[dst] = b[src]
    w["modified"] = _now()
    out = _window_view(w, True)
    out.pop("NextExecutionTime", None)
    return out


def _delete_window(store: SsmStore, b: dict) -> dict:
    _need(b, "WindowId")
    _need_window(store, b["WindowId"])
    del store.windows[b["WindowId"]]
    return {"WindowId": b["WindowId"]}


def _register_target(store: SsmStore, b: dict) -> dict:
    _need(b, "WindowId", "ResourceType", "Targets")
    w = _need_window(store, b["WindowId"])
    if b["ResourceType"] not in ("INSTANCE", "RESOURCE_GROUP"):
        raise SsmError("ValidationException", "ResourceType must be INSTANCE or RESOURCE_GROUP.")
    tid = str(uuid.uuid4())
    w["targets"][tid] = {"id": tid, "resource_type": b["ResourceType"], "targets": b["Targets"], "name": b.get("Name", ""),
                         "description": b.get("Description", ""), "owner_information": b.get("OwnerInformation", "")}
    return {"WindowTargetId": tid}


def _describe_targets(store: SsmStore, b: dict) -> dict:
    _need(b, "WindowId")
    w = _need_window(store, b["WindowId"])
    items = [{"WindowId": w["id"], "WindowTargetId": t["id"], "ResourceType": t["resource_type"], "Targets": t["targets"],
              "OwnerInformation": t["owner_information"], "Name": t["name"], "Description": t["description"]} for t in w["targets"].values()]
    return _page(items, b, "Targets", 50, 50)


def _deregister_target(store: SsmStore, b: dict) -> dict:
    _need(b, "WindowId", "WindowTargetId")
    w = _need_window(store, b["WindowId"])
    if b["WindowTargetId"] not in w["targets"]:
        raise SsmError("DoesNotExistException", f"Maintenance window target {b['WindowTargetId']} does not exist")
    del w["targets"][b["WindowTargetId"]]
    return {"WindowId": w["id"], "WindowTargetId": b["WindowTargetId"]}


# ═══════════════════════════════════════════════════════════════════════════
# Patch baselines
# ═══════════════════════════════════════════════════════════════════════════
_OSES = ("WINDOWS", "AMAZON_LINUX", "AMAZON_LINUX_2", "AMAZON_LINUX_2022", "UBUNTU", "REDHAT_ENTERPRISE_LINUX", "SUSE", "CENTOS",
         "ORACLE_LINUX", "DEBIAN", "MACOS", "RASPBIAN", "ROCKY_LINUX", "ALMA_LINUX", "AMAZON_LINUX_2023")


def _create_baseline(store: SsmStore, b: dict) -> dict:
    _need(b, "Name")
    os_ = b.get("OperatingSystem") or "WINDOWS"
    if os_ not in _OSES:
        raise SsmError("ValidationException", f"1 validation error detected: Value '{os_}' at 'operatingSystem' failed to satisfy constraint: Member must satisfy enum value set: {list(_OSES)}")
    bid = "pb-" + _hex(17)
    store.baselines[bid] = {"id": bid, "name": b["Name"], "os": os_, "description": b.get("Description", ""), "tags": _tags_in(b.get("Tags")),
                            "approval_rules": b.get("ApprovalRules") or {"PatchRules": []}, "approved": b.get("ApprovedPatches") or [],
                            "rejected": b.get("RejectedPatches") or [], "created": _now(), "default": False}
    return {"BaselineId": bid}


def _baseline_ident(p: dict) -> dict:
    return {"BaselineId": p["id"], "BaselineName": p["name"], "OperatingSystem": p["os"], "BaselineDescription": p["description"], "DefaultBaseline": p["default"]}


def _get_baseline(store: SsmStore, b: dict) -> dict:
    _need(b, "BaselineId")
    p = store.baselines.get(b["BaselineId"])
    if not p:
        raise SsmError("DoesNotExistException", f"Patch baseline {b['BaselineId']} does not exist")
    return {"BaselineId": p["id"], "Name": p["name"], "OperatingSystem": p["os"], "GlobalFilters": {"PatchFilters": []},
            "ApprovalRules": p["approval_rules"], "ApprovedPatches": p["approved"], "ApprovedPatchesComplianceLevel": "UNSPECIFIED",
            "ApprovedPatchesEnableNonSecurity": False, "RejectedPatches": p["rejected"], "PatchGroups": [], "CreatedDate": p["created"],
            "ModifiedDate": p["created"], "Description": p["description"], "Sources": [], "RejectedPatchesAction": "ALLOW_AS_DEPENDENCY"}


def _describe_baselines(store: SsmStore, b: dict) -> dict:
    items = sorted(store.baselines.values(), key=lambda p: p["created"])
    for f in b.get("Filters") or []:
        vals = f.get("Values") or []
        if f.get("Key") == "NAME_PREFIX":
            items = [p for p in items if any(p["name"].startswith(v) for v in vals)]
        elif f.get("Key") == "OWNER":
            items = [p for p in items if "Self" in vals or "All" in vals]
        elif f.get("Key") == "OPERATING_SYSTEM":
            items = [p for p in items if p["os"] in vals]
    return _page([_baseline_ident(p) for p in items], b, "BaselineIdentities", 10, 100)


def _delete_baseline(store: SsmStore, b: dict) -> dict:
    _need(b, "BaselineId")
    if b["BaselineId"] not in store.baselines:
        raise SsmError("DoesNotExistException", f"Patch baseline {b['BaselineId']} does not exist")
    del store.baselines[b["BaselineId"]]
    return {"BaselineId": b["BaselineId"]}


# ═══════════════════════════════════════════════════════════════════════════
# dispatch
# ═══════════════════════════════════════════════════════════════════════════
_OPS = {
    "PutParameter": _put_parameter, "GetParameter": _get_parameter, "GetParameters": _get_parameters,
    "GetParametersByPath": _get_by_path, "DescribeParameters": _describe_parameters, "DeleteParameter": _delete_parameter,
    "DeleteParameters": _delete_parameters, "GetParameterHistory": _parameter_history,
    "LabelParameterVersion": _label_version, "UnlabelParameterVersion": _unlabel_version,
    "AddTagsToResource": _add_tags, "RemoveTagsFromResource": _remove_tags, "ListTagsForResource": _list_tags,
    "CreateDocument": _create_document, "GetDocument": _get_document, "DescribeDocument": _describe_document,
    "ListDocuments": _list_documents, "UpdateDocument": _update_document, "UpdateDocumentDefaultVersion": _update_default_version,
    "ListDocumentVersions": _list_doc_versions, "DeleteDocument": _delete_document,
    "SendCommand": _send_command, "ListCommands": _list_commands, "ListCommandInvocations": _list_invocations,
    "GetCommandInvocation": _get_invocation, "CancelCommand": _cancel_command,
    "DescribeInstanceInformation": _describe_instance_info,
    "CreateAssociation": _create_association, "DescribeAssociation": _describe_association,
    "ListAssociations": _list_associations, "DeleteAssociation": _delete_association,
    "CreateMaintenanceWindow": _create_window, "GetMaintenanceWindow": _get_window,
    "DescribeMaintenanceWindows": _describe_windows, "UpdateMaintenanceWindow": _update_window,
    "DeleteMaintenanceWindow": _delete_window, "RegisterTargetWithMaintenanceWindow": _register_target,
    "DescribeMaintenanceWindowTargets": _describe_targets, "DeregisterTargetFromMaintenanceWindow": _deregister_target,
    "CreatePatchBaseline": _create_baseline, "GetPatchBaseline": _get_baseline,
    "DescribePatchBaselines": _describe_baselines, "DeletePatchBaseline": _delete_baseline,
}
OPERATIONS = sorted(_OPS)


def dispatch(store: SsmStore, target: str, payload: dict | None = None) -> SsmResponse:
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    if not action:
        return _error("MissingAction", "The request must include X-Amz-Target.", 400)
    fn = _OPS.get(action)
    if fn is None:
        return _error("UnknownOperationException", f"The action {action} is not implemented.", 400)
    _seed(store)
    try:
        return _ok(fn(store, body))
    except SsmError as e:
        return _error(e.code, e.message, e.status)
    except (TypeError, ValueError, AttributeError, KeyError):
        return _error("ValidationException", f"The request for {action} is not valid.", 400)


def _ok(body: dict) -> SsmResponse:
    return SsmResponse(status=200, body=body, headers={"x-amzn-requestid": _req_id()})


def _error(code: str, message: str, status: int = 400) -> SsmResponse:
    return SsmResponse(status=status, body={"__type": code, "message": message},
                       headers={"x-amzn-requestid": _req_id(), "x-amzn-errortype": code})


# ═══════════════════════════════════════════════════════════════════════════
# Console views (every grid column is always populated)
# ═══════════════════════════════════════════════════════════════════════════
def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))


def console_view(name: str, rec: dict, decrypt: bool = True) -> dict:
    v = _current(rec)
    return {"name": name, "id": name, "type": v["type"], "tier": v["tier"], "version": v["version"], "data_type": v.get("data_type", "text"),
            "last_modified": _iso(v["last_modified"]), "description": v.get("description") or "", "key_id": v.get("key_id") or "",
            "allowed_pattern": v.get("allowed_pattern") or "", "arn": _param_arn(name), "tags": dict(rec.get("tags") or {}),
            "value": _value_out(v, decrypt), "labels": list(v.get("labels", [])), "status": "Active"}


def console_history(name: str, rec: dict) -> list:
    return [{"version": v["version"], "value": _value_out(v, False), "type": v["type"], "last_modified": _iso(v["last_modified"]),
             "labels": ", ".join(v.get("labels", [])) or "none", "description": v.get("description") or "none",
             "last_modified_user": v["last_modified_user"]} for v in reversed(rec["versions"])]
