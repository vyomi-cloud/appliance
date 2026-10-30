"""GCP console summary, consolidation, VPC reconciliation, and enforcement routes.

Extracted from server.py — contains the /api/gcp/console/* route handlers
plus the _gcp_vpc_reconcile() helper.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from core import app_context as ctx

# Aliases
STATE = ctx.STATE
_gcp_project_name = ctx.gcp_project_name
_gcp_record_matches_project = ctx.gcp_record_matches_project
_gcp_state_proxies = ctx.gcp_state_proxies
_gcp_active_space_dict = ctx.gcp_active_space_dict
_persist_state = ctx.persist_state

_GCP_CONSOLE_COLLECTIONS = ctx._GCP_CONSOLE_COLLECTIONS
_GCP_IAM_NESTED_COLLECTIONS = ctx._GCP_IAM_NESTED_COLLECTIONS

gcp_compute_state = ctx.gcp_compute_state
gcp_vpc_state = ctx.gcp_vpc_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gcp_vpc_reconcile() -> dict:
    """Apply firewall enforcement (or restore full access) on every LXD-backed
    instance in the active space."""
    from core import gcp_vpc_enforce
    space = _gcp_active_space_dict()
    enforce = bool(space.get("enforce_vpc"))
    firewalls = None
    try:   # v4 C0d: the shared Compute core holds the firewall rules when unified
        from routes import gcp_firestore_compute_unified as _gfc
        firewalls = _gfc.firewall_rules()
    except Exception:
        firewalls = None
    if firewalls is None:
        firewalls = [fw for fw in gcp_vpc_state.get("firewalls", {}).values() if isinstance(fw, dict)]
    applied: list[str] = []
    for inst in gcp_compute_state.get("instances", {}).values():
        if not isinstance(inst, dict) or str(inst.get("runtime_backend") or "") != "lxd":
            continue
        container = inst.get("container_name") or (f"cloudlearn-{inst.get('instance_id')}" if inst.get("instance_id") else "")
        if not container:
            continue
        if enforce:
            tags = inst.get("tags") or []
            rules = [fw for fw in firewalls if gcp_vpc_enforce.rule_applies(fw, tags)]
            script = gcp_vpc_enforce.build_script(rules)
        else:
            script = gcp_vpc_enforce.clear_script()
        try:
            import server
            server._lxd_run(["exec", container, "--", "sh", "-c", script], timeout=30)
            applied.append(container)
        except Exception:
            pass
    return {"enforced": enforce, "instances": applied}


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register(app: FastAPI) -> None:
    """Mount all /api/gcp/console/* routes."""

    # Lazy import for helpers that still live in server.py
    def _srv():
        import server
        return server

    @app.get("/api/gcp/console/summary")
    def api_gcp_console_summary(project: str = ""):
        """Per-service GCP resource counts read straight from the Internal DB."""
        target = _gcp_project_name(project) if project else ""
        proxies = _gcp_state_proxies()

        def coll_of(service_key: str, collection: str) -> dict:
            c = proxies[service_key].get(collection, {})
            return c if isinstance(c, dict) else {}

        def count(service_key: str, collection: str) -> int:
            return sum(1 for rec in coll_of(service_key, collection).values()
                       if isinstance(rec, dict) and _gcp_record_matches_project(rec, target))

        def count_iam(collection: str) -> int:
            coll = coll_of("gcp_iam", collection)
            if target:
                sub = coll.get(target, {})
                return sum(1 for rec in sub.values() if isinstance(rec, dict)) if isinstance(sub, dict) else 0
            return sum(sum(1 for rec in sub.values() if isinstance(rec, dict))
                       for sub in coll.values() if isinstance(sub, dict))

        docs = coll_of("gcp_firestore", "documents")
        collections: set[str] = set()
        if isinstance(docs, dict):
            for rec in docs.values():
                if not (isinstance(rec, dict) and _gcp_record_matches_project(rec, target)):
                    continue
                name = str(rec.get("name") or rec.get("path") or "")
                if "/documents/" in name:
                    tail = name.split("/documents/", 1)[1]
                    collections.add(tail.split("/", 1)[0])
                elif rec.get("collection"):
                    collections.add(str(rec.get("collection")))

        # Firestore: when delegating to the emulator, count distinct root collections there.
        try:
            from core import gcp_firestore_emulator as _fe
            if _fe.available():
                collections = set()
                for d in _fe.list_root(target or _gcp_project_name(""), "(default)"):
                    nm = str(d.get("name") or "")
                    if "/documents/" in nm:
                        collections.add(nm.split("/documents/", 1)[1].split("/", 1)[0])
        except Exception:
            pass

        def _pubsub_count() -> int:
            try:
                from core import gcp_pubsub_emulator as _pe
                from core import wire_ingress as _wi_ps
                if _pe.available() and not _wi_ps.is_unified("gcp_pubsub"):
                    return len(_pe.list_topics(target or _gcp_project_name("")))
            except Exception:
                pass
            return count("gcp_pubsub", "topics")

        services = {
            "gcp-compute": count("gcp_compute", "instances"),
            "gcp-storage": count("gcp_storage", "buckets"),
            "gcp-cloudsql": count("gcp_sql", "instances"),
            "gcp-pubsub": _pubsub_count(),
            "gcp-firestore": len(collections),
            "gcp-functions": count("gcp_functions", "functions"),
            "gcp-apigateway": count("gcp_apigateway", "apis"),
            "gcp-vpc": count("gcp_vpc", "networks"),
            "gcp-iam": count_iam("service_accounts"),
        }
        try:   # v4 C0d: Compute / VPC / Firestore counts come from the shared cores' state
            from routes import gcp_firestore_compute_unified as _gfc
            services.update(_gfc.summary_counts(target))
        except Exception:
            pass
        try:   # v4 C0g: Pub/Sub topics come from the shared core's state (project-scoped)
            from routes import gcp_pubsub_unified as _gps
            services.update(_gps.summary_counts(target))
        except Exception:
            pass
        return {"project": target, "services": services}

    @app.post("/api/gcp/console/consolidate")
    async def api_gcp_consolidate_project(request: Request):
        """Re-key every GCP resource in the active space onto a single canonical
        project (space = project). Fixes legacy scatter."""
        payload = {}
        if request is not None:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
        payload = payload if isinstance(payload, dict) else {}
        target = _gcp_project_name(payload.get("project"))
        proxies = _gcp_state_proxies()
        updated = 0

        def _retarget(rec: dict, old: str) -> bool:
            changed = False
            if rec.get("project") != target:
                rec["project"] = target
                changed = True
            if old and old != target:
                for field in ("name", "selfLink", "topic", "subscription", "network", "subnetwork", "email"):
                    value = rec.get(field)
                    if isinstance(value, str) and old in value:
                        if field == "email":
                            rec[field] = value.replace(f"@{old}.", f"@{target}.")
                        else:
                            rec[field] = value.replace(f"projects/{old}/", f"projects/{target}/")
                        changed = True
            return changed

        # IAM nests records UNDER a project key ({project: {key: record}})
        iam_store = proxies["gcp_iam"]
        for collection in _GCP_IAM_NESTED_COLLECTIONS:
            nested = iam_store.get(collection)
            if not isinstance(nested, dict):
                continue
            merged: dict = {}
            for proj_key, sub in list(nested.items()):
                if not isinstance(sub, dict):
                    continue
                for key, rec in sub.items():
                    if not isinstance(rec, dict):
                        continue
                    if _retarget(rec, str(rec.get("project") or proj_key or "")):
                        updated += 1
                    merged[key] = rec
            nested.clear()
            nested[target] = merged

        _record_fields = ("selfLink", "kind", "uniqueId", "email")

        def _is_record(node: dict) -> bool:
            return isinstance(node.get("name"), str) or any(f in node for f in _record_fields)

        def _walk(node) -> None:
            nonlocal updated
            if not isinstance(node, dict):
                return
            if _is_record(node):
                if _retarget(node, str(node.get("project") or "")):
                    updated += 1
                return
            if isinstance(node.get("project"), str):
                node.pop("project", None)
                updated += 1
            for value in list(node.values()):
                _walk(value)

        for service_key in ("gcp_compute", "gcp_storage", "gcp_sql", "gcp_pubsub",
                            "gcp_firestore", "gcp_functions", "gcp_apigateway", "gcp_vpc"):
            proxy = proxies[service_key]
            for collection in list(proxy.keys()):
                _walk(proxy.get(collection))
        try:
            _persist_state()
        except Exception:
            pass
        try:
            _srv()._refresh_cloudsim_gcp_summary()
        except Exception:
            pass
        return {"project": target, "updated": updated}

    @app.post("/api/gcp/console/vpc-reconcile")
    def api_gcp_vpc_reconcile():
        """Re-apply VPC firewall enforcement to all governed instances."""
        return _gcp_vpc_reconcile()

    @app.get("/api/gcp/console/enforcement")
    def api_gcp_get_enforcement():
        """Per-space enforcement flags + the principal IAM checks run as."""
        space = _gcp_active_space_dict()
        return {
            "iam": bool(space.get("enforce_iam")),
            "vpc": bool(space.get("enforce_vpc")),
            "principal": space.get("active_principal") or "root",
        }

    @app.post("/api/gcp/console/enforcement")
    async def api_gcp_set_enforcement(request: Request):
        payload = {}
        if request is not None:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
        payload = payload if isinstance(payload, dict) else {}
        space = _gcp_active_space_dict()
        if "iam" in payload:
            space["enforce_iam"] = bool(payload["iam"])
        if "vpc" in payload:
            space["enforce_vpc"] = bool(payload["vpc"])
        if "principal" in payload:
            space["active_principal"] = str(payload["principal"] or "root")
        try:
            _persist_state()
        except Exception:
            pass
        if "vpc" in payload:
            try:
                _gcp_vpc_reconcile()
            except Exception:
                pass
        return {
            "iam": bool(space.get("enforce_iam")),
            "vpc": bool(space.get("enforce_vpc")),
            "principal": space.get("active_principal") or "root",
        }
