"""ELBv2 core — substrate-independent engine for the AWS Elastic Load Balancing v2 API.

Targets the NATIVE ELBv2 wire — the **Query protocol** (form-encoded
`Action=CreateLoadBalancer&Version=2015-12-01&...`, XML responses in
http://elasticloadbalancing.amazonaws.com/doc/2015-12-01/) — so an unmodified
boto3 / aws-cli / aws-sdk-java-v2 / aws-sdk-go-v2 client works with only the
endpoint overridden. Request / response field names and error codes follow the
botocore model (`elbv2/2015-12-01/service-2.json`).

Pure Python (stdlib only — no fastapi / boto3 / socket), so the SAME file runs on
the offline appliance and in Nano (Pyodide). State lives in an `Elbv2Store` (plain
dicts, a `persist()` hook) — the seam the offline appliance backs with the
space-scoped state and Nano backs with its shared store registry.

Backend: in-process. The engine models load balancers, listeners, rules, target
groups and target health; target health is deterministic (a registered target is
`healthy` once its target group is attached to a listener, `unused` before) so
waiters and health dashboards behave without a real L7 data plane.

Operations: Create/Describe/Delete LoadBalancer (+ attributes, SetSubnets,
SetSecurityGroups, SetIpAddressType), Create/Describe/Modify/Delete TargetGroup
(+ attributes), Register/Deregister Targets, DescribeTargetHealth, Create/Describe/
Modify/Delete Listener, listener certificates, Create/Describe/Modify/Delete Rule,
SetRulePriorities, Add/Remove/Describe tags, DescribeSSLPolicies,
DescribeAccountLimits.

The `console_*` helpers at the bottom are the flat REST view the web consoles use
(`/api/aws/elbv2/...`), shared by the offline server and Nano.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

NS = "http://elasticloadbalancing.amazonaws.com/doc/2015-12-01/"
DEFAULT_ACCOUNT_ID = "123456789012"
REGION = "us-east-1"
AZS = ["us-east-1a", "us-east-1b", "us-east-1c"]
LB_TYPES = ("application", "network", "gateway")
LB_SEG = {"application": "app", "network": "net", "gateway": "gwy"}
HOSTED_ZONE = {"application": "Z35SXDOTRQ7X7K", "network": "Z26RNL4JYFTOTI", "gateway": "Z26RNL4JYFTOTI"}
ALB_PROTOCOLS = ("HTTP", "HTTPS")
NLB_PROTOCOLS = ("TCP", "TLS", "UDP", "TCP_UDP")
TG_PROTOCOLS = ("HTTP", "HTTPS", "TCP", "TLS", "UDP", "TCP_UDP", "GENEVE")
DEFAULT_SSL_POLICY = "ELBSecurityPolicy-2016-08"
_ACTION_TYPES = ("forward", "redirect", "fixed-response", "authenticate-cognito", "authenticate-oidc")
_COND_FIELDS = ("path-pattern", "host-header", "http-header", "http-request-method",
                "query-string", "source-ip")

SSL_POLICIES = {
    "ELBSecurityPolicy-2016-08": (["TLSv1", "TLSv1.1", "TLSv1.2"], ["ECDHE-ECDSA-AES128-GCM-SHA256", "ECDHE-RSA-AES128-GCM-SHA256", "ECDHE-RSA-AES256-GCM-SHA384"], ("application", "network")),
    "ELBSecurityPolicy-TLS-1-2-2017-01": (["TLSv1.2"], ["ECDHE-ECDSA-AES128-GCM-SHA256", "ECDHE-RSA-AES128-GCM-SHA256"], ("application", "network")),
    "ELBSecurityPolicy-TLS13-1-2-2021-06": (["TLSv1.2", "TLSv1.3"], ["TLS_AES_128_GCM_SHA256", "TLS_AES_256_GCM_SHA384", "ECDHE-RSA-AES128-GCM-SHA256"], ("application", "network")),
    "ELBSecurityPolicy-FS-1-2-2019-08": (["TLSv1.2"], ["ECDHE-ECDSA-AES128-GCM-SHA256", "ECDHE-RSA-AES256-GCM-SHA384"], ("application", "network")),
}

_LB_ATTRS_APP = [("access_logs.s3.enabled", "false"), ("access_logs.s3.bucket", ""), ("access_logs.s3.prefix", ""),
                 ("idle_timeout.timeout_seconds", "60"), ("deletion_protection.enabled", "false"),
                 ("routing.http2.enabled", "true"), ("routing.http.drop_invalid_header_fields.enabled", "false"),
                 ("routing.http.xff_client_port.enabled", "false"), ("routing.http.desync_mitigation_mode", "defensive"),
                 ("waf.fail_open.enabled", "false"), ("load_balancing.cross_zone.enabled", "true")]
_LB_ATTRS_NET = [("access_logs.s3.enabled", "false"), ("access_logs.s3.bucket", ""), ("access_logs.s3.prefix", ""),
                 ("deletion_protection.enabled", "false"), ("load_balancing.cross_zone.enabled", "false")]
_TG_ATTRS = [("deregistration_delay.timeout_seconds", "300"), ("stickiness.enabled", "false"),
             ("stickiness.type", "lb_cookie"), ("stickiness.lb_cookie.duration_seconds", "86400"),
             ("slow_start.duration_seconds", "0"), ("load_balancing.algorithm.type", "round_robin"),
             ("load_balancing.cross_zone.enabled", "use_load_balancer_configuration")]


@dataclass
class Elbv2Response:
    status: int = 200
    body: str = ""
    headers: dict = field(default_factory=dict)
    media_type: str = "text/xml"


class Elbv2Error(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


class Elbv2Store:
    """State seam: plain dicts the engine reads/writes. `persist()` is called
    after every mutation."""

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID, region: str = REGION) -> None:
        self.account_id = account_id
        self.region = region
        self.load_balancers: dict[str, dict] = {}   # arn → record
        self.target_groups: dict[str, dict] = {}
        self.listeners: dict[str, dict] = {}
        self.rules: dict[str, dict] = {}
        self.tags: dict[str, dict] = {}             # arn → {key: value}
        self.trust_stores: dict[str, dict] = {}     # arn → record (ec2.trust-stores)
        self.trust_store_revocations: dict[str, dict] = {}   # (trust_store_arn, revocation_id) -> record
        # Set by the wire router (Nano) / routes/aws_elbv2.py (offline) — the SAME EC2/VPC
        # model and CloudWatch store autoscaling_core.py and vpc_core.py use, so target
        # health can react to a target's REAL instance state and HealthyHostCount/
        # UnHealthyHostCount can be real metrics (see ec2.load-balancing.monitoring).
        self.vpc_store: object = None
        self.cw_store: object = None
        self.s3_store: object = None   # trust-store CA bundles are read from Vyomi's own S3

    def persist(self) -> None:
        pass


# ── helpers ────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _req_id() -> str:
    return str(uuid.uuid4())


def _hex(n: int = 16) -> str:
    return uuid.uuid4().hex[:n]


def _short(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8]


def _az(i: int) -> str:
    return AZS[i % len(AZS)]


def _arn(store, path: str) -> str:
    return f"arn:aws:elasticloadbalancing:{store.region}:{store.account_id}:{path}"


# ── request parsing (Query protocol → nested dict) ─────────────────────────
def _tree(params: dict) -> dict:
    """`A.member.1.B=x` → {"A": [{"B": "x"}]}: the `member` element is dropped and
    dicts keyed only by digits become ordered lists."""
    root: dict = {}
    for k, v in params.items():
        if k in ("Action", "Version"):
            continue
        parts = [p for p in k.split(".") if p != "member"]
        node = root
        for p in parts[:-1]:
            nxt = node.get(p)
            if not isinstance(nxt, dict):
                nxt = node[p] = {}
            node = nxt
        node[parts[-1]] = v

    def conv(n):
        if isinstance(n, dict):
            n = {k: conv(v) for k, v in n.items()}
            if n and all(k.isdigit() for k in n):
                return [n[k] for k in sorted(n, key=int)]
        return n
    return conv(root)


def _lst(v) -> list:
    if v is None or v == "":
        return []
    return v if isinstance(v, list) else [v]


def _strs(v) -> list:
    return [x for x in _lst(v) if isinstance(x, str)]


def _bool_s(v, default="false") -> str:
    if v is None or v == "":
        return default
    return "true" if str(v).lower() == "true" else "false"


def _int(v, key: str, default=None):
    if v in (None, ""):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        raise Elbv2Error("ValidationError", f"Invalid value '{v}' for {key}.")


def _tags_of(req: dict) -> dict:
    return {t["Key"]: t.get("Value", "") for t in _lst(req.get("Tags")) if isinstance(t, dict) and t.get("Key") is not None}


# ── XML serialization ──────────────────────────────────────────────────────
def _x(tag: str, val) -> str:
    if isinstance(val, bool):
        val = "true" if val else "false"
    return f"<{tag}>{_xml_escape(str(val))}</{tag}>"


def _ser(tag: str, val) -> str:
    if val is None:
        return ""
    if isinstance(val, dict):
        return f"<{tag}>" + "".join(_ser(k, v) for k, v in val.items()) + f"</{tag}>"
    if isinstance(val, list):
        return f"<{tag}>" + "".join(_ser("member", i) for i in val) + f"</{tag}>"
    return _x(tag, val)


def _envelope(action: str, result_inner: str = "") -> Elbv2Response:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<{action}Response xmlns="{NS}"><{action}Result>{result_inner}</{action}Result>'
           f'<ResponseMetadata><RequestId>{_req_id()}</RequestId></ResponseMetadata>'
           f'</{action}Response>')
    return Elbv2Response(body=xml)


def _error(code: str, message: str, status: int = 400) -> Elbv2Response:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<ErrorResponse xmlns="{NS}">'
           f'<Error><Type>Sender</Type><Code>{_xml_escape(code)}</Code>'
           f'<Message>{_xml_escape(message)}</Message></Error>'
           f'<RequestId>{_req_id()}</RequestId></ErrorResponse>')
    return Elbv2Response(status=status, body=xml)


def _page(items: list, req: dict):
    """Marker/PageSize pagination → (page, NextMarker xml)."""
    size = _int(req.get("PageSize"), "PageSize", 400)
    if size < 1 or size > 400:
        raise Elbv2Error("ValidationError", "PageSize must be between 1 and 400.")
    m = str(req.get("Marker") or "0")
    start = int(m) if m.isdigit() else 0
    page = items[start:start + size]
    nxt = start + size
    return page, (_x("NextMarker", str(nxt)) if nxt < len(items) else "")


# ── lookups ────────────────────────────────────────────────────────────────
def _need_lb(store, arn: str) -> dict:
    lb = store.load_balancers.get(arn or "")
    if not lb:
        raise Elbv2Error("LoadBalancerNotFound", f"Load balancers '[{arn}]' not found")
    return lb


def _need_tg(store, arn: str) -> dict:
    tg = store.target_groups.get(arn or "")
    if not tg:
        raise Elbv2Error("TargetGroupNotFound", f"Target groups '[{arn}]' not found")
    return tg


def _need_listener(store, arn: str) -> dict:
    ls = store.listeners.get(arn or "")
    if not ls:
        raise Elbv2Error("ListenerNotFound", f"Listeners '[{arn}]' not found")
    return ls


def _need_rule(store, arn: str) -> dict:
    r = store.rules.get(arn or "")
    if not r:
        raise Elbv2Error("RuleNotFound", f"Rules '[{arn}]' not found")
    return r


def _tg_lb_arns(store, tg_arn: str) -> list:
    out = []
    for ls in store.listeners.values():
        used = list(ls["DefaultActions"]) + [a for r in store.rules.values()
                                              if r["_listener"] == ls["ListenerArn"] for a in r["Actions"]]
        if any(tg_arn in _action_tgs(a) for a in used) and ls["LoadBalancerArn"] not in out:
            out.append(ls["LoadBalancerArn"])
    return out


def _action_tgs(a: dict) -> list:
    cfg = a.get("ForwardConfig") or {}
    arns = [t.get("TargetGroupArn") for t in cfg.get("TargetGroups", [])]
    if a.get("TargetGroupArn"):
        arns.append(a["TargetGroupArn"])
    return list(dict.fromkeys(x for x in arns if x))


# ── views ──────────────────────────────────────────────────────────────────
def _lb_view(lb: dict) -> dict:
    return {k: v for k, v in lb.items() if not k.startswith("_")}


def _tg_view(store, tg: dict) -> dict:
    v = {k: val for k, val in tg.items() if not k.startswith("_") and val is not None}
    v["LoadBalancerArns"] = _tg_lb_arns(store, tg["TargetGroupArn"])
    return v


def _strip(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


# ── actions / conditions ───────────────────────────────────────────────────
def _norm_actions(store, raw, ctx: str = "Actions") -> list:
    out = []
    for i, a in enumerate(_lst(raw)):
        if not isinstance(a, dict) or a.get("Type") not in _ACTION_TYPES:
            raise Elbv2Error("ValidationError", f"Member must satisfy enum value set: {list(_ACTION_TYPES)}")
        t = a["Type"]
        n: dict = {"Type": t}
        if t == "forward":
            fc = a.get("ForwardConfig") or {}
            tgs = [{"TargetGroupArn": x.get("TargetGroupArn"), "Weight": _int(x.get("Weight"), "Weight", 1)}
                   for x in _lst(fc.get("TargetGroups")) if isinstance(x, dict)]
            if a.get("TargetGroupArn"):
                if not tgs:
                    tgs = [{"TargetGroupArn": a["TargetGroupArn"], "Weight": 1}]
                n["TargetGroupArn"] = a["TargetGroupArn"]
            if not tgs:
                raise Elbv2Error("ValidationError", "Forward action requires a TargetGroupArn or ForwardConfig.")
            for x in tgs:
                _need_tg(store, x["TargetGroupArn"])
            sc = fc.get("TargetGroupStickinessConfig") or {}
            n["ForwardConfig"] = {"TargetGroups": tgs, "TargetGroupStickinessConfig": {
                "Enabled": _bool_s(sc.get("Enabled")) == "true",
                "DurationSeconds": _int(sc.get("DurationSeconds"), "DurationSeconds", 3600)}}
            if len(tgs) > 1:
                n.pop("TargetGroupArn", None)
        elif t == "redirect":
            rc = a.get("RedirectConfig") or {}
            if not rc.get("StatusCode"):
                raise Elbv2Error("ValidationError", "RedirectConfig.StatusCode is required.")
            n["RedirectConfig"] = {"Protocol": rc.get("Protocol", "#{protocol}"), "Port": rc.get("Port", "#{port}"),
                                   "Host": rc.get("Host", "#{host}"), "Path": rc.get("Path", "/#{path}"),
                                   "Query": rc.get("Query", "#{query}"), "StatusCode": rc["StatusCode"]}
        elif t == "fixed-response":
            fr = a.get("FixedResponseConfig") or {}
            if not fr.get("StatusCode"):
                raise Elbv2Error("ValidationError", "FixedResponseConfig.StatusCode is required.")
            n["FixedResponseConfig"] = {k: fr[k] for k in ("MessageBody", "StatusCode", "ContentType") if fr.get(k) is not None}
        else:
            n["AuthenticateOidcConfig" if t == "authenticate-oidc" else "AuthenticateCognitoConfig"] = \
                a.get("AuthenticateOidcConfig") or a.get("AuthenticateCognitoConfig") or {}
        n["Order"] = _int(a.get("Order"), "Order", i + 1)
        out.append(n)
    if not out:
        raise Elbv2Error("ValidationError", f"{ctx} must contain at least one action.")
    return out


_COND_CFG = {"path-pattern": "PathPatternConfig", "host-header": "HostHeaderConfig",
             "http-header": "HttpHeaderConfig", "http-request-method": "HttpRequestMethodConfig",
             "query-string": "QueryStringConfig", "source-ip": "SourceIpConfig"}


def _norm_conditions(raw) -> list:
    out = []
    for c in _lst(raw):
        f = c.get("Field") if isinstance(c, dict) else None
        if f not in _COND_FIELDS:
            raise Elbv2Error("ValidationError", f"Condition field '{f}' is not valid.")
        cfg = c.get(_COND_CFG[f]) or {}
        vals = _strs(c.get("Values")) or (
            _strs(cfg.get("Values")) if f != "query-string" else [])
        n: dict = {"Field": f}
        if f == "query-string":
            pairs = [{"Key": p.get("Key"), "Value": p.get("Value")} for p in _lst(cfg.get("Values")) if isinstance(p, dict)]
            if not pairs:
                raise Elbv2Error("ValidationError", "QueryStringConfig requires Values.")
            n["QueryStringConfig"] = {"Values": pairs}
        else:
            if not vals:
                raise Elbv2Error("ValidationError", f"Condition '{f}' requires at least one value.")
            n["Values"] = vals
            ccfg: dict = {"Values": vals}
            if f == "http-header":
                hn = cfg.get("HttpHeaderName")
                if not hn:
                    raise Elbv2Error("ValidationError", "HttpHeaderConfig.HttpHeaderName is required.")
                ccfg = {"HttpHeaderName": hn, "Values": vals}
            n[_COND_CFG[f]] = ccfg
        out.append(n)
    return out


# ── operations: load balancers ─────────────────────────────────────────────
_LB_NAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,30}[A-Za-z0-9])?$")


def _azs_for(subnet_ids: list, mappings: list) -> list:
    ids = list(subnet_ids) + [m.get("SubnetId") for m in mappings if isinstance(m, dict) and m.get("SubnetId")]
    return [{"ZoneName": _az(i), "SubnetId": s, "LoadBalancerAddresses": []} for i, s in enumerate(ids)]


def _create_load_balancer(store, req):
    name = req.get("Name") or ""
    if not _LB_NAME.match(name) or name.startswith("internal-"):
        raise Elbv2Error("ValidationError", f"Load balancer name '{name}' cannot be longer than 32 characters, "
                         "must contain only alphanumeric characters or hyphens, and must not begin or end with a hyphen, "
                         "or begin with 'internal-'.")
    typ = req.get("Type") or "application"
    if typ not in LB_TYPES:
        raise Elbv2Error("ValidationError", f"Member must satisfy enum value set: {list(LB_TYPES)}")
    scheme = req.get("Scheme") or "internet-facing"
    if scheme not in ("internet-facing", "internal"):
        raise Elbv2Error("ValidationError", "Member must satisfy enum value set: [internal, internet-facing]")
    subnets = _strs(req.get("Subnets"))
    mappings = _lst(req.get("SubnetMappings"))
    azs = _azs_for(subnets, mappings)
    if typ == "application" and len(azs) < 2:
        raise Elbv2Error("ValidationError", "At least two subnets in two different Availability Zones must be specified")
    if not azs:
        raise Elbv2Error("ValidationError", "At least one subnet must be specified")
    ipt = req.get("IpAddressType") or "ipv4"
    if ipt not in ("ipv4", "dualstack"):
        raise Elbv2Error("ValidationError", "Member must satisfy enum value set: [ipv4, dualstack]")
    sgs = _strs(req.get("SecurityGroups"))
    for lb in store.load_balancers.values():
        if lb["LoadBalancerName"] == name:
            if (lb["Scheme"], lb["Type"]) != (scheme, typ) or [a["SubnetId"] for a in lb["AvailabilityZones"]] != [a["SubnetId"] for a in azs]:
                raise Elbv2Error("DuplicateLoadBalancerName", f"A load balancer with the same name '{name}' exists, but with different settings")
            return _envelope("CreateLoadBalancer", _ser("LoadBalancers", [_lb_view(lb)]))
    lid = _hex(16)
    arn = _arn(store, f"loadbalancer/{LB_SEG[typ]}/{name}/{lid}")
    dns = f"{'internal-' if scheme == 'internal' else ''}{name}-{int(_short(name, store.account_id), 16) % 10**9}.{store.region}.elb.amazonaws.com"
    rec = {"LoadBalancerArn": arn, "DNSName": dns, "CanonicalHostedZoneId": HOSTED_ZONE[typ],
           "CreatedTime": _now(), "LoadBalancerName": name, "Scheme": scheme,
           "VpcId": "vpc-" + _short(store.account_id, "vpc", sorted(a["SubnetId"] for a in azs)[0]),
           "State": {"Code": "active"}, "Type": typ, "AvailabilityZones": azs,
           "IpAddressType": ipt, "_attrs": dict(_LB_ATTRS_APP if typ == "application" else _LB_ATTRS_NET)}
    if typ != "network":
        rec["SecurityGroups"] = sgs
    elif sgs:
        rec["SecurityGroups"] = sgs
    store.load_balancers[arn] = rec
    store.tags[arn] = _tags_of(req)
    store.persist()
    view = _lb_view(rec)
    view["State"] = {"Code": "provisioning"}
    return _envelope("CreateLoadBalancer", _ser("LoadBalancers", [view]))


def _describe_load_balancers(store, req):
    arns, names = _strs(req.get("LoadBalancerArns")), _strs(req.get("Names"))
    items = list(store.load_balancers.values())
    if arns:
        miss = [a for a in arns if a not in store.load_balancers]
        if miss:
            raise Elbv2Error("LoadBalancerNotFound", f"Load balancers '{miss}' not found")
        items = [lb for lb in items if lb["LoadBalancerArn"] in arns]
    if names:
        miss = [n for n in names if not any(lb["LoadBalancerName"] == n for lb in items)]
        if miss:
            raise Elbv2Error("LoadBalancerNotFound", f"Load balancers '{miss}' not found")
        items = [lb for lb in items if lb["LoadBalancerName"] in names]
    items.sort(key=lambda lb: lb["LoadBalancerName"])
    page, marker = _page(items, req)
    return _envelope("DescribeLoadBalancers", _ser("LoadBalancers", [_lb_view(lb) for lb in page]) + marker)


def _delete_load_balancer(store, req):
    arn = req.get("LoadBalancerArn") or ""
    lb = store.load_balancers.get(arn)
    if lb:
        if lb["_attrs"].get("deletion_protection.enabled") == "true":
            raise Elbv2Error("OperationNotPermitted", f"Load balancer '{arn}' cannot be deleted because deletion protection is enabled")
        for ls in [l for l in store.listeners.values() if l["LoadBalancerArn"] == arn]:
            _drop_listener(store, ls["ListenerArn"])
        del store.load_balancers[arn]
        store.tags.pop(arn, None)
        store.persist()
    return _envelope("DeleteLoadBalancer")


def _attrs_list(attrs: dict) -> list:
    return [{"Key": k, "Value": v} for k, v in attrs.items()]


def _describe_load_balancer_attributes(store, req):
    lb = _need_lb(store, req.get("LoadBalancerArn"))
    return _envelope("DescribeLoadBalancerAttributes", _ser("Attributes", _attrs_list(lb["_attrs"])))


def _modify_load_balancer_attributes(store, req):
    lb = _need_lb(store, req.get("LoadBalancerArn"))
    for a in _lst(req.get("Attributes")):
        k, v = a.get("Key"), a.get("Value", "")
        if k not in lb["_attrs"]:
            raise Elbv2Error("ValidationError", f"Load balancer attribute key '{k}' is not recognized")
        lb["_attrs"][k] = v
    store.persist()
    return _envelope("ModifyLoadBalancerAttributes", _ser("Attributes", _attrs_list(lb["_attrs"])))


def _set_security_groups(store, req):
    lb = _need_lb(store, req.get("LoadBalancerArn"))
    sgs = _strs(req.get("SecurityGroups"))
    if not sgs:
        raise Elbv2Error("ValidationError", "SecurityGroups must contain at least one security group.")
    if lb["Type"] == "gateway":
        raise Elbv2Error("InvalidConfigurationRequest", "Security groups are not supported for gateway load balancers")
    lb["SecurityGroups"] = sgs
    store.persist()
    return _envelope("SetSecurityGroups", _ser("SecurityGroupIds", sgs))


def _set_subnets(store, req):
    lb = _need_lb(store, req.get("LoadBalancerArn"))
    azs = _azs_for(_strs(req.get("Subnets")), _lst(req.get("SubnetMappings")))
    if lb["Type"] == "application" and len(azs) < 2:
        raise Elbv2Error("ValidationError", "At least two subnets in two different Availability Zones must be specified")
    if not azs:
        raise Elbv2Error("ValidationError", "At least one subnet must be specified")
    lb["AvailabilityZones"] = azs
    store.persist()
    return _envelope("SetSubnets", _ser("AvailabilityZones", azs) + _x("IpAddressType", lb["IpAddressType"]))


def _set_ip_address_type(store, req):
    lb = _need_lb(store, req.get("LoadBalancerArn"))
    ipt = req.get("IpAddressType")
    if ipt not in ("ipv4", "dualstack", "dualstack-without-public-ipv4"):
        raise Elbv2Error("ValidationError", "Member must satisfy enum value set: [ipv4, dualstack]")
    lb["IpAddressType"] = ipt
    store.persist()
    return _envelope("SetIpAddressType", _x("IpAddressType", ipt))


# ── operations: target groups ──────────────────────────────────────────────
_TG_NAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,30}[A-Za-z0-9])?$")


def _create_target_group(store, req):
    name = req.get("Name") or ""
    if not _TG_NAME.match(name):
        raise Elbv2Error("ValidationError", f"Target group name '{name}' cannot be longer than 32 characters, "
                         "must contain only alphanumeric characters or hyphens, and must not begin or end with a hyphen")
    ttype = req.get("TargetType") or "instance"
    if ttype not in ("instance", "ip", "lambda", "alb"):
        raise Elbv2Error("ValidationError", "Member must satisfy enum value set: [instance, ip, lambda, alb]")
    proto = req.get("Protocol")
    port = _int(req.get("Port"), "Port")
    if ttype != "lambda":
        if proto not in TG_PROTOCOLS:
            raise Elbv2Error("ValidationError", f"Protocol must be one of {list(TG_PROTOCOLS)}.")
        if port is None or not 1 <= port <= 65535:
            raise Elbv2Error("ValidationError", "Port must be between 1 and 65535.")
        if not req.get("VpcId"):
            raise Elbv2Error("ValidationError", "A VPC ID must be specified")
    http = proto in ("HTTP", "HTTPS") or ttype == "lambda"
    hc_proto = req.get("HealthCheckProtocol") or ("HTTP" if http and proto != "HTTPS" else proto or "HTTP")
    if hc_proto == "HTTP" and proto == "HTTPS":
        hc_proto = "HTTPS"
    for tg in store.target_groups.values():
        if tg["TargetGroupName"] == name:
            if (tg.get("Protocol"), tg.get("Port"), tg.get("VpcId"), tg["TargetType"]) != (proto, port, req.get("VpcId"), ttype):
                raise Elbv2Error("DuplicateTargetGroupName", f"A target group with the same name '{name}' exists, but with different settings")
            return _envelope("CreateTargetGroup", _ser("TargetGroups", [_tg_view(store, tg)]))
    arn = _arn(store, f"targetgroup/{name}/{_hex(16)}")
    rec: dict = {"TargetGroupArn": arn, "TargetGroupName": name, "Protocol": proto, "Port": port,
                 "VpcId": req.get("VpcId"), "HealthCheckProtocol": hc_proto,
                 "HealthCheckPort": req.get("HealthCheckPort") or "traffic-port",
                 "HealthCheckEnabled": _bool_s(req.get("HealthCheckEnabled"), "true") == "true",
                 "HealthCheckIntervalSeconds": _int(req.get("HealthCheckIntervalSeconds"), "HealthCheckIntervalSeconds", 35 if ttype == "lambda" else 30),
                 "HealthCheckTimeoutSeconds": _int(req.get("HealthCheckTimeoutSeconds"), "HealthCheckTimeoutSeconds", 30 if ttype == "lambda" else (10 if hc_proto in ("TCP", "TLS") else 5)),
                 "HealthyThresholdCount": _int(req.get("HealthyThresholdCount"), "HealthyThresholdCount", 5 if http else 3),
                 "UnhealthyThresholdCount": _int(req.get("UnhealthyThresholdCount"), "UnhealthyThresholdCount", 2 if http else 3),
                 "TargetType": ttype, "IpAddressType": req.get("IpAddressType") or "ipv4",
                 "_attrs": dict(_TG_ATTRS), "_targets": []}
    if hc_proto in ("HTTP", "HTTPS"):
        rec["HealthCheckPath"] = req.get("HealthCheckPath") or "/"
        rec["Matcher"] = {"HttpCode": (req.get("Matcher") or {}).get("HttpCode") or "200"}
    if http:
        rec["ProtocolVersion"] = req.get("ProtocolVersion") or "HTTP1"
    store.target_groups[arn] = rec
    store.tags[arn] = _tags_of(req)
    store.persist()
    return _envelope("CreateTargetGroup", _ser("TargetGroups", [_tg_view(store, rec)]))


def _describe_target_groups(store, req):
    arns, names = _strs(req.get("TargetGroupArns")), _strs(req.get("Names"))
    items = list(store.target_groups.values())
    if arns:
        miss = [a for a in arns if a not in store.target_groups]
        if miss:
            raise Elbv2Error("TargetGroupNotFound", f"One or more target groups not found")
        items = [t for t in items if t["TargetGroupArn"] in arns]
    if names:
        if any(not any(t["TargetGroupName"] == n for t in items) for n in names):
            raise Elbv2Error("TargetGroupNotFound", "One or more target groups not found")
        items = [t for t in items if t["TargetGroupName"] in names]
    if req.get("LoadBalancerArn"):
        _need_lb(store, req["LoadBalancerArn"])
        items = [t for t in items if req["LoadBalancerArn"] in _tg_lb_arns(store, t["TargetGroupArn"])]
    items.sort(key=lambda t: t["TargetGroupName"])
    page, marker = _page(items, req)
    return _envelope("DescribeTargetGroups", _ser("TargetGroups", [_tg_view(store, t) for t in page]) + marker)


def _modify_target_group(store, req):
    tg = _need_tg(store, req.get("TargetGroupArn"))
    for k in ("HealthCheckProtocol", "HealthCheckPort", "HealthCheckPath"):
        if req.get(k):
            tg[k] = req[k]
    for k in ("HealthCheckIntervalSeconds", "HealthCheckTimeoutSeconds", "HealthyThresholdCount", "UnhealthyThresholdCount"):
        if req.get(k) not in (None, ""):
            tg[k] = _int(req[k], k)
    if req.get("HealthCheckEnabled") not in (None, ""):
        tg["HealthCheckEnabled"] = _bool_s(req["HealthCheckEnabled"]) == "true"
    if (req.get("Matcher") or {}).get("HttpCode"):
        tg["Matcher"] = {"HttpCode": req["Matcher"]["HttpCode"]}
    store.persist()
    return _envelope("ModifyTargetGroup", _ser("TargetGroups", [_tg_view(store, tg)]))


def _delete_target_group(store, req):
    arn = req.get("TargetGroupArn") or ""
    tg = _need_tg(store, arn)
    if _tg_lb_arns(store, arn):
        raise Elbv2Error("ResourceInUse", f"Target group '{arn}' is currently in use by a listener or a rule")
    del store.target_groups[arn]
    store.tags.pop(arn, None)
    store.persist()
    return _envelope("DeleteTargetGroup")


def _describe_target_group_attributes(store, req):
    tg = _need_tg(store, req.get("TargetGroupArn"))
    return _envelope("DescribeTargetGroupAttributes", _ser("Attributes", _attrs_list(tg["_attrs"])))


def _modify_target_group_attributes(store, req):
    tg = _need_tg(store, req.get("TargetGroupArn"))
    for a in _lst(req.get("Attributes")):
        k = a.get("Key")
        if k not in tg["_attrs"]:
            raise Elbv2Error("ValidationError", f"Target group attribute key '{k}' is not recognized")
        tg["_attrs"][k] = a.get("Value", "")
    store.persist()
    return _envelope("ModifyTargetGroupAttributes", _ser("Attributes", _attrs_list(tg["_attrs"])))


# ── operations: targets ────────────────────────────────────────────────────
def _valid_target(tg: dict, tid: str) -> None:
    t = tg["TargetType"]
    if t == "instance" and not re.match(r"^i-[0-9a-f]{8,17}$", tid or ""):
        raise Elbv2Error("InvalidTarget", f"'{tid}' is not a valid target ID for target type instance")
    if t == "ip":
        try:
            ipaddress.ip_address(tid)
        except ValueError:
            raise Elbv2Error("ValidationError", f"Target IP address '{tid}' is not a valid IP address")
    if t == "lambda" and not (tid or "").startswith("arn:aws:lambda:"):
        raise Elbv2Error("ValidationError", f"'{tid}' is not a valid lambda function ARN")


def _tkey(t: dict):
    return (t["Id"], t.get("Port"))


def _register_targets(store, req):
    tg = _need_tg(store, req.get("TargetGroupArn"))
    ts = [t for t in _lst(req.get("Targets")) if isinstance(t, dict)]
    if not ts:
        raise Elbv2Error("ValidationError", "Targets must contain at least one target.")
    for t in ts:
        _valid_target(tg, t.get("Id"))
        port = _int(t.get("Port"), "Port", tg.get("Port"))
        rec = {"Id": t["Id"], "Port": port}
        if t.get("AvailabilityZone"):
            rec["AvailabilityZone"] = t["AvailabilityZone"]
        tg["_targets"] = [x for x in tg["_targets"] if _tkey(x) != _tkey(rec)] + [rec]
    store.persist()
    return _envelope("RegisterTargets")


def _deregister_targets(store, req):
    tg = _need_tg(store, req.get("TargetGroupArn"))
    for t in _lst(req.get("Targets")):
        port = _int(t.get("Port"), "Port", tg.get("Port"))
        key = (t.get("Id"), port)
        if not any(_tkey(x) == key for x in tg["_targets"]):
            if tg["TargetType"] != "lambda":
                continue   # real ELBv2 silently ignores unregistered targets
        tg["_targets"] = [x for x in tg["_targets"] if _tkey(x) != key]
    store.persist()
    return _envelope("DeregisterTargets")


def _instance_state(store, instance_id: str) -> str | None:
    """The target's REAL EC2 instance state (running/stopped/terminated/…), from the SAME
    vpc_core model the EC2 console reads — None if no vpc_store is wired (older callers /
    unit tests keep the pre-existing deterministic-on-registration behaviour) or the
    instance isn't found there (an ENI/IP target, or a plain id a unit test made up)."""
    vpc_store = getattr(store, "vpc_store", None)
    if vpc_store is None:
        return None
    model = getattr(vpc_store, "_vpc_model", None) or {}
    inst = (model.get("instances") or {}).get(instance_id)
    return inst.get("state") if inst else None


