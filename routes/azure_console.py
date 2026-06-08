"""Azure console summary route extracted from server.py."""
from __future__ import annotations

from fastapi import FastAPI
from core import app_context as ctx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _azure_nsg_reconcile() -> dict:
    """Apply NSG iptables enforcement (or clear) on every LXD-backed Azure VM
    in the active space.  Mirrors ``_gcp_vpc_reconcile`` in routes/gcp_console.py."""
    from core import azure_nsg_enforce
    arm = ctx._azure_state_dict()

    # Collect all NSG security rules from all NSGs in the space.
    all_nsg_rules: list[dict] = []
    for rec in arm.values():
        if not isinstance(rec, dict):
            continue
        ft = str(rec.get("_type", "")).lower()
        # Top-level NSG resources carry inline securityRules.
        if ft == "microsoft.network/networksecuritygroups":
            props = rec.get("properties") or {}
            for rule in (props.get("securityRules") or []):
                if isinstance(rule, dict) and azure_nsg_enforce.rule_applies(rule):
                    all_nsg_rules.append(rule)
        # Child security rule resources (created via the nested ARM path).
        if ft == "microsoft.network/networksecuritygroups/securityrules":
            if azure_nsg_enforce.rule_applies(rec):
                all_nsg_rules.append(rec)

    has_rules = bool(all_nsg_rules)

    # Build the iptables script (apply or clear).
    if has_rules:
        script = azure_nsg_enforce.build_script(all_nsg_rules)
    else:
        script = azure_nsg_enforce.clear_script()

    # Walk every Azure VM that has a real LXD container and push the script.
    applied: list[str] = []
    for rec in arm.values():
        if not isinstance(rec, dict):
            continue
        if str(rec.get("_type", "")).lower() != "microsoft.compute/virtualmachines":
            continue
        props = rec.get("properties") or {}
        rt = props.get("runtime") or {}
        if str(rt.get("backend", "")) != "lxd":
            continue
        container = rt.get("containerName")
        if not container:
            continue
        try:
            import server
            server._lxd_run(["exec", container, "--", "sh", "-c", script], timeout=30)
            applied.append(container)
        except Exception:
            pass

    return {"enforced": has_rules, "ruleCount": len(all_nsg_rules), "instances": applied}


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register(app: FastAPI) -> None:

    @app.get("/api/azure/console/summary")
    def api_azure_console_summary():
        from providers import azure_services as provider_azure_services
        az = provider_azure_services
        type_to_key = {(c["namespace"] + "/" + c["type"]).lower(): c["key"] for c in az.RESOURCE_CATALOG}
        counts = {c["key"]: 0 for c in az.RESOURCE_CATALOG}
        for rec in list(ctx._azure_state_dict().values()):
            ft = str(rec.get("_type", "")).lower()
            if ft in type_to_key:
                counts[type_to_key[ft]] += 1
        return {"subscription": az.DEFAULT_SUBSCRIPTION, "resourceGroup": az.DEFAULT_RG,
                "counts": counts, "total": sum(counts.values())}

    @app.post("/api/azure/nsg/reconcile")
    def api_azure_nsg_reconcile():
        """Apply (or clear) NSG iptables rules on all LXD-backed Azure VMs."""
        return _azure_nsg_reconcile()
