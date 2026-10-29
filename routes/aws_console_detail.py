"""Offline routes behind the AWS console's resource-detail tabs.

Thin FastAPI wrappers over core/aws_console_detail.py (the same engine Nano runs
in the browser): each detail tab reads/writes THIS resource's data through one of
these, shaped like the real AWS API response it mirrors.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from core import app_context as ctx
from core import aws_console_detail as D


def _srv():
    import server as server_module
    return server_module


def _net() -> D.OfflineNet:
    return D.OfflineNet(ctx.vpc_state, ctx.id_gen, ctx.now)


def _iam_role(name: str):
    for r in ctx.iam_state.get("roles", {}).values():
        if name in {r.get("role_name", ""), r.get("role_id", "")}:
            return {"role_name": r.get("role_name"), "arn": r.get("arn") or f"arn:aws:iam::{ctx.AWS_ACCOUNT_ID}:role/{r.get('role_name')}"}
    return None


def ensure_model(inst: dict) -> dict:
    before = (inst.get("vpc_id"), bool(inst.get("network_interfaces")), bool(inst.get("block_device_mappings")))
    try:
        D.ensure_instance_model(inst, _net())
    except D.DetailError:
        return inst
    if before != (inst.get("vpc_id"), True, True):
        ctx.persist_state()
    return inst


def _instance(instance_id: str) -> dict:
    inst = ctx.ec2_state.get("instances", {}).get(instance_id)
    if not isinstance(inst, dict):
        raise HTTPException(404, detail="InvalidInstanceID.NotFound")
    return ensure_model(inst)


def _fail(e: D.DetailError):
    raise HTTPException(e.status, detail={"code": e.code, "message": e.message})


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def apply_launch(instance: dict, payload: dict) -> None:
    """Called by the EC2 create route with the raw console payload."""
    try:
        D.apply_launch(instance, payload, _net(), _iam_role)
    except D.DetailError as e:
        _fail(e)
    ctx.persist_state()


def iam_principals() -> list:
    """Offline IAM users / groups / roles with the documents of their attached policies."""
    st = ctx.iam_state
    pols = st.get("policies", {})

    def docs(ids):
        out = []
        for pid in ids or []:
            p = pols.get(pid) or next((x for x in pols.values() if pid in {x.get("policy_name"), x.get("arn")}), None)
            if p:
                out.append({"name": p.get("policy_name", pid), "arn": p.get("arn") or f"arn:aws:iam::{ctx.AWS_ACCOUNT_ID}:policy/{p.get('policy_name', pid)}",
                            "document": p.get("document")})
        return out
    acct = ctx.AWS_ACCOUNT_ID
    out = []
    for u in st.get("users", {}).values():
        out.append({"type": "User", "name": u.get("user_name", ""), "arn": u.get("arn") or f"arn:aws:iam::{acct}:user/{u.get('user_name')}", "policies": docs(u.get("policies"))})
    for g in st.get("groups", {}).values():
        out.append({"type": "Group", "name": g.get("group_name", ""), "arn": g.get("arn") or f"arn:aws:iam::{acct}:group/{g.get('group_name')}", "policies": docs(g.get("policies"))})
    for r in st.get("roles", {}).values():
        out.append({"type": "Role", "name": r.get("role_name", ""), "arn": r.get("arn") or f"arn:aws:iam::{acct}:role/{r.get('role_name')}", "policies": docs(r.get("policies"))})
    return out


def register(app: FastAPI) -> None:
    # ── EC2 instance detail tabs ─────────────────────────────────────────────
    @app.get("/api/ec2/instances/{instance_id}/details")
    def ec2_details(instance_id: str):
        return D.details_view(_instance(instance_id))

    @app.put("/api/ec2/instances/{instance_id}/attributes")
    async def ec2_modify_attributes(instance_id: str, request: Request):
        inst = _instance(instance_id)
        try:
            out = D.modify_attributes(inst, await _body(request))
        except D.DetailError as e:
            _fail(e)
        ctx.persist_state()
        ctx.record_usage("ec2.modify_instance_attribute", {"instance_id": instance_id, "resource_id": instance_id})
        return out

    @app.get("/api/ec2/instances/{instance_id}/network-interfaces")
    def ec2_enis(instance_id: str):
        inst = _instance(instance_id)
        return {"network_interfaces": D.network_interfaces_view(inst, _net())}

    @app.get("/api/ec2/instances/{instance_id}/security")
    def ec2_security(instance_id: str):
        return D.security_view(_instance(instance_id), _net())

    @app.get("/api/ec2/instances/{instance_id}/storage")
    def ec2_storage(instance_id: str):
        inst = _instance(instance_id)
        vols = [v for v in ctx.ec2_state.get("volumes", {}).values()
                if any(a.get("instance_id") == instance_id for a in v.get("attachments") or [])]
        return D.storage_view(inst, vols)

    @app.get("/api/ec2/instances/{instance_id}/user-data")
    def ec2_get_user_data(instance_id: str):
        inst = _instance(instance_id)
        return {"instance_id": instance_id, "user_data": inst.get("user_data") or "", "state": inst.get("state", "")}

    @app.put("/api/ec2/instances/{instance_id}/user-data")
    async def ec2_put_user_data(instance_id: str, request: Request):
        inst = _instance(instance_id)
        try:
            out = D.set_user_data(inst, (await _body(request)).get("user_data", ""))
        except D.DetailError as e:
            _fail(e)
        ctx.persist_state()
        ctx.record_usage("ec2.modify_instance_attribute", {"instance_id": instance_id, "resource_id": instance_id, "attribute": "userData"})
        return out

    @app.get("/api/ec2/instances/{instance_id}/iam-instance-profile")
    def ec2_get_profile(instance_id: str):
        inst = _instance(instance_id)
        return {"instance_id": instance_id, "iam_instance_profile": inst.get("iam_instance_profile") or None,
                "roles": sorted(r.get("role_name", "") for r in ctx.iam_state.get("roles", {}).values())}

    @app.put("/api/ec2/instances/{instance_id}/iam-instance-profile")
    async def ec2_put_profile(instance_id: str, request: Request):
        inst = _instance(instance_id)
        try:
            out = D.associate_iam_instance_profile(inst, (await _body(request)).get("name", ""), _iam_role, ctx.AWS_ACCOUNT_ID)
        except D.DetailError as e:
            _fail(e)
        ctx.persist_state()
        ctx.record_usage("ec2.associate_iam_instance_profile", {"instance_id": instance_id, "resource_id": instance_id, "profile": out["arn"]})
        return {"instance_id": instance_id, "iam_instance_profile": out}

    @app.delete("/api/ec2/instances/{instance_id}/iam-instance-profile")
    def ec2_delete_profile(instance_id: str):
        inst = _instance(instance_id)
        try:
            out = D.disassociate_iam_instance_profile(inst)
        except D.DetailError as e:
            _fail(e)
        ctx.persist_state()
        ctx.record_usage("ec2.disassociate_iam_instance_profile", {"instance_id": instance_id, "resource_id": instance_id})
        return {"instance_id": instance_id, "iam_instance_profile": None, "disassociated": out}

    @app.get("/api/ec2/instances/{instance_id}/console-output")
    def ec2_console_output(instance_id: str):
        inst = _instance(instance_id)
        log = inst.get("console_log") or []
        text = "\n".join((e.get("output") or "").rstrip("\n") for e in log[-50:] if isinstance(e, dict) and e.get("output"))
        return D.console_output(inst, text)

    @app.get("/api/ec2/serial-console-access")
    def ec2_serial_access():
        return {"serial_console_access_enabled": bool(ctx.ec2_state.get("account_attributes", {}).get("serial_console_access"))}

    @app.put("/api/ec2/serial-console-access")
    async def ec2_set_serial_access(request: Request):
        on = (await _body(request)).get("enabled") in D._TRUE
        ctx.ec2_state.setdefault("account_attributes", {})["serial_console_access"] = on
        ctx.persist_state()
        ctx.record_usage("ec2.serial_console_access", {"enabled": on})
        return {"serial_console_access_enabled": on}

    # ── S3 bucket configuration tabs (lifecycle, CORS, encryption, BPA, policy, ownership) ──
    def _bucket(name: str) -> dict:
        b = ctx.buckets.get(name)
        if not isinstance(b, dict):
            raise HTTPException(404, detail="NoSuchBucket")
        return b

    @app.get("/api/s3/buckets/{name}")
    def s3_get_bucket(name: str):
        # GetBucket + its tag set (GetBucketTagging), which the Tags tab edits.
        b = _bucket(name)
        return {"name": name, **{k: v for k, v in b.items() if k not in ("cors", "lifecycle")}, "tags": dict(b.get("tags") or {})}

    @app.patch("/api/s3/buckets/{name}")
    async def s3_put_tagging(name: str, request: Request):
        # PutBucketTagging: the Tags tab saves the whole tag set.
        b = _bucket(name)
        tags = (await _body(request)).get("tags") or {}
        if not isinstance(tags, dict) or len(tags) > 50:
            raise HTTPException(400, detail={"code": "InvalidTag", "message": "A bucket can have up to 50 tags."})
        b["tags"] = {str(k): str(v) for k, v in tags.items() if str(k)}
        ctx.persist_state()
        ctx.record_usage("s3.put_bucket_tagging", {"bucket": name, "resource_id": name})
        return {"name": name, "tags": b["tags"]}

    @app.get("/api/s3/buckets/{name}/config/{kind}")
    def s3_get_config(name: str, kind: str):
        try:
            return {"bucket": name, "kind": kind, "value": D.s3_bucket_config(_bucket(name), kind)}
        except D.DetailError as e:
            _fail(e)

    @app.put("/api/s3/buckets/{name}/config/{kind}")
    async def s3_put_config(name: str, kind: str, request: Request):
        b = _bucket(name)
        try:
            val = D.s3_put_bucket_config(b, name, kind, (await _body(request)).get("value"))
        except D.DetailError as e:
            _fail(e)
        if kind == "policy" or kind == "public_access_block":
            b["access"] = D.s3_access_summary(b)
        ctx.persist_state()
        ctx.record_usage(f"s3.put_bucket_{kind}", {"bucket": name, "resource_id": name})
        return {"bucket": name, "kind": kind, "value": val}

    @app.delete("/api/s3/buckets/{name}/config/{kind}")
    def s3_delete_config(name: str, kind: str):
        b = _bucket(name)
        if kind not in ("lifecycle", "cors", "policy"):
            raise HTTPException(400, detail={"code": "InvalidRequest", "message": f"{kind} cannot be deleted."})
        D.s3_put_bucket_config(b, name, kind, [] if kind != "policy" else "")
        b["access"] = D.s3_access_summary(b)
        ctx.persist_state()
        ctx.record_usage(f"s3.delete_bucket_{kind}", {"bucket": name, "resource_id": name})
        return {"bucket": name, "kind": kind, "value": D.s3_bucket_config(b, kind)}

    # ── RDS DB instance tabs ────────────────────────────────────────────────
    def _db(db_id: str) -> dict:
        from routes import aws_rds as R
        db = R._rds_find_db_instance(db_id)
        if not isinstance(db, dict):
            raise HTTPException(404, detail="DBInstanceNotFound")
        before = len(db)
        D.rds_ensure(db, _net())
        if len(db) != before:
            ctx.persist_state()
        return db

    @app.get("/api/rds/databases/{db_id}/connectivity")
    def rds_connectivity(db_id: str):
        from routes import aws_rds as R
        db = _db(db_id)
        grp = R._rds_find_db_subnet_group(str(db.get("db_subnet_group_name") or "").lower()) or db.get("db_subnet_group")
        return D.rds_connectivity(db, _net(), grp)

    @app.get("/api/rds/databases/{db_id}/subnet-group")
    def rds_subnet_group(db_id: str):
        # DescribeDBSubnetGroups for the instance's group (+ its VPC security groups).
        return rds_connectivity(db_id)

    @app.get("/api/rds/databases/{db_id}/pending-maintenance")
    def rds_pending(db_id: str):
        return {"db_instance_identifier": db_id, "pending_maintenance_actions": D.rds_pending_maintenance(_db(db_id))}

    @app.get("/api/rds/databases/{db_id}/performance-insights")
    def rds_pi(db_id: str):
        return D.rds_performance_insights(_db(db_id))

    @app.get("/api/rds/databases/{db_id}/configuration")
    def rds_configuration(db_id: str):
        return D.rds_configuration(_db(db_id))

    @app.put("/api/rds/databases/{db_id}/configuration")
    async def rds_modify(db_id: str, request: Request):
        db = _db(db_id)
        try:
            out = D.rds_modify(db, await _body(request))
        except (D.DetailError, ValueError, TypeError) as e:
            if isinstance(e, D.DetailError):
                _fail(e)
            raise HTTPException(400, detail={"code": "InvalidParameterValue", "message": str(e)})
        ctx.persist_state()
        ctx.record_usage("rds.modify_db_instance", {"db_instance_identifier": db_id, "resource_id": db_id})
        return out

    @app.get("/api/rds/databases/{db_id}/events")
    def rds_events(db_id: str):
        db = _db(db_id)
        return {"db_instance_identifier": db_id, "events": D.rds_events(db, list(ctx.rds_state.get("events") or []))}

    @app.delete("/api/rds/databases/{db_id}")
    def rds_delete(db_id: str, skip_final_snapshot: bool = True, final_snapshot_identifier: str = ""):
        # DeleteDBInstance honours deletion protection, as RDS does.
        from routes import aws_rds as R
        db = R._rds_find_db_instance(db_id)
        if isinstance(db, dict):
            try:
                D.rds_check_delete(db)
            except D.DetailError as e:
                _fail(e)
        return R.api_rds_delete_database(db_id, skip_final_snapshot, final_snapshot_identifier)

    # ── DynamoDB table tabs ─────────────────────────────────────────────────
    def _table(name: str) -> dict:
        from routes import aws_dynamodb as Y
        t = Y._ddb_find_table(name)
        if not isinstance(t, dict):
            raise HTTPException(404, detail="TableNotFound")
        return D.ddb_ensure(t)

    def _ddb_local(action: str, payload: dict) -> None:
        """Mirror a table-setting change into DynamoDB Local (what the native SDK wire
        talks to offline), best-effort, the way the console's CreateTable does."""
        try:
            import json as _json
            import urllib.request
            from core import dynamodb_proxy as _ddbp
            if not _ddbp.available():
                return
            req = urllib.request.Request(_ddbp._DDB_URL, data=_json.dumps(payload).encode(), method="POST", headers={
                "X-Amz-Target": f"DynamoDB_20120810.{action}", "Content-Type": "application/x-amz-json-1.0",
                "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/dynamodb/aws4_request"})
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    @app.get("/api/dynamodb/tables/{name}/detail/{section}")
    def ddb_section(name: str, section: str):
        try:
            return {"table_name": name, "section": section, **D.ddb_section(_table(name), section)}
        except D.DetailError as e:
            _fail(e)

    @app.put("/api/dynamodb/tables/{name}/detail/{section}")
    async def ddb_update(name: str, section: str, request: Request):
        t = _table(name)
        body = await _body(request)
        try:
            out = D.ddb_update_section(t, section, body)
        except D.DetailError as e:
            _fail(e)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, detail={"code": "ValidationException", "message": str(e)})
        if section == "ttl":
            _ddb_local("UpdateTimeToLive", {"TableName": name, "TimeToLiveSpecification": {
                "Enabled": out["time_to_live_status"] == "ENABLED", "AttributeName": out["attribute_name"]}})
        elif section == "streams":
            _ddb_local("UpdateTable", {"TableName": name, "StreamSpecification": {"StreamEnabled": out["stream_enabled"],
                       **({"StreamViewType": out["view_type"]} if out["stream_enabled"] else {})}})
        elif section == "capacity" and "billing_mode" in body:
            pt = t.get("provisioned_throughput") or {}
            _ddb_local("UpdateTable", {"TableName": name, "BillingMode": t["billing_mode"],
                       **({"ProvisionedThroughput": pt} if t["billing_mode"] == "PROVISIONED" else {})})
        ctx.persist_state()
        ctx.record_usage(f"dynamodb.update_{section}", {"table_name": name, "resource_id": name})
        return {"table_name": name, "section": section, **out}

    @app.delete("/api/dynamodb/tables/{name}")
    def ddb_delete(name: str):
        # DeleteTable honours deletion protection.
        from routes import aws_dynamodb as Y
        t = Y._ddb_find_table(name)
        if isinstance(t, dict):
            try:
                D.ddb_check_delete(t)
            except D.DetailError as e:
                _fail(e)
        return Y.api_dynamodb_delete_table(name)

    # ── Lambda function tabs ────────────────────────────────────────────────
    def _fn(name: str) -> dict:
        from routes import aws_lambda as L
        fn = L._lambda_find_function(name)
        if not isinstance(fn, dict):
            raise HTTPException(404, detail="ResourceNotFoundException")
        return D.lambda_ensure(fn)

    def _role_info(name: str):
        st = ctx.iam_state
        r = next((x for x in st.get("roles", {}).values() if x.get("role_name") == name), None)
        if not r:
            return None
        pols = st.get("policies", {})
        return {"policies": [pols.get(p, {}).get("policy_name", p) for p in r.get("policies") or []],
                "trust": r.get("assume_role_policy_document")}

    @app.get("/api/lambda/functions/{name}/detail/{section}")
    def lambda_section(name: str, section: str):
        try:
            return {"function_name": name, "section": section, **D.lambda_section(_fn(name), section, _role_info)}
        except D.DetailError as e:
            _fail(e)

    @app.put("/api/lambda/functions/{name}/detail/{section}")
    async def lambda_update(name: str, section: str, request: Request):
        fn = _fn(name)
        try:
            out = D.lambda_update_section(fn, section, await _body(request), _role_info)
        except D.DetailError as e:
            _fail(e)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, detail={"code": "InvalidParameterValueException", "message": str(e)})
        if section in ("code", "env", "configuration", "role"):
            try:
                _srv()._lambda_sync_code_artifact(fn)   # the runtime invokes the synced artifact
            except Exception:
                pass
        ctx.persist_state()
        ctx.record_usage(f"lambda.update_{section.replace('-', '_')}", {"function_name": name, "resource_id": name})
        return {"function_name": name, "section": section, **out}

    # ── IAM account tabs: identity providers, password policy, Access Analyzer ──
    def _shared_resources() -> list:
        """Resource-based policies in the account (what Access Analyzer evaluates)."""
        out = []
        for name, b in ctx.buckets.items():
            if isinstance(b, dict) and b.get("policy"):
                out.append({"type": "AWS::S3::Bucket", "arn": f"arn:aws:s3:::{name}", "policy": b["policy"]})
        try:
            from routes import aws_lambda as L
            for fn in L._lambda_list_functions():
                if fn.get("permissions"):
                    out.append({"type": "AWS::Lambda::Function", "arn": fn.get("function_arn", ""), "policy": D.lambda_policy_document(fn)})
        except Exception:
            pass
        for r in ctx.iam_state.get("roles", {}).values():
            doc = r.get("assume_role_policy_document")
            if doc:
                out.append({"type": "AWS::IAM::Role", "arn": r.get("arn") or f"arn:aws:iam::{ctx.AWS_ACCOUNT_ID}:role/{r.get('role_name')}",
                            "policy": doc})
        return out

    def _iam_section(section: str) -> dict:
        st, acct = ctx.iam_state, ctx.AWS_ACCOUNT_ID
        if section == "identity-providers":
            return {"identity_providers": D.iam_identity_providers(st.setdefault("identity_providers", {}), acct)}
        if section == "password-policy":
            return D.iam_password_policy(st.setdefault("account_settings", {}))
        if section == "access-analyzer":
            an = st.setdefault("access_analyzers", [])
            return {"analyzers": D.iam_analyzers(an), "findings": D.access_findings(acct, _shared_resources()) if an else []}
        raise HTTPException(404, detail={"code": "NoSuchEntity", "message": f"Unknown IAM section {section}"})

    @app.get("/api/iam/detail/{section}")
    def iam_section(section: str):
        return _iam_section(section)

    @app.put("/api/iam/detail/{section}")
    async def iam_update(section: str, request: Request):
        st, acct = ctx.iam_state, ctx.AWS_ACCOUNT_ID
        b = await _body(request)
        try:
            if section == "identity-providers":
                if b.get("action") == "delete":
                    if st.setdefault("identity_providers", {}).pop(str(b.get("provider_id") or ""), None) is None:
                        raise D.DetailError("NoSuchEntity", "Identity provider not found.", 404)
                else:
                    D.iam_create_identity_provider(st.setdefault("identity_providers", {}), b, acct)
            elif section == "password-policy":
                D.iam_update_password_policy(st.setdefault("account_settings", {}), b)
            elif section == "access-analyzer":
                an = st.setdefault("access_analyzers", [])
                if b.get("action") == "delete":
                    st["access_analyzers"] = [a for a in an if a["name"] != b.get("name")]
                else:
                    D.iam_create_analyzer(an, b.get("name"), acct)
            else:
                raise D.DetailError("NoSuchEntity", f"Unknown IAM section {section}", 404)
        except D.DetailError as e:
            _fail(e)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, detail={"code": "ValidationError", "message": str(e)})
        ctx.persist_state()
        ctx.record_usage(f"iam.update_{section.replace('-', '_')}", {"section": section})
        return _iam_section(section)

    # ── VPC tabs: attributes, NAT gateways, endpoints, network ACLs, flow logs ──
    @app.get("/api/vpc/vpcs/{vpc_id}/detail/{section}")
    def vpc_section(vpc_id: str, section: str):
        try:
            out = D.vpc_section(_net(), vpc_id, section.replace("-", "_"))
        except D.DetailError as e:
            _fail(e)
        ctx.persist_state()   # the default network ACL is created on first view
        return {"vpc_id": vpc_id, "section": section, **out}

    @app.put("/api/vpc/vpcs/{vpc_id}/detail/{section}")
    async def vpc_update(vpc_id: str, section: str, request: Request):
        try:
            out = D.vpc_update_section(_net(), vpc_id, section.replace("-", "_"), await _body(request),
                                       lambda b: b in ctx.buckets)
        except D.DetailError as e:
            _fail(e)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, detail={"code": "InvalidParameterValue", "message": str(e)})
        ctx.persist_state()
        ctx.record_usage(f"vpc.update_{section.replace('-', '_')}", {"vpc_id": vpc_id, "resource_id": vpc_id})
        return {"vpc_id": vpc_id, "section": section, **out}

    # ── SQS queue tabs ──────────────────────────────────────────────────────
    def _queue(name: str) -> dict:
        from routes import aws_sqs as Q
        q = Q._sqs_find_queue(name)
        if not isinstance(q, dict):
            raise HTTPException(404, detail="AWS.SimpleQueueService.NonExistentQueue")
        return q

    def _queue_view(q: dict) -> dict:
        s = _srv()
        attrs = s._sqs_queue_attributes(q)
        live = [m for m in q.get("messages", []) if not m.get("deleted")]
        counts = {"available": sum(1 for m in live if not m.get("in_flight") and s._sqs_message_is_visible(m)),
                  "in_flight": sum(1 for m in live if m.get("in_flight")),
                  "delayed": sum(1 for m in live if not m.get("in_flight") and not s._sqs_message_is_visible(m))}
        return D.sqs_view(q["queue_name"], q.get("queue_arn", ""), q.get("queue_url", ""), bool(q.get("fifo_queue")), attrs, counts)

    @app.get("/api/sqs/queues/{name}/detail/{section}")
    def sqs_section(name: str, section: str):
        q = _queue(name)
        out = _queue_view(q)
        if section == "dlq":
            from routes import aws_sqs as Q
            out["queues"] = [{"queue_name": x["queue_name"], "queue_arn": x.get("queue_arn", ""), "fifo": bool(x.get("fifo_queue"))}
                             for x in Q._sqs_list_queues() if x["queue_name"] != name]
            out["source_queues"] = [x["queue_name"] for x in Q._sqs_list_queues()
                                    if (x.get("redrive_policy") or {}).get("deadLetterTargetArn") == q.get("queue_arn")]
        return {"section": section, **out}

    @app.put("/api/sqs/queues/{name}/detail/{section}")
    async def sqs_update(name: str, section: str, request: Request):
        from routes import aws_sqs as Q
        q = _queue(name)
        try:
            if section == "purge":
                D.sqs_check_purge(q)
                _srv()._sqs_purge_queue(q)
            else:
                def lookup(n):
                    t = Q._sqs_find_queue(n)
                    return {"fifo": bool(t.get("fifo_queue"))} if t else None
                attrs = D.sqs_validate(section, await _body(request), name, q.get("queue_arn", ""), bool(q.get("fifo_queue")), lookup)
                std = {k: v for k, v in attrs.items() if k in ("VisibilityTimeout", "MessageRetentionPeriod", "MaximumMessageSize",
                                                               "DelaySeconds", "ReceiveMessageWaitTimeSeconds", "RedrivePolicy")}
                if "RedrivePolicy" in std and not std["RedrivePolicy"]:
                    std["RedrivePolicy"] = {}
                if std:
                    Q._sqs_update_queue_attributes(q, std)
                extra = q.setdefault("extra_attributes", {})
                for k, v in attrs.items():
                    if k not in std:
                        if v == "":
                            extra.pop(k, None)
                        else:
                            extra[k] = v
        except D.DetailError as e:
            _fail(e)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, detail={"code": "InvalidAttributeValue", "message": str(e)})
        ctx.persist_state()
        ctx.record_usage(f"sqs.update_{section}", {"queue_name": name, "resource_id": name})
        return {"section": section, **_queue_view(q)}

    # ── Permissions tab (every service): identity policies covering a resource ──
    @app.get("/api/aws/resource-access")
    def resource_access(arn: str, service: str):
        return {"resource_arn": arn, "statements": D.resource_access(iam_principals(), arn, service)}