def _target_health(store, tg: dict, t: dict, in_use: bool) -> dict:
    if not in_use:
        return {"State": "unused", "Reason": "Target.NotInUse",
                "Description": "Target group is not configured to receive traffic from the load balancer"}
    if tg["TargetType"] == "instance":
        state = _instance_state(store, t["Id"])
        if state is not None and state != "running":
            reason = "Target.DeregistrationInProgress" if state == "stopping" else "Target.FailedHealthChecks"
            return {"State": "unhealthy" if state in ("stopped", "stopping") else "draining",
                    "Reason": reason, "Description": f"Instance is in state '{state}'."}
    return {"State": "healthy"}


def _publish_health_metrics(store, tg: dict, lb_arns: list, healthy: int, unhealthy: int) -> None:
    """Real AWS/ApplicationELB + AWS/NetworkELB HealthyHostCount / UnHealthyHostCount,
    dimensioned by LoadBalancer + TargetGroup (see ec2.load-balancing.monitoring) —
    published whenever target health is (re-)evaluated, the same lazy-on-read convention
    this simulator's other CloudWatch metrics (e.g. EC2 StatusCheckFailed) use."""
    cw_store = getattr(store, "cw_store", None)
    if cw_store is None:
        return
    from core import cloudwatch_core as _cw
    tg_dim = tg["TargetGroupArn"].split(":targetgroup/", 1)[1] if ":targetgroup/" in tg["TargetGroupArn"] else tg["TargetGroupArn"]
    for lb_arn in lb_arns:
        lb = store.load_balancers.get(lb_arn)
        if lb is None:
            continue
        ns = "AWS/NetworkELB" if lb["Type"] == "network" else "AWS/ApplicationELB"
        lb_dim = _lb_ids(lb_arn)
        dims = [{"Name": "LoadBalancer", "Value": lb_dim}, {"Name": "TargetGroup", "Value": tg_dim}]
        _cw.ingest_internal_metric(cw_store, ns, "HealthyHostCount", dims, float(healthy), unit="Count")
        _cw.ingest_internal_metric(cw_store, ns, "UnHealthyHostCount", dims, float(unhealthy), unit="Count")


