"""Resource-based policies for the faithful-IAM AWS engine (feeds `state["resource_policies"]`, `state["resource_tags"]`).

Pure Python, stdlib only (Pyodide-safe, vendored for Nano). The engine (core/iam_engine/aws_eval.py) never imports a store; this module
reads the service stores' plain dict state and returns documents keyed by the exact ARN the request map emits.

Sources (store attr -> where the policy lives):
  s3      store.buckets[b]["cfg"]["policy"]            bucket policy (JSON text)               arn:aws:s3:::b   (+ object ARNs, see below)
          store.account["ecr"]["regions"][r][n]["policy"]  ECR repository policy                arn:aws:ecr:r:a:repository/n
  msg     store.queues[n]["attributes"]["Policy"]      SQS queue policy                         queue_arn
          store.topics[n]["attributes"]["Policy"]      SNS topic policy (explicit only)         topic_arn
  kms     store.keys[id]["Policy"]                     KMS key policy                           key ARN (+ every alias ARN of the key)
  sec     store.secrets[n]["resource_policy"]          Secrets Manager resource policy          secret ARN, and the suffix-less form the map emits for a by-name call
  lam     store._lambda_functions[n]["policy_statements"]   Lambda function policy             function ARN
          store._apigateway_apis[id]["policy"]         API Gateway REST API resource policy     arn:aws:execute-api:r:a:<apiId>  (see ResourcePolicyMap)

`ResourcePolicyMap.get()` widens an exact lookup so the engine needs no change: an S3 object ARN finds its bucket's policy, a qualified Lambda ARN
its function's, an execute-api ARN (`<apiId>/<stage>/<METHOD>/<path>`) its API's. Equality / iteration stay plain dict.

KMS: a key policy is the ONLY way to grant access to a key. IAM identity policies count only if the key policy enables them by naming the account
root as principal ("Enable IAM User Permissions"). `kms_key_policy_enables_iam` implements the test; the engine consumes it through
`state["resource_policy_requires_grant"]` (ARNs whose resource policy must itself grant, see aws_eval.evaluate).
"""
from __future__ import annotations

import json
from collections.abc import Mapping

REGION = "us-east-1"
_DEFAULT_ACCOUNT = "123456789012"


def _doc(raw):
    """Policy text/dict -> dict with a Statement, else None."""
    if isinstance(raw, Mapping):
        d = dict(raw)
    else:
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            d = json.loads(raw)
        except Exception:
            return None
    return d if isinstance(d, dict) and d.get("Statement") else None


class ResourcePolicyMap(dict):
    """{resource ARN: policy document} whose `get` also resolves sub-resource ARNs to the owning resource (read-only widening)."""

    def get(self, key, default=None):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        alt = self.owner_of(key)
        if alt is not None and dict.__contains__(self, alt):
            return dict.__getitem__(self, alt)
        return default

    @staticmethod
    def owner_of(arn):
        """Owning-resource ARN of a sub-resource ARN, or None."""
        if not isinstance(arn, str) or not arn.startswith("arn:"):
            return None
        parts = arn.split(":", 5)
        if len(parts) < 6:
            return None
        svc, tail = parts[2], parts[5]
        if svc == "s3":                                           # arn:aws:s3:::bucket/key -> arn:aws:s3:::bucket
            if "/" in tail:
                return "arn:%s:s3:::%s" % (parts[1], tail.split("/", 1)[0])
        elif svc == "lambda":                                     # function:name:qualifier -> function:name
            seg = tail.split(":")
            if len(seg) > 2 and seg[0] == "function":
                return ":".join(parts[:5]) + ":function:" + seg[1]
        elif svc == "execute-api":                                # <apiId>/<stage>/<METHOD>/<path> -> <apiId>
            if "/" in tail:
                return ":".join(parts[:5]) + ":" + tail.split("/", 1)[0]
        return None


def kms_key_policy_enables_iam(policy, account):
    """True when the key policy has an Allow statement whose principal is the account root (or '*'), i.e. IAM identity policies can grant access."""
    doc = _doc(policy)
    if not doc:
        return False
    stmts = doc["Statement"] if isinstance(doc["Statement"], list) else [doc["Statement"]]
    root = "arn:aws:iam::%s:root" % account
    for st in stmts:
        if not isinstance(st, dict) or st.get("Effect") != "Allow" or st.get("Condition"):
            continue
        pr = st.get("Principal")
        ents = [pr] if isinstance(pr, str) else (pr.get("AWS") if isinstance(pr, dict) else None)
        ents = [ents] if isinstance(ents, str) else (ents or [])
        if root in ents or str(account) in ents or "*" in ents:
            return True
    return False


