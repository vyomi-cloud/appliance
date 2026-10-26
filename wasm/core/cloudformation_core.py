"""CloudFormation core — substrate-independent stacks / change sets / events /
exports on the NATIVE AWS CloudFormation wire (the **Query protocol**: form-encoded
`Action=CreateStack&...`, XML responses, http://cloudformation.amazonaws.com/doc/2010-05-15/),
so an unmodified boto3 / aws-sdk-go-v2 / AWS SDK for Java v2 / aws-cli works.

NO fastapi / boto3 / socket / yaml imports (stdlib only) → loads under Pyodide, and
the very same file is what the offline appliance and Nano run. State lives on a
`CfnStore` seam (in-memory; `PersistentCfnStore` in core/persistent_store.py
write-throughs to SQLite through `persist()`).

Modeled:
  * templates — JSON and YAML (a built-in YAML subset incl. !Ref / !GetAtt / !Sub /
    !Join / ... short tags), Parameters (types, defaults, AllowedValues, NoEcho),
    Mappings, Conditions, Resources (DependsOn + implicit Ref/GetAtt ordering),
    Outputs (+ Export), Metadata.
  * intrinsics — Ref, Fn::GetAtt/Join/Sub/Select/Split/FindInMap/If/Equals/And/Or/Not/
    Base64/GetAZs/ImportValue/Cidr/Length/ToJsonString, pseudo parameters, AWS::NoValue.
  * lifecycle — CreateStack / UpdateStack / DeleteStack with real status strings and a
    per-resource event stream; ROLLBACK_COMPLETE on a failed create; termination
    protection; export / import checks; capability checks (IAM resources).
  * change sets — CREATE and UPDATE types, Add/Modify/Remove changes, Execute / Delete.
  * stack sets — metadata-level (create / describe / list / delete).

Resources are *simulated*: each gets a deterministic-shaped physical id and the
attributes templates actually reference (Arn, DomainName, Url, …). `store.provision`
is an optional hook `(type, logical_id, props, ctx) -> (physical_id, attrs) | None`
that a substrate can use to create the real thing in another core.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

CFN_NS = "http://cloudformation.amazonaws.com/doc/2010-05-15/"
REGION = "us-east-1"
ACCOUNT_ID = "123456789012"
IAM_TYPES = ("AWS::IAM::Role", "AWS::IAM::User", "AWS::IAM::Group", "AWS::IAM::Policy",
             "AWS::IAM::ManagedPolicy", "AWS::IAM::AccessKey", "AWS::IAM::InstanceProfile")
NAMED_IAM_PROPS = {"AWS::IAM::Role": "RoleName", "AWS::IAM::User": "UserName",
                   "AWS::IAM::Group": "GroupName", "AWS::IAM::ManagedPolicy": "ManagedPolicyName"}


@dataclass
class CfnResponse:
    status: int = 200
    body: str = ""
    headers: dict = field(default_factory=dict)
    media_type: str = "text/xml"


class CfnError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status = code, message, status


def _validation(msg: str) -> CfnError:
    return CfnError("ValidationError", msg)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _rid() -> str:
    return str(uuid.uuid4())


def _rand(n: int = 12) -> str:
    return uuid.uuid4().hex[:n]


# ── the store seam ─────────────────────────────────────────────────────────
class CfnStore:
    """stacks / change_sets / stack_sets keyed by id; exports derived from stacks."""

    def __init__(self, account_id: str = ACCOUNT_ID, region: str = REGION) -> None:
        self.account_id = account_id
        self.region = region
        self.stacks: dict[str, dict] = {}        # stack_id -> stack record
        self.change_sets: dict[str, dict] = {}   # change_set_id -> record
        self.stack_sets: dict[str, dict] = {}    # name -> record
        self.provision = None                    # optional substrate hook
        self.fetch_url = None                    # optional (url)->str for TemplateURL

    def persist(self) -> None:
        """Flush hook (no-op in memory)."""


# ── minimal YAML (CloudFormation subset) ───────────────────────────────────
_SHORT = {"Ref": "Ref", "Condition": "Condition"}


def _tag_name(tag: str) -> str:
    t = tag.lstrip("!")
    return t if t in _SHORT else "Fn::" + t


def _scalar(s: str):
    s = s.strip()
    if s == "" or s in ("~", "null", "Null", "NULL"):
        return None
    if s[0] in "\"'" and len(s) >= 2 and s[-1] == s[0]:
        if s[0] == '"':
            try:
                return json.loads(s)
            except Exception:
                return s[1:-1]
        return s[1:-1].replace("''", "'")
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if re.fullmatch(r"[-+]?\d+", s):
        return int(s)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+)([eE][-+]?\d+)?", s):
        return float(s)
    return s


def _strip_comment(line: str) -> str:
    q = None
    for i, c in enumerate(line):
        if q:
            if c == q:
                q = None
        elif c in "\"'":
            q = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


class _Flow:
    """Flow collections `{a: b, c: [d, e]}` / `[a, !Ref b]`."""

    def __init__(self, s: str) -> None:
        self.s, self.i = s, 0

    def ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i] in " \t\n":
            self.i += 1

    def value(self):
        self.ws()
        c = self.s[self.i]
        if c == "{":
            self.i += 1
            out = {}
            while True:
                self.ws()
                if self.s[self.i] == "}":
                    self.i += 1
                    return out
                k = self.token(":}")
                self.ws()
                if self.s[self.i] == ":":
                    self.i += 1
                    out[k] = self.value()
                else:
                    out[k] = None
                self.ws()
                if self.s[self.i] == ",":
                    self.i += 1
        if c == "[":
            self.i += 1
            out = []
            while True:
                self.ws()
                if self.s[self.i] == "]":
                    self.i += 1
                    return out
                out.append(self.value())
                self.ws()
                if self.s[self.i] == ",":
                    self.i += 1
        if c == "!":
            j = self.i
            while self.i < len(self.s) and self.s[self.i] not in " \t,]}":
                self.i += 1
            tag = self.s[j:self.i]
            return {_tag_name(tag): self.value()}
        return _scalar(self.token(",]}"))

    def token(self, stops: str):
        self.ws()
        if self.s[self.i] in "\"'":
            q = self.s[self.i]
            j = self.i + 1
            while j < len(self.s) and not (self.s[j] == q and self.s[j - 1] != "\\"):
                j += 1
            raw = self.s[self.i:j + 1]
            self.i = j + 1
            return _scalar(raw)
        j = self.i
        while self.i < len(self.s) and self.s[self.i] not in stops:
            if self.s[self.i] == ":" and ":" in stops and self.s[self.i + 1:self.i + 2] not in (" ", ""):
                self.i += 1
                continue
            self.i += 1
        return self.s[j:self.i].strip()


def _yaml_value(text: str):
    """Parse the inline part after `key:` / `- ` (scalar / flow / !Tag scalar)."""
    t = text.strip()
    if t.startswith("!"):
        tag, _, rest = t.partition(" ")
        return {_tag_name(tag): _yaml_value(rest) if rest.strip() else None}
    if t[:1] in "{[":
        return _Flow(t).value()
    return _scalar(t)


def parse_yaml(text: str):
    raw = text.replace("\t", "  ").splitlines()
    items = [(len(l) - len(l.lstrip(" ")), l) for l in raw]

    def parse_block(idx: int, indent: int):
        """Parse the node whose lines start at idx with the given indent. Returns (value, next_idx)."""
        while idx < len(items) and not _strip_comment(items[idx][1]).strip():
            idx += 1
        if idx >= len(items):
            return None, idx
        ind, line = items[idx]
        body = _strip_comment(line).strip()
        if body.startswith("- ") or body == "-":
            out = []
            while idx < len(items):
                while idx < len(items) and not _strip_comment(items[idx][1]).strip():
                    idx += 1
                if idx >= len(items):
                    break
                ind2, l2 = items[idx]
                b2 = _strip_comment(l2).strip()
                if ind2 != ind or not (b2.startswith("- ") or b2 == "-"):
                    break
                rest = b2[1:].strip()
                if not rest:
                    v, idx = parse_block(idx + 1, ind + 1)
                    out.append(v)
                elif re.match(r"^[^\s\"'{\[!][^:]*:(\s|$)", rest) or re.match(r"^[\"'][^\"']*[\"']:(\s|$)", rest):
                    # inline mapping start inside a list item: re-indent this line as a mapping
                    items[idx] = (ind + 2, " " * (ind + 2) + rest)
                    v, idx = parse_block(idx, ind + 2)
                    out.append(v)
                else:
                    out.append(_yaml_value(rest))
                    idx += 1
            return out, idx
        if re.match(r"^(\"[^\"]*\"|'[^']*'|[^\s\"'{\[!#-][^:]*|-[^\s:][^:]*):(\s|$)", body) and not body.startswith("!"):
            out = {}
            while idx < len(items):
                while idx < len(items) and not _strip_comment(items[idx][1]).strip():
                    idx += 1
                if idx >= len(items):
                    break
                ind2, l2 = items[idx]
                b2 = _strip_comment(l2).strip()
                if ind2 < ind:
                    break
                if ind2 > ind:
                    raise ValueError(f"bad indentation near: {b2[:40]}")
                m = re.match(r"^(\"[^\"]*\"|'[^']*'|[^:]+?):(?:\s+(.*))?$", b2)
                if not m or b2.startswith("- "):
                    break
                key = _scalar(m.group(1)) if m.group(1)[0] in "\"'" else m.group(1).strip()
                key = key if isinstance(key, str) else str(key)
                rest = (m.group(2) or "").strip()
                idx += 1
                if rest[:1] in ("|", ">"):
                    fold = rest[0] == ">"
                    keep = rest[1:2] == "+"
                    buf: list[str] = []
                    bind = None
                    while idx < len(items):
                        li, ll = items[idx]
                        if ll.strip() == "":
                            buf.append("")
                            idx += 1
                            continue
                        if li <= ind:
                            break
                        bind = li if bind is None else bind
                        buf.append(ll[bind:] if li >= bind else ll.strip())
                        idx += 1
                    while buf and buf[-1] == "" and not keep:
                        buf.pop()
                    if fold:
                        s = " ".join(buf)
                    else:
                        s = "\n".join(buf)
                    out[key] = s + "\n" if buf and rest[1:2] != "-" else s
                elif rest and not rest.startswith("!") or (rest.startswith("!") and " " in rest):
                    # a plain multi-line scalar continues on deeper lines
                    val = _yaml_value(rest)
                    if isinstance(val, str) and rest[:1] not in "\"'":
                        while idx < len(items) and items[idx][0] > ind and _strip_comment(items[idx][1]).strip():
                            val += " " + _strip_comment(items[idx][1]).strip()
                            idx += 1
                    out[key] = val
                elif rest:  # bare !Tag then nested block / list on following lines
                    tag = _tag_name(rest)
                    nxt = idx
                    while nxt < len(items) and not _strip_comment(items[nxt][1]).strip():
                        nxt += 1
                    if nxt < len(items) and items[nxt][0] >= ind:
                        v, idx = parse_block(nxt, items[nxt][0])
                    else:
                        v = None
                    out[key] = {tag: v}
                else:
                    nxt = idx
                    while nxt < len(items) and not _strip_comment(items[nxt][1]).strip():
                        nxt += 1
                    if nxt < len(items) and (items[nxt][0] > ind or (
                            items[nxt][0] == ind and _strip_comment(items[nxt][1]).strip().startswith("- "))):
                        v, idx = parse_block(nxt, items[nxt][0])
                        out[key] = v
                    else:
                        out[key] = None
            return out, idx
        return _yaml_value(body), idx + 1

    first = 0
    while first < len(items) and (not _strip_comment(items[first][1]).strip()
                                  or _strip_comment(items[first][1]).strip() == "---"):
        first += 1
    if first >= len(items):
        return None
    val, _ = parse_block(first, items[first][0])
    return val


def parse_template(text: str) -> dict:
    t = (text or "").strip()
    if not t:
        raise _validation("Template format error: Template body is empty")
    doc = None
    if t[0] == "{":
        try:
            doc = json.loads(t)
        except Exception as e:
            raise _validation(f"Template format error: JSON not well-formed. ({e})")
    else:
        try:
            doc = parse_yaml(t)
        except Exception as e:
            raise _validation(f"Template format error: YAML not well-formed. ({e})")
    if not isinstance(doc, dict):
        raise _validation("Template format error: unsupported structure.")
    return doc


# ── resource model (physical ids + attributes) ─────────────────────────────
_EC2_PREFIX = {"VPC": "vpc", "Subnet": "subnet", "SecurityGroup": "sg", "InternetGateway": "igw",
               "RouteTable": "rtb", "Instance": "i", "Volume": "vol", "NetworkAcl": "acl",
               "NatGateway": "nat", "EIP": "eipalloc", "NetworkInterface": "eni",
               "SubnetRouteTableAssociation": "rtbassoc", "VPCGatewayAttachment": "igw-attach"}


def _service_name(rtype: str) -> str:
    return rtype.split("::")[1].lower() if rtype.count("::") >= 2 else "custom"


def _simulate_resource(store: CfnStore, stack_name: str, logical: str, rtype: str, props: dict):
    """-> (physical_id, attrs) for a resource type."""
    acct, region = store.account_id, store.region
    short = rtype.split("::")[-1]
    svc = _service_name(rtype)
    uniq = f"{stack_name}-{logical}-{_rand(12).upper()}"
    attrs: dict = {}
    if rtype == "AWS::S3::Bucket":
        name = props.get("BucketName") or f"{stack_name}-{logical}-{_rand(12)}".lower()
        attrs = {"Arn": f"arn:aws:s3:::{name}", "DomainName": f"{name}.s3.amazonaws.com",
                 "RegionalDomainName": f"{name}.s3.{region}.amazonaws.com",
                 "DualStackDomainName": f"{name}.s3.dualstack.{region}.amazonaws.com",
                 "WebsiteURL": f"http://{name}.s3-website-{region}.amazonaws.com"}
        return name, attrs
    if rtype == "AWS::SQS::Queue":
        name = props.get("QueueName") or uniq
        arn = f"arn:aws:sqs:{region}:{acct}:{name}"
        return f"https://sqs.{region}.amazonaws.com/{acct}/{name}", {"Arn": arn, "QueueName": name,
                                                                      "QueueUrl": f"https://sqs.{region}.amazonaws.com/{acct}/{name}"}
    if rtype == "AWS::SNS::Topic":
        name = props.get("TopicName") or uniq
        arn = f"arn:aws:sns:{region}:{acct}:{name}"
        return arn, {"TopicName": name, "TopicArn": arn}
    if rtype == "AWS::DynamoDB::Table":
        name = props.get("TableName") or uniq
        return name, {"Arn": f"arn:aws:dynamodb:{region}:{acct}:table/{name}",
                      "StreamArn": f"arn:aws:dynamodb:{region}:{acct}:table/{name}/stream/{_now()}"}
    if rtype in ("AWS::IAM::Role", "AWS::IAM::User", "AWS::IAM::Group", "AWS::IAM::ManagedPolicy"):
        key = NAMED_IAM_PROPS[rtype]
        name = props.get(key) or uniq
        kind = {"Role": "role", "User": "user", "Group": "group", "ManagedPolicy": "policy"}[short]
        arn = f"arn:aws:iam::{acct}:{kind}/{name}"
        a = {"Arn": arn}
        if kind in ("role", "user", "group"):
            a[short + "Id"] = "AIDA" + _rand(17).upper()
        return (arn if kind == "policy" else name), a
    if rtype == "AWS::Lambda::Function":
        name = props.get("FunctionName") or uniq
        return name, {"Arn": f"arn:aws:lambda:{region}:{acct}:function:{name}"}
    if rtype == "AWS::Logs::LogGroup":
        name = props.get("LogGroupName") or f"/aws/{stack_name}/{logical}-{_rand(8)}"
        return name, {"Arn": f"arn:aws:logs:{region}:{acct}:log-group:{name}:*"}
    if rtype == "AWS::KMS::Key":
        kid = str(uuid.uuid4())
        return kid, {"Arn": f"arn:aws:kms:{region}:{acct}:key/{kid}", "KeyId": kid}
    if rtype == "AWS::SecretsManager::Secret":
        arn = f"arn:aws:secretsmanager:{region}:{acct}:secret:{props.get('Name') or uniq}-{_rand(6)}"
        return arn, {"Arn": arn, "Id": arn}
    if rtype == "AWS::SSM::Parameter":
        return props.get("Name") or uniq, {"Type": props.get("Type", "String"), "Value": props.get("Value", "")}
    if rtype == "AWS::Events::Rule":
        name = props.get("Name") or uniq
        return name, {"Arn": f"arn:aws:events:{region}:{acct}:rule/{name}"}
    if rtype == "AWS::CloudFormation::WaitConditionHandle":
        return f"https://cloudformation-waitcondition-{region}.s3.amazonaws.com/{stack_name}/{_rand(16)}", {}
    if rtype == "AWS::CloudFormation::WaitCondition":
        return f"arn:aws:cloudformation:{region}:{acct}:stack/{stack_name}/{_rid()}/{logical}", {"Data": "{}"}
    if rtype == "AWS::CloudFormation::Stack":
        return f"arn:aws:cloudformation:{region}:{acct}:stack/{uniq}/{_rid()}", {}
    if rtype.startswith("Custom::") or rtype == "AWS::CloudFormation::CustomResource":
        return f"{stack_name}-{logical}-{_rand(8)}", {}
    if svc == "ec2" and short in _EC2_PREFIX:
        pid = f"{_EC2_PREFIX[short]}-{_rand(17)}"
        a = {}
        if short == "VPC":
            a = {"CidrBlock": props.get("CidrBlock", "10.0.0.0/16"), "VpcId": pid,
                 "DefaultSecurityGroup": "sg-" + _rand(17), "DefaultNetworkAcl": "acl-" + _rand(17)}
        elif short == "Subnet":
            a = {"AvailabilityZone": props.get("AvailabilityZone") or region + "a", "SubnetId": pid}
        elif short == "SecurityGroup":
            a = {"GroupId": pid, "VpcId": props.get("VpcId", "")}
        elif short == "Instance":
            a = {"PrivateIp": "10.0.0." + str(int(_rand(2), 16) % 250 + 4), "PublicIp": "54.0.0." + str(int(_rand(2), 16) % 250 + 4),
                 "PrivateDnsName": f"ip-10-0-0-4.{region}.compute.internal",
                 "PublicDnsName": f"ec2-54-0-0-4.{region}.compute.amazonaws.com",
                 "AvailabilityZone": region + "a"}
        return pid, a
    # generic
    phys = props.get("Name") or props.get(short + "Name") or uniq
    return phys, {"Arn": f"arn:aws:{svc}:{region}:{acct}:{short.lower()}/{phys}"}


# ── intrinsic evaluation ───────────────────────────────────────────────────
class _Ctx:
    def __init__(self, store, stack_name, stack_id, params, template, resources=None, conditions=None):
        self.store, self.stack_name, self.stack_id = store, stack_name, stack_id
        self.params = params                    # name -> value (list for list types)
        self.template = template
        self.resources = resources if resources is not None else {}   # logical -> rec
        self.conditions = conditions if conditions is not None else {}

    def pseudo(self, name):
        s = self.store
        return {"AWS::Region": s.region, "AWS::AccountId": s.account_id, "AWS::StackName": self.stack_name,
                "AWS::StackId": self.stack_id, "AWS::Partition": "aws", "AWS::URLSuffix": "amazonaws.com",
                "AWS::NotificationARNs": [], "AWS::NoValue": _NOVALUE}.get(name)


_NOVALUE = object()


def _is_intrinsic(v) -> bool:
    return isinstance(v, dict) and len(v) == 1 and (next(iter(v)).startswith("Fn::") or next(iter(v)) in ("Ref", "Condition"))


def _str(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return "" if v is None else str(v)


def _getatt(ctx: _Ctx, logical: str, attr: str):
    r = ctx.resources.get(logical)
    if r is None:
        raise _validation(f"Template format error: Unresolved resource dependencies [{logical}] in the Resources block of the template")
    if attr in r["attrs"]:
        return r["attrs"][attr]
    if attr in ("Ref",):
        return r["physical"]
    raise _validation(f"Template error: resource {logical} does not support attribute type {attr} in Fn::GetAtt")


def evaluate(v, ctx: _Ctx):
    if isinstance(v, list):
        return [x for x in (evaluate(i, ctx) for i in v) if x is not _NOVALUE]
    if not isinstance(v, dict):
        return v
    if len(v) == 1:
        k, arg = next(iter(v.items()))
        if k == "Ref":
            if arg in ctx.params:
                return ctx.params[arg]
            if isinstance(arg, str) and arg.startswith("AWS::"):
                return ctx.pseudo(arg)
            if arg in ctx.resources:
                return ctx.resources[arg]["physical"]
            raise _validation(f"Template format error: Unresolved resource dependencies [{arg}] in the Resources block of the template")
        if k == "Fn::GetAtt":
            if isinstance(arg, str):
                lg, _, at = arg.partition(".")
            else:
                lg, at = arg[0], evaluate(arg[1], ctx)
            return _getatt(ctx, lg, at)
        if k == "Fn::Join":
            d, parts = arg
            return evaluate(d, ctx).join(_str(x) for x in evaluate(parts, ctx))
        if k == "Fn::Sub":
            if isinstance(arg, list):
                tmpl, extra = arg[0], {a: evaluate(b, ctx) for a, b in arg[1].items()}
            else:
                tmpl, extra = arg, {}

            def rep(m):
                name = m.group(1)
                if name.startswith("!"):
                    return "${" + name[1:] + "}"
                if name in extra:
                    return _str(extra[name])
                if "." in name and name.split(".")[0] in ctx.resources:
                    return _str(_getatt(ctx, *name.split(".", 1)))
                return _str(evaluate({"Ref": name}, ctx))
            return re.sub(r"\$\{([^}]+)\}", rep, tmpl)
        if k == "Fn::Select":
            i, lst = evaluate(arg[0], ctx), evaluate(arg[1], ctx)
            try:
                return lst[int(i)]
            except Exception:
                raise _validation("Template error: Fn::Select cannot select nonexistent value at index " + _str(i))
        if k == "Fn::Split":
            return evaluate(arg[1], ctx).split(evaluate(arg[0], ctx))
        if k == "Fn::FindInMap":
            m, a, b = (evaluate(x, ctx) for x in arg)
            try:
                return ctx.template["Mappings"][m][a][b]
            except Exception:
                raise _validation(f"Template error: Unable to get mapping for {m}::{a}::{b}")
        if k == "Fn::If":
            c, a, b = arg
            return evaluate(a if _cond_value(ctx, c) else b, ctx)
        if k in ("Fn::Equals", "Fn::And", "Fn::Or", "Fn::Not") or k == "Condition":
            return _cond_eval(ctx, v)
        if k == "Fn::Base64":
            return base64.b64encode(_str(evaluate(arg, ctx)).encode()).decode()
        if k == "Fn::GetAZs":
            r = evaluate(arg, ctx) or ctx.store.region
            return [f"{r}a", f"{r}b", f"{r}c"]
        if k == "Fn::ImportValue":
            name = evaluate(arg, ctx)
            exp = exports_of(ctx.store).get(name)
            if exp is None:
                raise _validation(f"No export named {name} found.")
            return exp["Value"]
        if k == "Fn::Length":
            return len(evaluate(arg, ctx))
        if k == "Fn::ToJsonString":
            return json.dumps(evaluate(arg, ctx), separators=(",", ":"))
        if k == "Fn::Cidr":
            block, count, bits = (evaluate(x, ctx) for x in arg)
            net = ipaddress.ip_network(block)
            size = 2 ** (net.max_prefixlen - int(bits))
            return [str(ipaddress.ip_network((int(net.network_address) + i * size, net.max_prefixlen - int(bits))))
                    for i in range(int(count))]
        if k == "Fn::Transform":
            raise _validation("Template error: Fn::Transform (macros) is not supported by the simulator")
    return {kk: x for kk, x in ((kk, evaluate(vv, ctx)) for kk, vv in v.items()) if x is not _NOVALUE}


def _cond_value(ctx: _Ctx, name):
    if isinstance(name, dict):
        return _cond_eval(ctx, name)
    if name not in ctx.conditions:
        raise _validation(f"Template format error: Unresolved condition dependency {name} in Resource block")
    return ctx.conditions[name]


def _cond_eval(ctx: _Ctx, c) -> bool:
    if not isinstance(c, dict):
        return bool(c)
    k, a = next(iter(c.items()))
    if k == "Condition":
        return _cond_value(ctx, a)
    if k == "Fn::Equals":
        return evaluate(a[0], ctx) == evaluate(a[1], ctx)
    if k == "Fn::And":
        return all(_cond_eval(ctx, x) if isinstance(x, dict) and next(iter(x)).startswith(("Fn::", "Condition")) else bool(evaluate(x, ctx)) for x in a)
    if k == "Fn::Or":
        return any(_cond_eval(ctx, x) if isinstance(x, dict) and next(iter(x)).startswith(("Fn::", "Condition")) else bool(evaluate(x, ctx)) for x in a)
    if k == "Fn::Not":
        return not _cond_eval(ctx, a[0])
    return bool(evaluate(c, ctx))


def _refs(v, out: set) -> None:
    """Logical names referenced by Ref / GetAtt / Sub inside a property tree."""
    if isinstance(v, list):
        for i in v:
            _refs(i, out)
    elif isinstance(v, dict):
        for k, a in v.items():
            if k == "Ref" and isinstance(a, str):
                out.add(a)
            elif k == "Fn::GetAtt":
                out.add(a.split(".")[0] if isinstance(a, str) else a[0])
            elif k == "Fn::Sub":
                t = a if isinstance(a, str) else a[0]
                for m in re.findall(r"\$\{([^}!]+)\}", t):
                    out.add(m.split(".")[0])
                if isinstance(a, list):
                    _refs(a[1], out)
            else:
                _refs(a, out)


def _order(resources: dict) -> list[str]:
    deps = {}
    for lg, r in resources.items():
        s: set = set()
        _refs(r.get("Properties", {}), s)
        dep_on = r.get("DependsOn") or []
        s.update([dep_on] if isinstance(dep_on, str) else dep_on)
        deps[lg] = {d for d in s if d in resources and d != lg}
    order, state = [], {}

    def visit(n, path):
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            raise _validation("Circular dependency between resources: [" + ", ".join(path + [n]) + "]")
        state[n] = 1
        for d in sorted(deps[n]):
            visit(d, path + [n])
        state[n] = 2
        order.append(n)
    for n in resources:
        visit(n, [])
    return order


# ── exports ────────────────────────────────────────────────────────────────
def exports_of(store: CfnStore) -> dict:
    out = {}
    for sid, st in store.stacks.items():
        if st["StackStatus"] in ("DELETE_COMPLETE", "ROLLBACK_COMPLETE", "CREATE_FAILED", "REVIEW_IN_PROGRESS"):
            continue
        for o in st.get("Outputs", []):
            if o.get("ExportName"):
                out[o["ExportName"]] = {"ExportingStackId": sid, "Name": o["ExportName"], "Value": o["OutputValue"]}
    return out


def _imports_of(store: CfnStore, export_name: str) -> list[str]:
    names = []
    for st in store.stacks.values():
        if st["StackStatus"] == "DELETE_COMPLETE":
            continue
        if export_name in st.get("_imports", []):
            names.append(st["StackName"])
    return sorted(names)


# ── stack engine ───────────────────────────────────────────────────────────
def _resolve_params(tmpl: dict, given: dict, previous: dict | None = None, use_prev: set | None = None):
    declared = tmpl.get("Parameters") or {}
    if not isinstance(declared, dict):
        raise _validation("Template format error: Parameters must be a map")
    unknown = [k for k in given if k not in declared]
    if unknown:
        raise _validation(f"Parameters: [{', '.join(unknown)}] do not exist in the template")
    values, missing, display = {}, [], []
    for name, spec in declared.items():
        ptype = (spec or {}).get("Type", "String")
        if name in given and not (use_prev and name in use_prev):
            val = given[name]
        elif previous is not None and name in previous and (use_prev is None or name in use_prev or name not in given):
            val = previous[name]
        elif "Default" in (spec or {}):
            val = spec["Default"]
        else:
            missing.append(name)
            continue
        allowed = (spec or {}).get("AllowedValues")
        if allowed and _str(val) not in [_str(a) for a in allowed]:
            raise _validation(f"Parameter '{name}' must be one of AllowedValues")
        if ptype == "Number":
            try:
                float(val)
            except Exception:
                raise _validation(f"Parameter '{name}' must be a number")
        for lim, fn in (("MinLength", lambda a, b: len(a) >= int(b)), ("MaxLength", lambda a, b: len(a) <= int(b))):
            if lim in (spec or {}) and not fn(_str(val), spec[lim]):
                raise _validation(f"Parameter '{name}' must {'be at least' if lim == 'MinLength' else 'be at most'} {spec[lim]} characters")
        if ptype.startswith("List<") or ptype == "CommaDelimitedList":
            val = [x.strip() for x in _str(val).split(",")] if not isinstance(val, list) else val
        elif ptype != "Number":
            val = _str(val)
        else:
            val = _str(val)
        values[name] = val
        display.append({"ParameterKey": name,
                        "ParameterValue": "****" if (spec or {}).get("NoEcho") in (True, "true") else (",".join(val) if isinstance(val, list) else val)})
    if missing:
        raise _validation(f"Parameters: [{', '.join(missing)}] must have values")
    return values, display


def _event(stack: dict, logical: str, physical: str, rtype: str, status: str, reason: str = "", props=None) -> None:
    ev = {"StackId": stack["StackId"], "EventId": _rid(), "StackName": stack["StackName"],
          "LogicalResourceId": logical, "PhysicalResourceId": physical, "ResourceType": rtype,
          "Timestamp": _now(), "ResourceStatus": status}
    if reason:
        ev["ResourceStatusReason"] = reason
    if props is not None:
        ev["ResourceProperties"] = json.dumps(props)
    stack["_events"].insert(0, ev)


def _set_status(stack: dict, status: str, reason: str = "") -> None:
    stack["StackStatus"] = status
    if reason:
        stack["StackStatusReason"] = reason
    elif "StackStatusReason" in stack:
        del stack["StackStatusReason"]
    _event(stack, stack["StackName"], stack["StackId"], "AWS::CloudFormation::Stack", status, reason)


def _check_capabilities(tmpl: dict, caps: list[str]) -> None:
    res = tmpl.get("Resources") or {}
    types = {r.get("Type") for r in res.values() if isinstance(r, dict)}
    iam = sorted(t for t in types if t in IAM_TYPES)
    if not iam:
        return
    named = any(r.get("Type") in NAMED_IAM_PROPS and NAMED_IAM_PROPS[r["Type"]] in (r.get("Properties") or {})
                for r in res.values() if isinstance(r, dict))
    if "CAPABILITY_NAMED_IAM" in caps or ("CAPABILITY_IAM" in caps and not named):
        return
    need = "CAPABILITY_NAMED_IAM" if named else "CAPABILITY_IAM"
    raise CfnError("InsufficientCapabilitiesException",
                   f"Requires capabilities : [{need}]")


def _provision(store: CfnStore, stack: dict, tmpl: dict, params: dict, only: set | None = None, reuse: dict | None = None,
               action: str = "CREATE"):
    """Evaluate + 'create' the template's resources in dependency order.
    -> (resources {logical: rec}, failed_logical_or_None, reason)."""
    ctx = _Ctx(store, stack["StackName"], stack["StackId"], params, tmpl)
    for cname, cexpr in (tmpl.get("Conditions") or {}).items():
        ctx.conditions[cname] = _cond_eval(ctx, cexpr)
    all_res = tmpl.get("Resources") or {}
    if not isinstance(all_res, dict) or not all_res:
        raise _validation("Template format error: At least one Resources member must be defined.")
    live = {}
    for lg, r in all_res.items():
        if not isinstance(r, dict) or "Type" not in r:
            raise _validation(f"Template format error: [/Resources/{lg}] Every Resources object must contain a Type member.")
        cond = r.get("Condition")
        if cond and not _cond_value(ctx, cond):
            continue
        live[lg] = r
    order = _order(live)
    done = {}
    ctx.resources = done
    progress = f"{action}_IN_PROGRESS"
    for lg in order:
        r = live[lg]
        rtype = r["Type"]
        props = evaluate(r.get("Properties") or {}, ctx)
        prev = (reuse or {}).get(lg)
        unchanged = prev is not None and prev["type"] == rtype and prev["props"] == props
        if unchanged:
            done[lg] = dict(prev)
            continue
        _event(stack, lg, prev["physical"] if prev else "", rtype, progress, "", props)
        valid = rtype.startswith(("AWS::", "Custom::", "Alexa::")) and rtype.count("::") >= 2 or rtype == "AWS::CloudFormation::CustomResource"
        if not valid:
            _event(stack, lg, "", rtype, f"{action}_FAILED", f"Template format error: Unrecognized resource types: [{rtype}]")
            return done, lg, f"Template format error: Unrecognized resource types: [{rtype}]"
        out = None
        if store.provision:
            try:
                out = store.provision(rtype, lg, props, {"stack": stack["StackName"], "region": store.region})
            except CfnError as e:
                _event(stack, lg, "", rtype, f"{action}_FAILED", e.message, props)
                return done, lg, e.message
        if out is None:
            if prev and prev["type"] == rtype:
                phys, attrs = prev["physical"], prev["attrs"]
            else:
                phys, attrs = _simulate_resource(store, stack["StackName"], lg, rtype, props)
        else:
            phys, attrs = out
        done[lg] = {"type": rtype, "props": props, "physical": phys, "attrs": attrs,
                    "status": f"{action}_COMPLETE", "ts": _now(), "metadata": r.get("Metadata"),
                    "depends_on": r.get("DependsOn")}
        _event(stack, lg, phys, rtype, f"{action}_COMPLETE", "", props)
    return done, None, ""


def _outputs(store, stack, tmpl, params, resources) -> list[dict]:
    ctx = _Ctx(store, stack["StackName"], stack["StackId"], params, tmpl, resources)
    for cname, cexpr in (tmpl.get("Conditions") or {}).items():
        ctx.conditions[cname] = _cond_eval(ctx, cexpr)
    outs = []
    for name, spec in (tmpl.get("Outputs") or {}).items():
        if spec.get("Condition") and not _cond_value(ctx, spec["Condition"]):
            continue
        o = {"OutputKey": name, "OutputValue": _str(evaluate(spec.get("Value"), ctx))}
        if spec.get("Description"):
            o["Description"] = spec["Description"]
        if spec.get("Export"):
            o["ExportName"] = _str(evaluate(spec["Export"].get("Name"), ctx))
        outs.append(o)
    return outs


def _collect_imports(tmpl: dict) -> list[str]:
    found: list[str] = []

    def walk(v):
        if isinstance(v, dict):
            for k, a in v.items():
                if k == "Fn::ImportValue" and isinstance(a, str):
                    found.append(a)
                else:
                    walk(a)
        elif isinstance(v, list):
            for i in v:
                walk(i)
    walk(tmpl.get("Resources") or {})
    walk(tmpl.get("Outputs") or {})
    return found


def _get_template_text(store: CfnStore, a: dict) -> str:
    if a.get("TemplateBody"):
        return a["TemplateBody"]
    if a.get("TemplateURL"):
        if store.fetch_url:
            try:
                return store.fetch_url(a["TemplateURL"])
            except Exception as e:
                raise _validation(f"S3 error: could not fetch {a['TemplateURL']}: {e}")
        raise _validation("S3 error: TemplateURL cannot be fetched in this environment; use TemplateBody")
    raise _validation("Either Template URL or Template Body must be specified.")


def _find_stack(store: CfnStore, name_or_id: str | None, include_deleted: bool = False) -> dict:
    if not name_or_id:
        raise _validation("Stack name or id is required")
    if name_or_id.startswith("arn:"):
        st = store.stacks.get(name_or_id)
        if st:
            return st
    else:
        live = [s for s in store.stacks.values() if s["StackName"] == name_or_id and s["StackStatus"] != "DELETE_COMPLETE"]
        if live:
            return live[0]
    raise _validation(f"Stack with id {name_or_id} does not exist")


def _public_stack(st: dict) -> dict:
    return {k: v for k, v in st.items() if not k.startswith("_")}


def _tags(a: dict) -> list[dict]:
    return [{"Key": t.get("Key"), "Value": t.get("Value", "")} for t in (a.get("Tags") or [])]


def _param_map(a: dict) -> tuple[dict, set]:
    given, use_prev = {}, set()
    for p in a.get("Parameters") or []:
        k = p.get("ParameterKey")
        if p.get("UsePreviousValue") in (True, "true"):
            use_prev.add(k)
        else:
            given[k] = p.get("ParameterValue", "")
    return given, use_prev


def _caps(a: dict) -> list[str]:
    return list(a.get("Capabilities") or [])


def _validate_name(name: str) -> None:
    if not name or not re.fullmatch(r"[a-zA-Z][-a-zA-Z0-9]*", name) or len(name) > 128:
        raise _validation(f"1 validation error detected: Value '{name}' at 'stackName' failed to satisfy constraint: "
                          "Member must satisfy regular expression pattern: [a-zA-Z][-a-zA-Z0-9]*|arn:[-a-zA-Z0-9:/._+]*")


def _apply_exports(store: CfnStore, stack: dict, outputs: list[dict]) -> None:
    mine = exports_of(store)
    for o in outputs:
        n = o.get("ExportName")
        if n and n in mine and mine[n]["ExportingStackId"] != stack["StackId"]:
            raise _validation(f"Export with name {n} is already exported by stack {mine[n]['ExportingStackId']}")


def _new_stack(store: CfnStore, a: dict, name: str, status_inprogress: str = "CREATE_IN_PROGRESS") -> dict:
    sid = f"arn:aws:cloudformation:{store.region}:{store.account_id}:stack/{name}/{_rid()}"
    st = {"StackId": sid, "StackName": name, "CreationTime": _now(), "StackStatus": status_inprogress,
          "DisableRollback": a.get("DisableRollback") in (True, "true"), "NotificationARNs": list(a.get("NotificationARNs") or []),
          "Capabilities": _caps(a), "Tags": _tags(a), "EnableTerminationProtection": a.get("EnableTerminationProtection") in (True, "true"),
          "DriftInformation": {"StackDriftStatus": "NOT_CHECKED"}, "Parameters": [], "Outputs": [],
          "_events": [], "_resources": {}, "_template": "", "_params": {}, "_imports": []}
    if a.get("RoleARN"):
        st["RoleARN"] = a["RoleARN"]
    if a.get("TimeoutInMinutes"):
        st["TimeoutInMinutes"] = int(a["TimeoutInMinutes"])
    store.stacks[sid] = st
    return st


def _run_create(store: CfnStore, st: dict, a: dict, text: str, tmpl: dict, params: dict, display: list, action_ev: bool = True):
    st["_template"], st["_params"], st["Parameters"] = text, params, display
    if tmpl.get("Description"):
        st["Description"] = tmpl["Description"]
    st["_imports"] = _collect_imports(tmpl)
    _set_status(st, "CREATE_IN_PROGRESS", "User Initiated")
    resources, failed, reason = _provision(store, st, tmpl, params)
    if failed:
        st["_resources"] = resources
        if st["DisableRollback"]:
            _set_status(st, "CREATE_FAILED", reason)
        else:
            _set_status(st, "ROLLBACK_IN_PROGRESS", reason)
            for lg in reversed(list(resources)):
                r = resources[lg]
                _event(st, lg, r["physical"], r["type"], "DELETE_COMPLETE")
            st["_resources"] = {}
            _set_status(st, "ROLLBACK_COMPLETE")
        return
    outs = _outputs(store, st, tmpl, params, resources)
    try:
        _apply_exports(store, st, outs)
    except CfnError as e:
        st["_resources"] = {}
        _set_status(st, "ROLLBACK_COMPLETE", e.message)
        return
    st["_resources"], st["Outputs"] = resources, outs
    _set_status(st, "CREATE_COMPLETE")


def _check_imports_exist(store: CfnStore, tmpl: dict) -> None:
    ex = exports_of(store)
    for n in _collect_imports(tmpl):
        if n not in ex:
            raise _validation(f"No export named {n} found.")


# ── operations ─────────────────────────────────────────────────────────────
def op_create_stack(store, a):
    name = a.get("StackName", "")
    _validate_name(name)
    for s in store.stacks.values():
        if s["StackName"] == name and s["StackStatus"] != "DELETE_COMPLETE":
            raise CfnError("AlreadyExistsException", f"Stack [{name}] already exists")
    text = _get_template_text(store, a)
    tmpl = parse_template(text)
    given, _ = _param_map(a)
    params, display = _resolve_params(tmpl, given)
    _check_capabilities(tmpl, _caps(a))
    _check_imports_exist(store, tmpl)
    st = _new_stack(store, a, name)
    _run_create(store, st, a, text, tmpl, params, display)
    store.persist()
    return {"StackId": st["StackId"]}


def op_update_stack(store, a):
    st = _find_stack(store, a.get("StackName"))
    if st["StackStatus"].endswith("_IN_PROGRESS") or st["StackStatus"] in ("ROLLBACK_COMPLETE", "REVIEW_IN_PROGRESS", "CREATE_FAILED"):
        raise _validation(f"Stack:{st['StackId']} is in {st['StackStatus']} state and can not be updated.")
    if a.get("UsePreviousTemplate") in (True, "true"):
        text = st["_template"]
    else:
        text = _get_template_text(store, a)
    tmpl = parse_template(text)
    given, use_prev = _param_map(a)
    params, display = _resolve_params(tmpl, given, st["_params"], use_prev)
    _check_capabilities(tmpl, _caps(a) or st.get("Capabilities", []))
    _check_imports_exist(store, tmpl)
    if text == st["_template"] and params == st["_params"] and (not a.get("Tags") or _tags(a) == st["Tags"]):
        raise _validation("No updates are to be performed.")
    _apply_update(store, st, a, text, tmpl, params, display)
    store.persist()
    return {"StackId": st["StackId"]}


def _apply_update(store, st, a, text, tmpl, params, display):
    old_resources = st["_resources"]
    _set_status(st, "UPDATE_IN_PROGRESS", "User Initiated")
    resources, failed, reason = _provision(store, st, tmpl, params, reuse=old_resources, action="UPDATE")
    if failed:
        _set_status(st, "UPDATE_ROLLBACK_IN_PROGRESS", reason)
        _set_status(st, "UPDATE_ROLLBACK_COMPLETE")
        return
    for lg in reversed(list(old_resources)):
        if lg not in resources:
            r = old_resources[lg]
            _event(st, lg, r["physical"], r["type"], "DELETE_IN_PROGRESS")
            _event(st, lg, r["physical"], r["type"], "DELETE_COMPLETE")
    outs = _outputs(store, st, tmpl, params, resources)
    try:
        _apply_exports(store, st, outs)
        kept = {o["ExportName"] for o in outs if o.get("ExportName")}
        for o in st.get("Outputs", []):
            n = o.get("ExportName")
            if n and n not in kept and _imports_of(store, n):
                raise _validation(f"Cannot delete export {n} as it is in use by {', '.join(_imports_of(store, n))}.")
    except CfnError as e:
        _set_status(st, "UPDATE_ROLLBACK_COMPLETE", e.message)
        return
    st.update({"_template": text, "_params": params, "Parameters": display, "_resources": resources,
               "Outputs": outs, "LastUpdatedTime": _now(), "_imports": _collect_imports(tmpl)})
    if a.get("Tags"):
        st["Tags"] = _tags(a)
    if _caps(a):
        st["Capabilities"] = _caps(a)
    if tmpl.get("Description"):
        st["Description"] = tmpl["Description"]
    elif "Description" in st:
        del st["Description"]
    _set_status(st, "UPDATE_COMPLETE")


def op_delete_stack(store, a):
    name = a.get("StackName", "")
    if name.startswith("arn:"):
        st = store.stacks.get(name)
    else:
        st = next((s for s in store.stacks.values() if s["StackName"] == name and s["StackStatus"] != "DELETE_COMPLETE"), None)
    if st is None or st["StackStatus"] == "DELETE_COMPLETE":
        return {}   # DeleteStack of a missing stack succeeds (real behaviour)
    if st.get("EnableTerminationProtection"):
        raise _validation(f"Stack [{st['StackName']}] cannot be deleted while TerminationProtection is enabled")
    for o in st.get("Outputs", []):
        n = o.get("ExportName")
        users = [x for x in _imports_of(store, n) if x != st["StackName"]] if n else []
        if users:
            raise _validation(f"Cannot delete export {n} as it is in use by {', '.join(users)}.")
    _set_status(st, "DELETE_IN_PROGRESS", "User Initiated")
    for lg in reversed(list(st["_resources"])):
        r = st["_resources"][lg]
        _event(st, lg, r["physical"], r["type"], "DELETE_IN_PROGRESS")
        _event(st, lg, r["physical"], r["type"], "DELETE_COMPLETE")
    st["_resources"], st["Outputs"] = {}, []
    st["DeletionTime"] = _now()
    _set_status(st, "DELETE_COMPLETE")
    for cid in [c for c, cs in store.change_sets.items() if cs["StackId"] == st["StackId"]]:
        del store.change_sets[cid]
    store.persist()
    return {}


def op_describe_stacks(store, a):
    name = a.get("StackName")
    if name:
        if name.startswith("arn:"):
            st = store.stacks.get(name)
            found = [st] if st else []
        else:
            found = [s for s in store.stacks.values() if s["StackName"] == name and s["StackStatus"] != "DELETE_COMPLETE"]
        if not found:
            raise _validation(f"Stack with id {name} does not exist")
    else:
        found = [s for s in store.stacks.values() if s["StackStatus"] != "DELETE_COMPLETE"]
    return {"Stacks": [_public_stack(s) for s in found]}


def op_list_stacks(store, a):
    flt = set(a.get("StackStatusFilter") or [])
    out = []
    for s in store.stacks.values():
        if flt and s["StackStatus"] not in flt:
            continue
        item = {"StackId": s["StackId"], "StackName": s["StackName"], "CreationTime": s["CreationTime"],
                "StackStatus": s["StackStatus"], "DriftInformation": {"StackDriftStatus": "NOT_CHECKED"}}
        for k in ("LastUpdatedTime", "DeletionTime", "StackStatusReason"):
            if k in s:
                item[k] = s[k]
        if s.get("Description"):
            item["TemplateDescription"] = s["Description"]
        out.append(item)
    return {"StackSummaries": out}


def op_describe_stack_events(store, a):
    if a.get("StackName"):
        n = a["StackName"]
        st = store.stacks.get(n) if n.startswith("arn:") else None
        if st is None:
            st = next((s for s in store.stacks.values() if s["StackName"] == n and s["StackStatus"] != "DELETE_COMPLETE"), None)
        if st is None:
            raise _validation(f"Stack [{n}] does not exist")
        return {"StackEvents": st["_events"]}
    ev = [e for s in store.stacks.values() for e in s["_events"]]
    return {"StackEvents": sorted(ev, key=lambda e: e["Timestamp"], reverse=True)}


def _res_record(st, lg, r):
    return {"StackName": st["StackName"], "StackId": st["StackId"], "LogicalResourceId": lg,
            "PhysicalResourceId": r["physical"], "ResourceType": r["type"], "Timestamp": r["ts"],
            "ResourceStatus": r["status"], "DriftInformation": {"StackResourceDriftStatus": "NOT_CHECKED"}}


def op_describe_stack_resources(store, a):
    if a.get("StackName"):
        st = _find_stack(store, a["StackName"])
        res = [(st, lg, r) for lg, r in st["_resources"].items()]
    else:
        pid = a.get("PhysicalResourceId")
        res = [(s, lg, r) for s in store.stacks.values() for lg, r in s["_resources"].items() if r["physical"] == pid]
        if not res:
            raise _validation(f"Stack for {pid} does not exist")
    if a.get("LogicalResourceId"):
        res = [x for x in res if x[1] == a["LogicalResourceId"]]
    return {"StackResources": [_res_record(s, lg, r) for s, lg, r in res]}


def op_describe_stack_resource(store, a):
    st = _find_stack(store, a.get("StackName"))
    lg = a.get("LogicalResourceId")
    r = st["_resources"].get(lg)
    if r is None:
        raise _validation(f"Resource {lg} does not exist for stack {st['StackName']}")
    d = _res_record(st, lg, r)
    d["LastUpdatedTimestamp"] = d.pop("Timestamp")
    if r.get("metadata") is not None:
        d["Metadata"] = json.dumps(r["metadata"])
    return {"StackResourceDetail": d}


def op_list_stack_resources(store, a):
    st = _find_stack(store, a.get("StackName"))
    return {"StackResourceSummaries": [
        {"LogicalResourceId": lg, "PhysicalResourceId": r["physical"], "ResourceType": r["type"],
         "LastUpdatedTimestamp": r["ts"], "ResourceStatus": r["status"],
         "DriftInformation": {"StackResourceDriftStatus": "NOT_CHECKED"}}
        for lg, r in st["_resources"].items()]}


def op_get_template(store, a):
    if a.get("ChangeSetName"):
        cs = _find_change_set(store, a["ChangeSetName"], a.get("StackName"))
        return {"TemplateBody": cs["_template"], "StagesAvailable": ["Original", "Processed"]}
    st = _find_stack(store, a.get("StackName"))
    return {"TemplateBody": st["_template"], "StagesAvailable": ["Original", "Processed"]}


def _template_params(tmpl: dict) -> list[dict]:
    out = []
    for n, s in (tmpl.get("Parameters") or {}).items():
        s = s or {}
        p = {"ParameterKey": n}
        if "Default" in s:
            p["DefaultValue"] = _str(s["Default"])
        p["NoEcho"] = s.get("NoEcho") in (True, "true")
        if s.get("Description"):
            p["Description"] = s["Description"]
        out.append(p)
    return out


def _capabilities_of(tmpl: dict) -> tuple[list[str], str]:
    res = tmpl.get("Resources") or {}
    iam = [r.get("Type") for r in res.values() if isinstance(r, dict) and r.get("Type") in IAM_TYPES]
    if not iam:
        return [], ""
    named = any(r.get("Type") in NAMED_IAM_PROPS and NAMED_IAM_PROPS[r["Type"]] in (r.get("Properties") or {}) for r in res.values())
    return (["CAPABILITY_NAMED_IAM"] if named else ["CAPABILITY_IAM"],
            "The following resource(s) require capabilities: [" + ", ".join(sorted(set(iam))) + "]")


def op_validate_template(store, a):
    tmpl = parse_template(_get_template_text(store, a))
    if not isinstance(tmpl.get("Resources"), dict) or not tmpl["Resources"]:
        raise _validation("Template format error: At least one Resources member must be defined.")
    for lg, r in tmpl["Resources"].items():
        if not isinstance(r, dict) or "Type" not in r:
            raise _validation(f"Template format error: [/Resources/{lg}] Every Resources object must contain a Type member.")
    _order({k: v for k, v in tmpl["Resources"].items()})
    caps, why = _capabilities_of(tmpl)
    out = {"Parameters": _template_params(tmpl)}
    if tmpl.get("Description"):
        out["Description"] = tmpl["Description"]
    out["Capabilities"] = caps
    if why:
        out["CapabilitiesReason"] = why
    return out


def op_get_template_summary(store, a):
    if a.get("StackName"):
        tmpl = parse_template(_find_stack(store, a["StackName"])["_template"])
    else:
        tmpl = parse_template(_get_template_text(store, a))
    res = tmpl.get("Resources") or {}
    caps, why = _capabilities_of(tmpl)
    params = []
    for p in _template_params(tmpl):
        spec = (tmpl.get("Parameters") or {}).get(p["ParameterKey"]) or {}
        p["ParameterType"] = spec.get("Type", "String")
        params.append(p)
    out = {"Parameters": params, "Capabilities": caps}
    if why:
        out["CapabilitiesReason"] = why
    out["ResourceTypes"] = sorted({r.get("Type") for r in res.values() if isinstance(r, dict)})
    out["Version"] = tmpl.get("AWSTemplateFormatVersion", "2010-09-09")
    if tmpl.get("Description"):
        out["Description"] = tmpl["Description"]
    if tmpl.get("Metadata"):
        out["Metadata"] = json.dumps(tmpl["Metadata"])
    return out


def op_list_exports(store, a):
    return {"Exports": list(exports_of(store).values())}


def op_list_imports(store, a):
    name = a.get("ExportName", "")
    if name not in exports_of(store):
        raise _validation(f"Export '{name}' does not exist")
    return {"Imports": _imports_of(store, name)}


def op_update_termination_protection(store, a):
    st = _find_stack(store, a.get("StackName"))
    st["EnableTerminationProtection"] = a.get("EnableTerminationProtection") in (True, "true")
    store.persist()
    return {"StackId": st["StackId"]}


def op_set_stack_policy(store, a):
    st = _find_stack(store, a.get("StackName"))
    st["_policy"] = a.get("StackPolicyBody") or ""
    store.persist()
    return None


def op_get_stack_policy(store, a):
    st = _find_stack(store, a.get("StackName"))
    return {"StackPolicyBody": st["_policy"]} if st.get("_policy") else {}


def op_cancel_update_stack(store, a):
    st = _find_stack(store, a.get("StackName"))
    if st["StackStatus"] != "UPDATE_IN_PROGRESS":
        raise _validation(f"CancelUpdateStack cannot be called from current stack status")
    return None


def op_describe_account_limits(store, a):
    return {"AccountLimits": [{"Name": "StackLimit", "Value": 2000}, {"Name": "StackOutputsLimit", "Value": 200}]}


# ── change sets ────────────────────────────────────────────────────────────
def _find_change_set(store, name_or_id, stack_name=None):
    if name_or_id and name_or_id.startswith("arn:") and name_or_id in store.change_sets:
        return store.change_sets[name_or_id]
    for cs in store.change_sets.values():
        if cs["ChangeSetName"] == name_or_id and (not stack_name or stack_name in (cs["StackName"], cs["StackId"])):
            return cs
    raise CfnError("ChangeSetNotFound", f"ChangeSet [{name_or_id}] does not exist", 404)


def _diff(old: dict, new_tmpl: dict, params: dict, store, st) -> list[dict]:
    ctx = _Ctx(store, st["StackName"], st["StackId"], params, new_tmpl)
    for cname, cexpr in (new_tmpl.get("Conditions") or {}).items():
        ctx.conditions[cname] = _cond_eval(ctx, cexpr)
    new = {lg: r for lg, r in (new_tmpl.get("Resources") or {}).items()
           if not r.get("Condition") or _cond_value(ctx, r["Condition"])}
    changes = []
    for lg, r in new.items():
        if lg not in old:
            changes.append({"Type": "Resource", "ResourceChange": {"Action": "Add", "LogicalResourceId": lg, "ResourceType": r["Type"],
                                                                   "Scope": [], "Details": []}})
            continue
        o = old[lg]
        raw_new = r.get("Properties") or {}
        if o["type"] != r["Type"]:
            changes.append({"Type": "Resource", "ResourceChange": {
                "Action": "Modify", "LogicalResourceId": lg, "PhysicalResourceId": o["physical"], "ResourceType": r["Type"],
                "Replacement": "True", "Scope": ["Properties"], "Details": []}})
            continue
        try:
            ev_new = evaluate(raw_new, _Ctx(store, st["StackName"], st["StackId"], params, new_tmpl, {k: v for k, v in old.items()}, ctx.conditions))
        except CfnError:
            ev_new = raw_new
        if ev_new != o["props"]:
            keys = sorted({k for k in set(ev_new) | set(o["props"]) if ev_new.get(k) != o["props"].get(k)})
            changes.append({"Type": "Resource", "ResourceChange": {
                "Action": "Modify", "LogicalResourceId": lg, "PhysicalResourceId": o["physical"], "ResourceType": r["Type"],
                "Replacement": "False", "Scope": ["Properties"],
                "Details": [{"Target": {"Attribute": "Properties", "Name": k, "RequiresRecreation": "Never"},
                             "Evaluation": "Static", "ChangeSource": "DirectModification"} for k in keys]}})
    for lg, o in old.items():
        if lg not in new:
            changes.append({"Type": "Resource", "ResourceChange": {
                "Action": "Remove", "LogicalResourceId": lg, "PhysicalResourceId": o["physical"], "ResourceType": o["type"],
                "Scope": [], "Details": []}})
    return changes


def op_create_change_set(store, a):
    name = a.get("ChangeSetName", "")
    if not name or not re.fullmatch(r"[a-zA-Z][-a-zA-Z0-9]*", name):
        raise _validation(f"1 validation error detected: Value '{name}' at 'changeSetName' failed to satisfy constraint: "
                          "Member must satisfy regular expression pattern: [a-zA-Z][-a-zA-Z0-9]*")
    ctype = a.get("ChangeSetType") or "UPDATE"
    if ctype not in ("CREATE", "UPDATE", "IMPORT"):
        raise _validation(f"Value '{ctype}' at 'changeSetType' failed to satisfy constraint: Member must satisfy enum value set: [CREATE, UPDATE, IMPORT]")
    sname = a.get("StackName", "")
    if a.get("UsePreviousTemplate") in (True, "true"):
        text = _find_stack(store, sname)["_template"]
    else:
        text = _get_template_text(store, a)
    tmpl = parse_template(text)
    given, use_prev = _param_map(a)
    if ctype == "CREATE":
        _validate_name(sname)
        for s in store.stacks.values():
            if s["StackName"] == sname and s["StackStatus"] != "DELETE_COMPLETE":
                raise CfnError("AlreadyExistsException", f"Stack [{sname}] already exists and cannot be created again with the changeSet [{name}].")
        params, display = _resolve_params(tmpl, given)
        st = _new_stack(store, a, sname, "REVIEW_IN_PROGRESS")
        st["_events"] = []
        _event(st, sname, st["StackId"], "AWS::CloudFormation::Stack", "REVIEW_IN_PROGRESS", "User Initiated")
        old = {}
    else:
        st = _find_stack(store, sname)
        params, display = _resolve_params(tmpl, given, st["_params"], use_prev)
        old = st["_resources"]
    for cs in store.change_sets.values():
        if cs["StackId"] == st["StackId"] and cs["ChangeSetName"] == name:
            raise CfnError("AlreadyExistsException", f"ChangeSet [{name}] already exists.")
    _check_capabilities(tmpl, _caps(a) or st.get("Capabilities", []))
    changes = _diff(old, tmpl, params, store, st)
    cid = f"arn:aws:cloudformation:{store.region}:{store.account_id}:changeSet/{name}/{_rid()}"
    no_changes = not changes and ctype == "UPDATE"
    cs = {"ChangeSetId": cid, "ChangeSetName": name, "StackId": st["StackId"], "StackName": st["StackName"],
          "CreationTime": _now(), "ExecutionStatus": "UNAVAILABLE" if no_changes else "AVAILABLE",
          "Status": "FAILED" if no_changes else "CREATE_COMPLETE", "Parameters": display, "Capabilities": _caps(a),
          "Tags": _tags(a), "Changes": changes, "IncludeNestedStacks": False,
          "_template": text, "_params": params, "_type": ctype}
    if no_changes:
        cs["StatusReason"] = "The submitted information didn't contain changes. Submit different information to create a change set."
    if a.get("Description"):
        cs["Description"] = a["Description"]
    store.change_sets[cid] = cs
    store.persist()
    return {"Id": cid, "StackId": st["StackId"]}


def op_describe_change_set(store, a):
    cs = _find_change_set(store, a.get("ChangeSetName"), a.get("StackName"))
    return {k: v for k, v in cs.items() if not k.startswith("_")}


def op_list_change_sets(store, a):
    st = _find_stack(store, a.get("StackName"))
    out = []
    for cs in store.change_sets.values():
        if cs["StackId"] != st["StackId"]:
            continue
        item = {k: cs[k] for k in ("StackId", "StackName", "ChangeSetId", "ChangeSetName", "ExecutionStatus", "Status", "CreationTime")}
        for k in ("StatusReason", "Description"):
            if k in cs:
                item[k] = cs[k]
        out.append(item)
    return {"Summaries": out}


def op_delete_change_set(store, a):
    cs = _find_change_set(store, a.get("ChangeSetName"), a.get("StackName"))
    st = store.stacks.get(cs["StackId"])
    del store.change_sets[cs["ChangeSetId"]]
    if st and st["StackStatus"] == "REVIEW_IN_PROGRESS" and not any(c["StackId"] == st["StackId"] for c in store.change_sets.values()):
        pass   # real CFN keeps the REVIEW_IN_PROGRESS shell until deleted
    store.persist()
    return {}


def op_execute_change_set(store, a):
    cs = _find_change_set(store, a.get("ChangeSetName"), a.get("StackName"))
    if cs["ExecutionStatus"] != "AVAILABLE":
        raise CfnError("InvalidChangeSetStatus", f"ChangeSet [{cs['ChangeSetId']}] cannot be executed in its current status of [{cs['Status']}]")
    st = store.stacks[cs["StackId"]]
    tmpl = parse_template(cs["_template"])
    params = cs["_params"]
    display = cs["Parameters"]
    if cs["_type"] == "CREATE":
        st["Capabilities"], st["Tags"] = cs["Capabilities"], cs["Tags"]
        _run_create(store, st, {}, cs["_template"], tmpl, params, display)
    else:
        _apply_update(store, st, {"Tags": cs["Tags"], "Capabilities": cs["Capabilities"]}, cs["_template"], tmpl, params, display)
    cs["ExecutionStatus"] = "EXECUTE_COMPLETE" if st["StackStatus"].endswith("_COMPLETE") and "ROLLBACK" not in st["StackStatus"] else "EXECUTE_FAILED"
    for other in store.change_sets.values():
        if other["StackId"] == st["StackId"] and other is not cs and other["ExecutionStatus"] == "AVAILABLE":
            other["ExecutionStatus"] = "OBSOLETE"
    store.persist()
    return {}


# ── stack sets (metadata level) ────────────────────────────────────────────
def op_create_stack_set(store, a):
    n = a.get("StackSetName", "")
    if n in store.stack_sets:
        raise CfnError("NameAlreadyExistsException", f"StackSet [{n}] already exists")
    text = _get_template_text(store, a)
    tmpl = parse_template(text)
    sid = f"{n}:{_rid()}"
    store.stack_sets[n] = {"StackSetName": n, "StackSetId": sid, "Status": "ACTIVE", "TemplateBody": text,
                           "Description": a.get("Description") or tmpl.get("Description", ""),
                           "Parameters": [{"ParameterKey": p["ParameterKey"], "ParameterValue": p.get("ParameterValue", "")}
                                          for p in a.get("Parameters") or []],
                           "Capabilities": _caps(a), "Tags": _tags(a),
                           "StackSetARN": f"arn:aws:cloudformation:{store.region}:{store.account_id}:stackset/{sid}",
                           "PermissionModel": a.get("PermissionModel") or "SELF_MANAGED",
                           "StackSetDriftDetectionDetails": {"DriftStatus": "NOT_CHECKED", "TotalStackInstancesCount": 0}}
    store.persist()
    return {"StackSetId": sid}


def _find_stack_set(store, n):
    ss = store.stack_sets.get(n) or next((s for s in store.stack_sets.values() if s["StackSetId"] == n), None)
    if not ss:
        raise CfnError("StackSetNotFoundException", f"StackSet {n} not found", 404)
    return ss


def op_describe_stack_set(store, a):
    return {"StackSet": _find_stack_set(store, a.get("StackSetName"))}


def op_list_stack_sets(store, a):
    return {"Summaries": [{"StackSetName": s["StackSetName"], "StackSetId": s["StackSetId"], "Description": s["Description"],
                           "Status": s["Status"], "PermissionModel": s["PermissionModel"],
                           "DriftStatus": "NOT_CHECKED"} for s in store.stack_sets.values()
                          if not a.get("Status") or s["Status"] == a["Status"]]}


def op_delete_stack_set(store, a):
    ss = _find_stack_set(store, a.get("StackSetName"))
    del store.stack_sets[ss["StackSetName"]]
    store.persist()
    return {}


_OPS = {
    "CreateStack": op_create_stack, "UpdateStack": op_update_stack, "DeleteStack": op_delete_stack,
    "DescribeStacks": op_describe_stacks, "ListStacks": op_list_stacks,
    "DescribeStackEvents": op_describe_stack_events, "DescribeStackResources": op_describe_stack_resources,
    "DescribeStackResource": op_describe_stack_resource, "ListStackResources": op_list_stack_resources,
    "GetTemplate": op_get_template, "GetTemplateSummary": op_get_template_summary,
    "ValidateTemplate": op_validate_template, "ListExports": op_list_exports, "ListImports": op_list_imports,
    "UpdateTerminationProtection": op_update_termination_protection,
    "SetStackPolicy": op_set_stack_policy, "GetStackPolicy": op_get_stack_policy,
    "CancelUpdateStack": op_cancel_update_stack, "DescribeAccountLimits": op_describe_account_limits,
    "CreateChangeSet": op_create_change_set, "DescribeChangeSet": op_describe_change_set,
    "ListChangeSets": op_list_change_sets, "DeleteChangeSet": op_delete_change_set,
    "ExecuteChangeSet": op_execute_change_set,
    "CreateStackSet": op_create_stack_set, "DescribeStackSet": op_describe_stack_set,
    "ListStackSets": op_list_stack_sets, "DeleteStackSet": op_delete_stack_set,
}
OPERATIONS = sorted(_OPS)


# ── wire: Query-protocol request → nested args, results → XML ──────────────
def unflatten(params: dict) -> dict:
    """`Parameters.member.1.ParameterKey=K` → {"Parameters": [{"ParameterKey": "K"}]}."""
    tree: dict = {}
    for k, v in params.items():
        parts = k.split(".")
        node = tree
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v

    def fix(n):
        if not isinstance(n, dict):
            return n
        n = {k: fix(v) for k, v in n.items()}
        if set(n) == {"member"}:
            m = n["member"]
            return m if isinstance(m, list) else [m]
        if n and all(k.isdigit() for k in n):
            return [n[k] for k in sorted(n, key=int)]
        return n
    return fix(tree)


def _x(tag: str, v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return f"<{tag}>{'true' if v else 'false'}</{tag}>"
    if isinstance(v, dict):
        return f"<{tag}>" + "".join(_x(k, x) for k, x in v.items()) + f"</{tag}>"
    if isinstance(v, list):
        return f"<{tag}>" + "".join(_x("member", i) for i in v) + f"</{tag}>"
    return f"<{tag}>{_xml_escape(str(v))}</{tag}>"


def _envelope(action: str, result: dict | None) -> CfnResponse:
    inner = "".join(_x(k, v) for k, v in (result or {}).items())
    res = f"<{action}Result>{inner}</{action}Result>" if result is not None else ""
    xml = ('<?xml version="1.0" encoding="UTF-8"?>' f'<{action}Response xmlns="{CFN_NS}">{res}'
           f'<ResponseMetadata><RequestId>{_rid()}</RequestId></ResponseMetadata></{action}Response>')
    return CfnResponse(body=xml)


def _error(code: str, message: str, status: int = 400) -> CfnResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>' f'<ErrorResponse xmlns="{CFN_NS}">'
           f'<Error><Type>Sender</Type><Code>{_xml_escape(code)}</Code><Message>{_xml_escape(message)}</Message></Error>'
           f'<RequestId>{_rid()}</RequestId></ErrorResponse>')
    return CfnResponse(status=status, body=xml)


def dispatch(store: CfnStore, params: dict | None = None) -> CfnResponse:
    params = params if isinstance(params, dict) else {}
    action = str(params.get("Action", "")).strip()
    op = _OPS.get(action)
    if op is None:
        return _error("InvalidAction", f"Could not find operation {action} for version {params.get('Version', '2010-05-15')}", 400)
    args = unflatten({k: v for k, v in params.items() if k not in ("Action", "Version")})
    try:
        result = op(store, args)
    except CfnError as e:
        return _error(e.code, e.message, e.status)
    if result is None and action in ("SetStackPolicy", "CancelUpdateStack", "DeleteStack"):
        return _envelope(action, None)
    return _envelope(action, result if result is not None else {})