def _describe_target_health(store, req):
    tg = _need_tg(store, req.get("TargetGroupArn"))
    wanted = [(t.get("Id"), _int(t.get("Port"), "Port", tg.get("Port"))) for t in _lst(req.get("Targets")) if isinstance(t, dict)]
    lb_arns = _tg_lb_arns(store, tg["TargetGroupArn"])
    in_use = bool(lb_arns)
    out = []
    healthy = unhealthy = 0
    for t in tg["_targets"]:
        th = _target_health(store, tg, t, in_use)
        if th["State"] == "healthy":
            healthy += 1
        elif th["State"] in ("unhealthy", "draining"):
            unhealthy += 1
        if wanted and _tkey(t) not in wanted:
            continue
        out.append({"Target": dict(t), "HealthCheckPort": str(t["Port"] if tg["HealthCheckPort"] == "traffic-port" else tg["HealthCheckPort"]),
                    "TargetHealth": th})
    for w in wanted:
        if not any(_tkey(t) == w for t in tg["_targets"]):
            out.append({"Target": {"Id": w[0], "Port": w[1]}, "HealthCheckPort": str(w[1]),
                        "TargetHealth": {"State": "unused", "Reason": "Target.NotRegistered",
                                         "Description": "Target is not registered to the target group"}})
    if in_use:
        _publish_health_metrics(store, tg, lb_arns, healthy, unhealthy)
    return _envelope("DescribeTargetHealth", _ser("TargetHealthDescriptions", out))