def _acct(*stores):
    for s in stores:
        a = getattr(s, "account_id", None)
        if a:
            return str(a)
    return _DEFAULT_ACCOUNT


def _dict(v):
    return v if isinstance(v, Mapping) else {}       # the appliance's state slots are Mapping proxies, not plain dicts


def _collect(stores):
    """-> (policies, tags, requires_grant) as plain dicts."""
    pol, tags, need = {}, {}, []

    def put(arn, raw, t=None):
        d = _doc(raw)
        if d:
            pol[arn] = d
        if t:
            tags[arn] = dict(t)

    s3 = stores.get("s3")
    if s3 is not None:
        for b, meta in _dict(getattr(s3, "buckets", None)).items():
            meta = _dict(meta)
            arn = "arn:aws:s3:::%s" % b
            put(arn, _dict(meta.get("cfg")).get("policy") or meta.get("policy"), meta.get("tags"))
        for region, repos in _dict(_dict(_dict(getattr(s3, "account", None)).get("ecr")).get("regions")).items():
            acct = _acct(s3)
            for n, r in _dict(repos).items():
                if isinstance(r, Mapping):
                    put("arn:aws:ecr:%s:%s:repository/%s" % (region, acct, n), r.get("policy"), r.get("tags") if isinstance(r.get("tags"), Mapping) else None)

    msg = stores.get("msg")
    if msg is not None:
        for n, q in _dict(getattr(msg, "queues", None)).items():
            q = _dict(q)
            arn = q.get("queue_arn") or "arn:aws:sqs:%s:%s:%s" % (REGION, _acct(msg), n)
            put(arn, _dict(q.get("attributes")).get("Policy"), q.get("tags"))
        for n, t in _dict(getattr(msg, "topics", None)).items():
            t = _dict(t)
            arn = t.get("topic_arn") or "arn:aws:sns:%s:%s:%s" % (REGION, _acct(msg), n)
            put(arn, _dict(t.get("attributes")).get("Policy"), t.get("tags"))

    kms = stores.get("kms")
    if kms is not None:
        acct = _acct(kms)
        aliases = _dict(getattr(kms, "aliases", None))
        for kid, k in _dict(getattr(kms, "keys", None)).items():
            if not isinstance(k, Mapping):
                continue
            d = _doc(k.get("Policy"))
            arns = ["arn:aws:kms:%s:%s:key/%s" % (REGION, acct, kid)]
            arns += ["arn:aws:kms:%s:%s:%s" % (REGION, acct, a) for a, target in aliases.items() if target == kid]   # the map cannot resolve alias -> key
            for arn in arns:
                put(arn, k.get("Policy"), k.get("Tags") if isinstance(k.get("Tags"), Mapping) else None)
                if d and not kms_key_policy_enables_iam(d, acct):
                    need.append(arn)
                elif not d:
                    need.append(arn)        # a key with no readable policy grants nothing to IAM
    sec = stores.get("sec")
    if sec is not None:
        acct = _acct(sec)
        for n, s in _dict(getattr(sec, "secrets", None)).items():
            s = _dict(s)
            full = s.get("arn") or "arn:aws:secretsmanager:%s:%s:secret:%s" % (REGION, acct, n)
            t = s.get("tags") if isinstance(s.get("tags"), Mapping) else None
            put(full, s.get("resource_policy"), t)
            put("arn:aws:secretsmanager:%s:%s:secret:%s" % (REGION, acct, n), s.get("resource_policy"), t)    # by-name calls

    lam = stores.get("lam")
    if lam is not None:
        acct = _acct(lam)
        for n, fn in _dict(getattr(lam, "_lambda_functions", None)).items():
            fn = _dict(fn)
            stmts = list(_dict(fn.get("policy_statements")).values())
            if stmts:
                put(fn.get("arn") or "arn:aws:lambda:%s:%s:function:%s" % (REGION, acct, n),
                    {"Version": "2012-10-17", "Id": "default", "Statement": stmts})
        try:
            apis = _dict(getattr(lam, "_apigateway_apis", None))
        except Exception:
            apis = {}
        for api_id, api in apis.items():
            if isinstance(api, Mapping):
                put("arn:aws:execute-api:%s:%s:%s" % (REGION, acct, api_id), api.get("policy"))
    return pol, tags, need