# ── operations: listeners ──────────────────────────────────────────────────
def _lb_ids(arn: str) -> str:
    return arn.split(":loadbalancer/", 1)[1]


def _create_listener(store, req):
    lb = _need_lb(store, req.get("LoadBalancerArn"))
    typ = lb["Type"]
    proto = req.get("Protocol")
    if typ == "gateway":
        proto, port = None, None
    else:
        allowed = ALB_PROTOCOLS if typ == "application" else NLB_PROTOCOLS
        if proto not in allowed:
            raise Elbv2Error("ValidationError", f"Protocol '{proto}' is not supported for a {typ} load balancer; use one of {list(allowed)}")
        port = _int(req.get("Port"), "Port")
        if port is None or not 1 <= port <= 65535:
            raise Elbv2Error("ValidationError", "Port must be between 1 and 65535.")
    for ls in store.listeners.values():
        if ls["LoadBalancerArn"] == lb["LoadBalancerArn"] and ls.get("Port") == port:
            raise Elbv2Error("DuplicateListener", "A listener with the specified port already exists")
    certs = [{"CertificateArn": c.get("CertificateArn")} for c in _lst(req.get("Certificates")) if isinstance(c, dict) and c.get("CertificateArn")]
    if proto in ("HTTPS", "TLS") and not certs:
        raise Elbv2Error("ValidationError", "A certificate must be specified for HTTPS listeners")
    actions = _norm_actions(store, req.get("DefaultActions"), "DefaultActions")
    lid = _hex(16)
    arn = _arn(store, f"listener/{LB_SEG[typ]}/{lb['LoadBalancerName']}/{_lb_ids(lb['LoadBalancerArn']).split('/')[-1]}/{lid}")
    rec = {"ListenerArn": arn, "LoadBalancerArn": lb["LoadBalancerArn"], "DefaultActions": actions}
    if port is not None:
        rec["Port"], rec["Protocol"] = port, proto
    if certs:
        rec["Certificates"] = certs
        rec["SslPolicy"] = req.get("SslPolicy") or DEFAULT_SSL_POLICY
    if req.get("AlpnPolicy"):
        rec["AlpnPolicy"] = _strs(req["AlpnPolicy"])
    if req.get("MutualAuthentication"):
        rec["MutualAuthentication"] = _mutual_auth(store, req["MutualAuthentication"], proto)
    store.listeners[arn] = rec
    store.tags[arn] = _tags_of(req)
    rarn = arn.replace(":listener/", ":listener-rule/").rsplit("/", 1)[0] + f"/{lid}/{_hex(16)}"
    store.rules[rarn] = {"RuleArn": rarn, "Priority": "default", "Conditions": [], "Actions": actions,
                         "IsDefault": True, "_listener": arn}
    store.persist()
    return _envelope("CreateListener", _ser("Listeners", [_strip(rec)]))


def _describe_listeners(store, req):
    items = list(store.listeners.values())
    arns = _strs(req.get("ListenerArns"))
    if req.get("LoadBalancerArn"):
        _need_lb(store, req["LoadBalancerArn"])
        items = [l for l in items if l["LoadBalancerArn"] == req["LoadBalancerArn"]]
    if arns:
        if any(a not in store.listeners for a in arns):
            raise Elbv2Error("ListenerNotFound", "One or more listeners not found")
        items = [l for l in items if l["ListenerArn"] in arns]
    elif not req.get("LoadBalancerArn"):
        raise Elbv2Error("ValidationError", "You must specify either listener ARNs or a load balancer ARN")
    items.sort(key=lambda l: l.get("Port") or 0)
    page, marker = _page(items, req)
    return _envelope("DescribeListeners", _ser("Listeners", [_strip(l) for l in page]) + marker)


def _modify_listener(store, req):
    ls = _need_listener(store, req.get("ListenerArn"))
    lb = store.load_balancers[ls["LoadBalancerArn"]]
    if req.get("Port"):
        port = _int(req["Port"], "Port")
        if any(o is not ls and o["LoadBalancerArn"] == ls["LoadBalancerArn"] and o.get("Port") == port for o in store.listeners.values()):
            raise Elbv2Error("DuplicateListener", "A listener with the specified port already exists")
        ls["Port"] = port
    if req.get("Protocol"):
        allowed = ALB_PROTOCOLS if lb["Type"] == "application" else NLB_PROTOCOLS
        if req["Protocol"] not in allowed:
            raise Elbv2Error("ValidationError", f"Protocol '{req['Protocol']}' is not supported for a {lb['Type']} load balancer")
        ls["Protocol"] = req["Protocol"]
    if req.get("SslPolicy"):
        ls["SslPolicy"] = req["SslPolicy"]
    certs = [{"CertificateArn": c.get("CertificateArn")} for c in _lst(req.get("Certificates")) if isinstance(c, dict) and c.get("CertificateArn")]
    if certs:
        ls["Certificates"] = certs
        ls.setdefault("SslPolicy", DEFAULT_SSL_POLICY)
    if ls.get("Protocol") in ("HTTPS", "TLS") and not ls.get("Certificates"):
        raise Elbv2Error("ValidationError", "A certificate must be specified for HTTPS listeners")
    if req.get("DefaultActions"):
        ls["DefaultActions"] = _norm_actions(store, req["DefaultActions"], "DefaultActions")
        for r in store.rules.values():
            if r["_listener"] == ls["ListenerArn"] and r["IsDefault"]:
                r["Actions"] = ls["DefaultActions"]
    if req.get("MutualAuthentication"):
        ls["MutualAuthentication"] = _mutual_auth(store, req["MutualAuthentication"], ls.get("Protocol"))
    store.persist()
    return _envelope("ModifyListener", _ser("Listeners", [_strip(ls)]))


# ── trust stores (mutual TLS, ec2.trust-stores) ─────────────────────────────
def _need_trust_store(store, arn):
    ts = store.trust_stores.get(arn or "")
    if not ts:
        raise Elbv2Error("TrustStoreNotFound", f"Trust store '{arn}' not found")
    return ts


def _mutual_auth(store, cfg: dict, protocol: str | None) -> dict:
    mode = str(cfg.get("Mode") or "off")
    if mode == "off":
        return {"Mode": "off"}
    if protocol != "HTTPS":
        raise Elbv2Error("ValidationError", "MutualAuthentication requires an HTTPS listener.")
    ts_arn = cfg.get("TrustStoreArn")
    if not ts_arn:
        raise Elbv2Error("ValidationError", "TrustStoreArn is required when MutualAuthentication.Mode is not 'off'.")
    _need_trust_store(store, ts_arn)
    return {"Mode": mode, "TrustStoreArn": ts_arn,
            "IgnoreClientCertificateExpiry": str(cfg.get("IgnoreClientCertificateExpiry", "")).lower() == "true",
            "TrustStoreAssociationStatus": "active"}