def aws_resource_policies(stores):
    """stores: {"s3","msg","kms","sec","lam"} (any subset; each the service store object). -> ResourcePolicyMap {resource ARN: policy document}."""
    return ResourcePolicyMap(_collect(stores or {})[0])


def aws_resource_tags(stores):
    """{resource ARN: tags} for aws:ResourceTag/<k> conditions."""
    return _collect(stores or {})[1]


def aws_requires_grant(stores):
    """ARNs whose resource policy must itself grant access (KMS keys that do not enable IAM policies)."""
    return _collect(stores or {})[2]


def aws_resource_state(stores):
    """The three state keys at once (one scan)."""
    pol, tags, need = _collect(stores or {})
    return {"resource_policies": ResourcePolicyMap(pol), "resource_tags": tags, "resource_policy_requires_grant": need}


def host_stores():
    """Bind to the live substrate: the appliance stores (Mesh) or the Nano registry. Missing services are simply absent."""
    out = {}
    try:
        from core import appliance_stores as A
        for key, fn in (("s3", "s3_store"), ("msg", "messaging_store"), ("kms", "aws_kms_store"), ("sec", "aws_secrets_store"), ("lam", "lambda_store")):
            try:
                out[key] = getattr(A, fn)()
            except Exception:
                pass
        return out
    except ImportError:
        pass
    try:
        from core import nano_registry
        reg = nano_registry.get()
        for key, name in (("s3", "s3"), ("msg", "msg"), ("kms", "kms"), ("sec", "sec"), ("lam", "compute")):
            if reg.get(name) is not None:
                out[key] = reg[name]
    except Exception:
        pass
    return out


# ----------------------------------------------------------------------------- organisation policies (SCP / RCP)
_SCP, _RCP = "SERVICE_CONTROL_POLICY", "RESOURCE_CONTROL_POLICY"


def org_levels(store, account=None):
    """-> {"scps": [[doc,...], ...], "rcps": [...]}: one level per org node on the path root -> OU... -> account (attachments modelled by
    core/organizations_core.py: store.extras["org"]["attachments"] {target_id: [policy ids]}, store.org_policies {id: {type, content}}).
    Every level must allow (the engine's rule).  AWS: SCPs never restrict the MANAGEMENT account, so it gets none unless the lab opts in
    with store.extras["org"]["scp_apply_to_management"] = True (Vyomi extension for single-account learners).  No org -> no levels."""
    org = (getattr(store, "extras", None) or {}).get("org")
    if not isinstance(org, Mapping):
        return {"scps": [], "rcps": []}
    account = str(account or getattr(store, "account_id", "") or "")
    if account and account == str(org.get("master_account_id")) and not org.get("scp_apply_to_management"):
        return {"scps": [], "rcps": []}
    accounts, ous, pols = _dict(org.get("accounts")), _dict(org.get("ous")), _dict(getattr(store, "org_policies", None))
    path, cur = [], account
    node = accounts.get(account)
    if node is None:
        return {"scps": [], "rcps": []}
    path.append(account)
    cur = node.get("parent")
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        path.append(cur)
        cur = _dict(ous.get(cur)).get("parent")
    path.reverse()                                              # root first
    out = {"scps": [], "rcps": []}
    att = _dict(org.get("attachments"))
    for kind, key in ((_SCP, "scps"), (_RCP, "rcps")):
        for target in path:
            docs = []
            for pid in att.get(target) or []:
                p = _dict(pols.get(pid))
                d = _doc(p.get("content")) if p.get("type") == kind else None
                if d:
                    docs.append(d)
            if docs:
                out[key].append(docs)
    return out


_override = None


def set_host_stores(fn):
    """Tests / alternative hosts: fn() -> stores dict (see aws_resource_policies)."""
    global _override
    _override = fn


def aws_state_extras(store, stores=None):
    """Keys to merge into aws_state(): resource_policies, resource_tags, resource_policy_requires_grant, and scps/rcps when an org attaches any."""
    if stores is None:
        stores = _override() if _override else host_stores()
    out = aws_resource_state(stores)
    lv = org_levels(store)
    if lv["scps"]:
        out["scps"] = lv["scps"]
    if lv["rcps"]:
        out["rcps"] = lv["rcps"]
    return out