def _count_pem_certs(body: bytes) -> int:
    try:
        return body.decode("utf-8", "ignore").count("-----BEGIN CERTIFICATE-----")
    except Exception:
        return 0


def _create_trust_store(store, req):
    name = req.get("Name")
    if not name or not re.match(r"^[a-zA-Z0-9-]{1,32}$", name):
        raise Elbv2Error("ValidationError", "Name must be 1-32 alphanumeric/hyphen characters.")
    if any(t["Name"] == name for t in store.trust_stores.values()):
        raise Elbv2Error("DuplicateTrustStoreName", f"Trust store '{name}' already exists")
    bucket, key = req.get("CaCertificatesBundleS3Bucket"), req.get("CaCertificatesBundleS3Key")
    if not bucket or not key:
        raise Elbv2Error("ValidationError", "CaCertificatesBundleS3Bucket and CaCertificatesBundleS3Key are required.")
    cert_count = 0
    if store.s3_store is not None:
        from core import s3_object_core as _s3
        r = _s3.get_object(store.s3_store, bucket, key, {}, {})
        if r.status != 200:
            raise Elbv2Error("ValidationError", f"The CA bundle object s3://{bucket}/{key} does not exist.")
        cert_count = _count_pem_certs(r.body if isinstance(r.body, bytes) else bytes(r.body or b""))
        if cert_count == 0:
            raise Elbv2Error("ValidationError", f"s3://{bucket}/{key} does not contain a valid PEM CA bundle (no -----BEGIN CERTIFICATE----- block).")
    arn = _arn(store, f"truststore/{name}/{_hex(16)}")
    ts = {"TrustStoreArn": arn, "Name": name, "Status": "ACTIVE",
          "NumberOfCaCertificates": cert_count, "TotalRevokedEntries": 0,
          "CaCertificatesBundleS3Bucket": bucket, "CaCertificatesBundleS3Key": key}
    store.trust_stores[arn] = ts
    store.tags[arn] = _tags_of(req)
    store.persist()
    return _envelope("CreateTrustStore", _ser("TrustStores", [ts]))


def _describe_trust_stores(store, req):
    items = list(store.trust_stores.values())
    arns = _strs(req.get("TrustStoreArns"))
    names = _strs(req.get("Names"))
    if arns:
        if any(a not in store.trust_stores for a in arns):
            raise Elbv2Error("TrustStoreNotFound", "One or more trust stores not found")
        items = [t for t in items if t["TrustStoreArn"] in arns]
    elif names:
        items = [t for t in items if t["Name"] in names]
    page, marker = _page(items, req)
    return _envelope("DescribeTrustStores", _ser("TrustStores", page) + marker)


def _modify_trust_store(store, req):
    ts = _need_trust_store(store, req.get("TrustStoreArn"))
    bucket = req.get("CaCertificatesBundleS3Bucket") or ts["CaCertificatesBundleS3Bucket"]
    key = req.get("CaCertificatesBundleS3Key") or ts["CaCertificatesBundleS3Key"]
    if store.s3_store is not None and (req.get("CaCertificatesBundleS3Bucket") or req.get("CaCertificatesBundleS3Key")):
        from core import s3_object_core as _s3
        r = _s3.get_object(store.s3_store, bucket, key, {}, {})
        if r.status != 200:
            raise Elbv2Error("ValidationError", f"The CA bundle object s3://{bucket}/{key} does not exist.")
        ts["NumberOfCaCertificates"] = _count_pem_certs(r.body if isinstance(r.body, bytes) else bytes(r.body or b""))
    ts["CaCertificatesBundleS3Bucket"], ts["CaCertificatesBundleS3Key"] = bucket, key
    store.persist()
    return _envelope("ModifyTrustStore", _ser("TrustStores", [ts]))


def _delete_trust_store(store, req):
    arn = req.get("TrustStoreArn")
    ts = _need_trust_store(store, arn)
    in_use = [l["ListenerArn"] for l in store.listeners.values()
              if (l.get("MutualAuthentication") or {}).get("TrustStoreArn") == arn]
    if in_use:
        raise Elbv2Error("TrustStoreInUse", f"Trust store '{arn}' is associated with listener(s) {in_use}.")
    store.trust_stores.pop(arn, None)
    store.trust_store_revocations.pop(arn, None)
    store.tags.pop(arn, None)
    store.persist()
    return _envelope("DeleteTrustStore")


def _describe_trust_store_associations(store, req):
    arn = req.get("TrustStoreArn")
    _need_trust_store(store, arn)
    rows = [{"ResourceArn": l["ListenerArn"]} for l in store.listeners.values()
            if (l.get("MutualAuthentication") or {}).get("TrustStoreArn") == arn]
    page, marker = _page(rows, req)
    return _envelope("DescribeTrustStoreAssociations", _ser("TrustStoreAssociations", page) + marker)


def _create_trust_store_revocation(store, req):
    arn = req.get("TrustStoreArn")
    _need_trust_store(store, arn)
    bucket, key = req.get("RevocationContents.1.S3Bucket") or req.get("RevocationContentsS3Bucket"), \
                  req.get("RevocationContents.1.S3Key") or req.get("RevocationContentsS3Key")
    revs = store.trust_store_revocations.setdefault(arn, {})
    rev_id = len(revs) + 1
    revs[rev_id] = {"TrustStoreArn": arn, "RevocationId": rev_id, "RevocationType": "CRL",
                    "NumberOfRevokedEntries": 0, "S3Bucket": bucket, "S3Key": key}
    store.trust_stores[arn]["TotalRevokedEntries"] = sum(r["NumberOfRevokedEntries"] for r in revs.values())
    store.persist()
    return _envelope("CreateTrustStoreRevocation", _ser("TrustStoreRevocations", [revs[rev_id]]))


def _describe_trust_store_revocations(store, req):
    arn = req.get("TrustStoreArn")
    _need_trust_store(store, arn)
    rows = list(store.trust_store_revocations.get(arn, {}).values())
    return _envelope("DescribeTrustStoreRevocations", _ser("TrustStoreRevocations", rows))


def _delete_trust_store_revocation(store, req):
    arn = req.get("TrustStoreArn")
    _need_trust_store(store, arn)
    rev_id = int(req.get("RevocationId"))
    store.trust_store_revocations.get(arn, {}).pop(rev_id, None)
    store.persist()
    return _envelope("DeleteTrustStoreRevocation")


def _drop_listener(store, arn: str) -> None:
    for rarn in [k for k, r in store.rules.items() if r["_listener"] == arn]:
        del store.rules[rarn]
        store.tags.pop(rarn, None)
    store.listeners.pop(arn, None)
    store.tags.pop(arn, None)


def _delete_listener(store, req):
    _need_listener(store, req.get("ListenerArn"))
    _drop_listener(store, req["ListenerArn"])
    store.persist()
    return _envelope("DeleteListener")


def _add_listener_certificates(store, req):
    ls = _need_listener(store, req.get("ListenerArn"))
    certs = [{"CertificateArn": c.get("CertificateArn")} for c in _lst(req.get("Certificates")) if isinstance(c, dict) and c.get("CertificateArn")]
    if not certs:
        raise Elbv2Error("ValidationError", "Certificates must contain at least one certificate.")
    have = ls.setdefault("_extra_certs", [])
    for c in certs:
        if c not in have:
            have.append(c)
    store.persist()
    return _envelope("AddListenerCertificates", _ser("Certificates", have))


def _remove_listener_certificates(store, req):
    ls = _need_listener(store, req.get("ListenerArn"))
    arns = [c.get("CertificateArn") for c in _lst(req.get("Certificates")) if isinstance(c, dict)]
    if any(a in [c["CertificateArn"] for c in ls.get("Certificates", [])] for a in arns):
        raise Elbv2Error("OperationNotPermitted", "Cannot remove the default certificate of a listener")
    ls["_extra_certs"] = [c for c in ls.get("_extra_certs", []) if c["CertificateArn"] not in arns]
    store.persist()
    return _envelope("RemoveListenerCertificates")


def _describe_listener_certificates(store, req):
    ls = _need_listener(store, req.get("ListenerArn"))
    certs = [dict(c, IsDefault=True) for c in ls.get("Certificates", [])] + \
            [dict(c, IsDefault=False) for c in ls.get("_extra_certs", [])]
    return _envelope("DescribeListenerCertificates", _ser("Certificates", certs))


# ── operations: rules ──────────────────────────────────────────────────────
def _rule_view(r: dict) -> dict:
    return _strip(r)


def _create_rule(store, req):
    ls = _need_listener(store, req.get("ListenerArn"))
    prio = _int(req.get("Priority"), "Priority")
    if prio is None or not 1 <= prio <= 50000:
        raise Elbv2Error("ValidationError", "Priority must be between 1 and 50000.")
    if any(r["_listener"] == ls["ListenerArn"] and r["Priority"] == str(prio) for r in store.rules.values()):
        raise Elbv2Error("PriorityInUse", f"The priority '{prio}' is currently in use")
    conds = _norm_conditions(req.get("Conditions"))
    if not conds:
        raise Elbv2Error("ValidationError", "Conditions must contain at least one condition.")
    acts = _norm_actions(store, req.get("Actions"))
    base = ls["ListenerArn"].replace(":listener/", ":listener-rule/")
    arn = f"{base}/{_hex(16)}"
    rec = {"RuleArn": arn, "Priority": str(prio), "Conditions": conds, "Actions": acts, "IsDefault": False, "_listener": ls["ListenerArn"]}
    store.rules[arn] = rec
    store.tags[arn] = _tags_of(req)
    store.persist()
    return _envelope("CreateRule", _ser("Rules", [_rule_view(rec)]))


def _rules_sorted(items: list) -> list:
    return sorted(items, key=lambda r: (1, 0) if r["IsDefault"] else (0, int(r["Priority"])))


def _describe_rules(store, req):
    arns = _strs(req.get("RuleArns"))
    if req.get("ListenerArn"):
        _need_listener(store, req["ListenerArn"])
        items = [r for r in store.rules.values() if r["_listener"] == req["ListenerArn"]]
    elif arns:
        if any(a not in store.rules for a in arns):
            raise Elbv2Error("RuleNotFound", "One or more rules not found")
        items = [store.rules[a] for a in arns]
    else:
        raise Elbv2Error("ValidationError", "You must specify either listener ARN or rule ARNs")
    page, marker = _page(_rules_sorted(items), req)
    return _envelope("DescribeRules", _ser("Rules", [_rule_view(r) for r in page]) + marker)


def _modify_rule(store, req):
    r = _need_rule(store, req.get("RuleArn"))
    if r["IsDefault"]:
        raise Elbv2Error("OperationNotPermitted", "A default rule cannot be modified; use ModifyListener")
    if req.get("Conditions"):
        r["Conditions"] = _norm_conditions(req["Conditions"])
    if req.get("Actions"):
        r["Actions"] = _norm_actions(store, req["Actions"])
    store.persist()
    return _envelope("ModifyRule", _ser("Rules", [_rule_view(r)]))


def _delete_rule(store, req):
    r = _need_rule(store, req.get("RuleArn"))
    if r["IsDefault"]:
        raise Elbv2Error("OperationNotPermitted", "Default rules cannot be deleted")
    del store.rules[r["RuleArn"]]
    store.tags.pop(r["RuleArn"], None)
    store.persist()
    return _envelope("DeleteRule")


def _set_rule_priorities(store, req):
    pairs = [(p.get("RuleArn"), _int(p.get("Priority"), "Priority")) for p in _lst(req.get("RulePriorities")) if isinstance(p, dict)]
    if not pairs:
        raise Elbv2Error("ValidationError", "RulePriorities must contain at least one entry.")
    rules = [_need_rule(store, a) for a, _ in pairs]
    if any(r["IsDefault"] for r in rules):
        raise Elbv2Error("OperationNotPermitted", "The priority of a default rule cannot be changed")
    for r, (_, p) in zip(rules, pairs):
        if p is None or not 1 <= p <= 50000:
            raise Elbv2Error("ValidationError", "Priority must be between 1 and 50000.")
        moving = {a for a, _ in pairs}
        if any(o["_listener"] == r["_listener"] and o["Priority"] == str(p) and o["RuleArn"] not in moving for o in store.rules.values()):
            raise Elbv2Error("PriorityInUse", f"The priority '{p}' is currently in use")
    for r, (_, p) in zip(rules, pairs):
        r["Priority"] = str(p)
    store.persist()
    return _envelope("SetRulePriorities", _ser("Rules", [_rule_view(r) for r in rules]))


# ── operations: tags / reference data ──────────────────────────────────────
def _tag_target(store, arn: str) -> None:
    if arn in store.load_balancers or arn in store.target_groups or arn in store.listeners or arn in store.rules:
        return
    if ":targetgroup/" in arn:
        raise Elbv2Error("TargetGroupNotFound", f"Target groups '[{arn}]' not found")
    if ":listener-rule/" in arn:
        raise Elbv2Error("RuleNotFound", f"Rules '[{arn}]' not found")
    if ":listener/" in arn:
        raise Elbv2Error("ListenerNotFound", f"Listeners '[{arn}]' not found")
    raise Elbv2Error("LoadBalancerNotFound", f"Load balancers '[{arn}]' not found")


def _add_tags(store, req):
    arns = _strs(req.get("ResourceArns"))
    new = _tags_of(req)
    if not new:
        raise Elbv2Error("ValidationError", "Tags must contain at least one tag.")
    for a in arns:
        _tag_target(store, a)
    for a in arns:
        have = store.tags.setdefault(a, {})
        if len({**have, **new}) > 50:
            raise Elbv2Error("TooManyTags", "The limit of 50 tags per resource was exceeded")
        have.update(new)
    store.persist()
    return _envelope("AddTags")


def _remove_tags(store, req):
    arns, keys = _strs(req.get("ResourceArns")), _strs(req.get("TagKeys"))
    for a in arns:
        _tag_target(store, a)
    for a in arns:
        for k in keys:
            store.tags.get(a, {}).pop(k, None)
    store.persist()
    return _envelope("RemoveTags")


def _describe_tags(store, req):
    arns = _strs(req.get("ResourceArns"))
    if not arns:
        raise Elbv2Error("ValidationError", "ResourceArns must contain at least one ARN.")
    for a in arns:
        _tag_target(store, a)
    return _envelope("DescribeTags", _ser("TagDescriptions", [
        {"ResourceArn": a, "Tags": [{"Key": k, "Value": v} for k, v in (store.tags.get(a) or {}).items()]} for a in arns]))


def _describe_ssl_policies(store, req):
    names = _strs(req.get("Names"))
    if any(n not in SSL_POLICIES for n in names):
        raise Elbv2Error("SSLPolicyNotFound", "One or more SSL policies not found")
    out = []
    for n, (protos, ciphers, types) in SSL_POLICIES.items():
        if names and n not in names:
            continue
        out.append({"SslProtocols": protos, "Ciphers": [{"Name": c, "Priority": i + 1} for i, c in enumerate(ciphers)],
                    "Name": n, "SupportedLoadBalancerTypes": list(types)})
    return _envelope("DescribeSSLPolicies", _ser("SslPolicies", out))


def _describe_account_limits(store, req):
    limits = [("application-load-balancers", 50), ("network-load-balancers", 50), ("gateway-load-balancers", 100),
              ("target-groups", 3000), ("targets-per-application-load-balancer", 1000),
              ("targets-per-network-load-balancer", 3000), ("listeners-per-application-load-balancer", 50),
              ("listeners-per-network-load-balancer", 50), ("rules-per-application-load-balancer", 100),
              ("certificates-per-application-load-balancer", 25)]
    return _envelope("DescribeAccountLimits", _ser("Limits", [{"Name": n, "Max": str(m)} for n, m in limits]))


OPERATIONS = {
    "CreateLoadBalancer": _create_load_balancer, "DescribeLoadBalancers": _describe_load_balancers,
    "DeleteLoadBalancer": _delete_load_balancer,
    "DescribeLoadBalancerAttributes": _describe_load_balancer_attributes,
    "ModifyLoadBalancerAttributes": _modify_load_balancer_attributes,
    "SetSecurityGroups": _set_security_groups, "SetSubnets": _set_subnets,
    "SetIpAddressType": _set_ip_address_type,
    "CreateTargetGroup": _create_target_group, "DescribeTargetGroups": _describe_target_groups,
    "ModifyTargetGroup": _modify_target_group, "DeleteTargetGroup": _delete_target_group,
    "DescribeTargetGroupAttributes": _describe_target_group_attributes,
    "ModifyTargetGroupAttributes": _modify_target_group_attributes,
    "RegisterTargets": _register_targets, "DeregisterTargets": _deregister_targets,
    "DescribeTargetHealth": _describe_target_health,
    "CreateListener": _create_listener, "DescribeListeners": _describe_listeners,
    "ModifyListener": _modify_listener, "DeleteListener": _delete_listener,
    "AddListenerCertificates": _add_listener_certificates,
    "RemoveListenerCertificates": _remove_listener_certificates,
    "DescribeListenerCertificates": _describe_listener_certificates,
    "CreateRule": _create_rule, "DescribeRules": _describe_rules, "ModifyRule": _modify_rule,
    "DeleteRule": _delete_rule, "SetRulePriorities": _set_rule_priorities,
    "AddTags": _add_tags, "RemoveTags": _remove_tags, "DescribeTags": _describe_tags,
    "DescribeSSLPolicies": _describe_ssl_policies, "DescribeAccountLimits": _describe_account_limits,
    "CreateTrustStore": _create_trust_store, "DescribeTrustStores": _describe_trust_stores,
    "ModifyTrustStore": _modify_trust_store, "DeleteTrustStore": _delete_trust_store,
    "DescribeTrustStoreAssociations": _describe_trust_store_associations,
    "CreateTrustStoreRevocation": _create_trust_store_revocation,
    "DescribeTrustStoreRevocations": _describe_trust_store_revocations,
    "DeleteTrustStoreRevocation": _delete_trust_store_revocation,
}


def dispatch(store: Elbv2Store, params: dict) -> Elbv2Response:
    """Serve ONE Query-protocol request (`params` = merged query + form body)."""
    action = str(params.get("Action", "")).strip()
    if not action:
        return _error("MissingAction", "The request must contain the parameter Action.")
    fn = OPERATIONS.get(action)
    if fn is None:
        return _error("InvalidAction", f"The action {action} is not valid for this web service.")
    try:
        return fn(store, _tree(params))
    except Elbv2Error as e:
        return _error(e.code, e.message, e.status)


# ── console REST view (flat, shared by the offline server and Nano) ────────
def _err_parts(r: Elbv2Response):
    code = re.search(r"<Code>(.*?)</Code>", r.body)
    msg = re.search(r"<Message>(.*?)</Message>", r.body)
    return (code.group(1) if code else "Error", msg.group(1) if msg else "", r.status)


def _call(store, action: str, **p) -> Elbv2Response:
    r = dispatch(store, {"Action": action, **p})
    if r.status != 200:
        raise Elbv2Error(*_err_parts(r))
    return r


def _tg_names(store, lb_arn: str) -> str:
    names = []
    for t in store.target_groups.values():
        if lb_arn in _tg_lb_arns(store, t["TargetGroupArn"]):
            names.append(t["TargetGroupName"])
    return ", ".join(sorted(names)) or "None"


def _console_lb(store, lb: dict) -> dict:
    ls = [l for l in store.listeners.values() if l["LoadBalancerArn"] == lb["LoadBalancerArn"]]
    return {
        "name": lb["LoadBalancerName"], "arn": lb["LoadBalancerArn"], "dns_name": lb["DNSName"],
        "state": lb["State"]["Code"], "type": lb["Type"], "scheme": lb["Scheme"], "vpc_id": lb["VpcId"],
        "availability_zones": ", ".join(a["ZoneName"] for a in lb["AvailabilityZones"]),
        "subnets": ", ".join(a["SubnetId"] for a in lb["AvailabilityZones"]),
        "security_groups": ", ".join(lb.get("SecurityGroups") or []) or "None",
        "ip_address_type": lb["IpAddressType"], "listeners": len(ls),
        "target_groups": _tg_names(store, lb["LoadBalancerArn"]),
        "hosted_zone_id": lb["CanonicalHostedZoneId"],
        "created": lb["CreatedTime"], "instance_type": lb["Type"],
        "idle_timeout": lb["_attrs"].get("idle_timeout.timeout_seconds", "N/A"),
        "deletion_protection": lb["_attrs"].get("deletion_protection.enabled", "false"),
        "tags": dict(store.tags.get(lb["LoadBalancerArn"]) or {}),
        "data_plane": "control-plane only (in-process)",
    }


def console_list(store) -> dict:
    return {"items": [_console_lb(store, lb) for lb in sorted(store.load_balancers.values(), key=lambda x: x["LoadBalancerName"])]}


def _find_lb(store, name: str) -> dict:
    for lb in store.load_balancers.values():
        if lb["LoadBalancerName"] == name:
            return lb
    raise Elbv2Error("LoadBalancerNotFound", f"Load balancers '[{name}]' not found")


def console_get(store, name: str) -> dict:
    return _console_lb(store, _find_lb(store, name))


def console_create(store, body: dict) -> dict:
    """Console 'Create load balancer': an ALB (or NLB) across two default subnets."""
    name = str(body.get("name") or body.get("Name") or "").strip()
    typ = str(body.get("type") or "application").lower()
    subs = [f"subnet-{_short(store.account_id, 'default', i)}" for i in range(2)]
    p = {"Name": name, "Type": typ, "Scheme": body.get("scheme") or "internet-facing",
         "Subnets.member.1": subs[0], "Subnets.member.2": subs[1]}
    _call(store, "CreateLoadBalancer", **p)
    return console_get(store, name)


def console_delete(store, name: str) -> dict:
    lb = _find_lb(store, name)
    _call(store, "DeleteLoadBalancer", LoadBalancerArn=lb["LoadBalancerArn"])
    return {"deleted": name}


def console_set_tags(store, name: str, tags: dict) -> dict:
    lb = _find_lb(store, name)
    store.tags[lb["LoadBalancerArn"]] = {str(k): str(v) for k, v in (tags or {}).items()}
    store.persist()
    return console_get(store, name)


def _lb_name(store, arn: str) -> str:
    lb = store.load_balancers.get(arn)
    return lb["LoadBalancerName"] if lb else ""


def _action_summary(a: dict) -> str:
    t = a["Type"]
    if t == "forward":
        return "Forward to " + ", ".join(n.split("/")[1] if "/" in n else n for n in _action_tgs(a))
    if t == "redirect":
        return "Redirect " + a["RedirectConfig"]["StatusCode"]
    if t == "fixed-response":
        return "Fixed response " + a["FixedResponseConfig"]["StatusCode"]
    return t


def console_children(store, kind: str) -> dict:
    if kind == "target-groups":
        rows = []
        for t in sorted(store.target_groups.values(), key=lambda x: x["TargetGroupName"]):
            rows.append({"name": t["TargetGroupName"], "arn": t["TargetGroupArn"], "protocol": t.get("Protocol") or "-",
                         "port": t.get("Port") if t.get("Port") is not None else "-", "target_type": t["TargetType"],
                         "vpc_id": t.get("VpcId") or "N/A", "load_balancer": _tg_names(store, t["TargetGroupArn"]),
                         "targets": len(t["_targets"]), "health_check": t.get("HealthCheckPath") or t["HealthCheckProtocol"]})
        return {"items": rows}
    if kind == "listeners":
        rows = []
        for l in sorted(store.listeners.values(), key=lambda x: (_lb_name(store, x["LoadBalancerArn"]), x.get("Port") or 0)):
            rows.append({"name": l["ListenerArn"].rsplit("/", 1)[1], "arn": l["ListenerArn"],
                         "load_balancer": _lb_name(store, l["LoadBalancerArn"]),
                         "protocol": l.get("Protocol") or "GENEVE", "port": l.get("Port") if l.get("Port") is not None else "-",
                         "default_action": _action_summary(l["DefaultActions"][0]),
                         "rules": sum(1 for r in store.rules.values() if r["_listener"] == l["ListenerArn"])})
        return {"items": rows}
    raise Elbv2Error("ValidationError", f"Unknown collection {kind}.", 404)


def console_child_create(store, kind: str, body: dict) -> dict:
    name = str(body.get("name", "")).strip()
    if kind == "target-groups":
        vpc = next(iter(store.load_balancers.values()), {}).get("VpcId") or "vpc-" + _short(store.account_id, "vpc")
        _call(store, "CreateTargetGroup", Name=name, Protocol=body.get("protocol") or "HTTP",
              Port=str(body.get("port") or 80), VpcId=body.get("vpc_id") or vpc,
              TargetType=body.get("target_type") or "instance")
        return {"created": name}
    if kind == "listeners":
        lb = _find_lb(store, str(body.get("load_balancer") or name))
        proto = body.get("protocol") or ("HTTP" if lb["Type"] == "application" else "TCP")
        tgs = [t for t in store.target_groups.values() if t["Protocol"] == proto or lb["Type"] == "application"]
        if tgs:
            act = {"DefaultActions.member.1.Type": "forward", "DefaultActions.member.1.TargetGroupArn": tgs[0]["TargetGroupArn"]}
        else:
            act = {"DefaultActions.member.1.Type": "fixed-response", "DefaultActions.member.1.FixedResponseConfig.StatusCode": "200",
                   "DefaultActions.member.1.FixedResponseConfig.ContentType": "text/plain",
                   "DefaultActions.member.1.FixedResponseConfig.MessageBody": "OK"}
        _call(store, "CreateListener", LoadBalancerArn=lb["LoadBalancerArn"], Protocol=proto,
              Port=str(body.get("port") or 80), **act)
        return {"created": name or proto}
    raise Elbv2Error("ValidationError", f"Unknown collection {kind}.", 404)


def console_child_delete(store, kind: str, name: str) -> dict:
    if kind == "target-groups":
        arn = next((t["TargetGroupArn"] for t in store.target_groups.values() if t["TargetGroupName"] == name), "")
        _call(store, "DeleteTargetGroup", TargetGroupArn=arn)
    elif kind == "listeners":
        arn = next((l["ListenerArn"] for l in store.listeners.values() if l["ListenerArn"].rsplit("/", 1)[1] == name), "")
        _call(store, "DeleteListener", ListenerArn=arn)
    else:
        raise Elbv2Error("ValidationError", f"Unknown collection {kind}.", 404)
    return {"deleted": name}
