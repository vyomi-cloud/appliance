"""Marketplace of onboarded simulators + per-simulator Pro/Max trial (see core/sim_marketplace.py)."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from core import app_context as ctx
from core import sim_marketplace as mk

_PUBLIC_MAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
                "icloud.com", "me.com", "proton.me", "protonmail.com", "aol.com", "msn.com"}


def _license_ctx() -> dict:
    """Tier/entitlement facts, read the same way /api/license/status does."""
    from routes.licensing import _normalize_tier
    from core import license_remote as _lr
    try:
        tenant = ctx.tenant_dict(ctx.active_tenant_id()) or {}
    except Exception:
        tenant = {}
    lic = dict(ctx.STATE.get("license") or {})
    claims = ctx.STATE.get("license_claims") or {}
    tier = _normalize_tier(tenant.get("license_tier") or lic.get("tier") or "free")
    try:
        if _lr.is_sub_expired(claims):
            tier = "free"
    except Exception:
        pass
    trial_on = bool(claims.get("trial"))
    if trial_on:                      # the portal's account-level trial is NOT a licence: it only makes Pro/Max explorable
        tier = "free"
    primary = str(tenant.get("primary_cloud") or claims.get("primary_cloud") or lic.get("primary_cloud") or "")
    sub = str(claims.get("sub") or lic.get("email") or lic.get("issued_to") or "")
    org = str(claims.get("org") or claims.get("org_name") or lic.get("org") or "").strip()
    dom = sub.split("@", 1)[1].lower() if "@" in sub else ""
    by = org or (dom if dom and dom not in _PUBLIC_MAIL else "")
    import os
    portal = (os.environ.get("CLOUDLEARN_LICENSE_BACKEND_URL") or _lr.DEFAULT_BACKEND_URL).rstrip("/")
    owned = [str(x).lower() for x in (claims.get("simulators") or lic.get("simulators") or []) if x]
    return {"owned": owned, "tier": tier, "primary": primary, "licensed_by": by, "email": sub,
            "upgrade_url": portal + "/pricing", "portal": portal}


def _covered(lc: dict, sims=None) -> dict:
    return {s["id"]: mk.licensed_tier(s["id"], lc["tier"], lc["primary"], lc.get("owned") or ()) for s in (sims if sims is not None else mk.SIMULATORS)}


def _spaces_map() -> dict:
    ss = ctx.STATE.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    return ss.setdefault("spaces", {})


def _mine(sp: dict) -> bool:
    return isinstance(sp, dict) and (sp.get("tenant_id") or ctx.DEFAULT_TENANT_ID) == ctx.active_tenant_id()


def sweep_and_annotate(spaces: list[dict]):
    """Called by GET /api/spaces: apply expiry rules, then compute each space's
    {tier, tier_source, trial}. Returns (spaces_without_removed, {space_id: extras}). Never raises."""
    extras: dict = {}
    try:
        lc = _license_ctx()
        cov = _covered(lc)
        removed = mk.sweep_expired(ctx.STATE, _spaces_map(), cov, scope=ctx.active_tenant_id(),
                                   delete=lambda i: ctx.PLATFORM.delete_space(i))
        if removed:
            gone = {r["space_id"] for r in removed}
            spaces = [s for s in spaces if s.get("space_id") not in gone]
            ctx.persist_state()
        for s in spaces:
            sim = str(s.get("provider") or "").lower()
            eff = mk.effective(_spaces_map().get(s.get("space_id")) or s, cov.get(sim))
            extras[s.get("space_id")] = {"tier": eff["tier"], "tier_source": eff["source"], "trial": eff["trial"]}
    except Exception:
        pass
    return spaces, extras


def register(app: FastAPI) -> None:

    @app.get("/api/marketplace/simulators")
    def marketplace_simulators():
        lc = _license_ctx()
        cov = _covered(lc)
        scope = ctx.active_tenant_id()
        mine = {str(s.get("provider") or "").lower(): s for s in _spaces_map().values() if _mine(s)}
        mk.sweep_expired(ctx.STATE, _spaces_map(), cov, scope=scope, delete=lambda i: ctx.PLATFORM.delete_space(i))
        mine = {p: s for p, s in mine.items() if s.get("space_id") in _spaces_map()}
        ended = mk.ended_map(ctx.STATE, scope)
        cards = []
        for sim in mk.SIMULATORS:
            c = mk.card_state(sim, mine.get(sim["id"]), cov[sim["id"]], ended)
            c["licensed_by"] = lc["licensed_by"] if c["licensed"] else ""
            c["offers"] = mk.offers_for(sim["id"], cov[sim["id"]], lc["portal"])
            c["owned"] = sim["id"] in (lc.get("owned") or []) and not mk.licensed_tier(sim["id"], lc["tier"], lc["primary"])
            cards.append(c)
        return {"simulators": cards, "upgrade_url": lc["upgrade_url"],
                "licence": mk.licence_summary(lc["tier"], lc["primary"], lc.get("owned") or (), lc["portal"])}

    @app.post("/api/marketplace/simulators/{sim_id}/add")
    def marketplace_add(sim_id: str):
        sim = mk.get_simulator(sim_id)
        if not sim:
            raise HTTPException(404, detail="UnknownSimulator")
        lc = _license_ctx()
        cov = _covered(lc)
        scope = ctx.active_tenant_id()
        existing = next((s for s in _spaces_map().values() if _mine(s) and str(s.get("provider")).lower() == sim_id), None)
        if existing:
            return {"created": False, "space_id": existing["space_id"]}
        if not sim["free_tier"] and not cov[sim_id]:
            if sim_id in mk.ended_map(ctx.STATE, scope):
                raise HTTPException(403, detail={"ok": False, "code": "trial_ended",
                    "reason": f"The {sim['name']} trial has ended. A licence is required to add it again.",
                    "upgrade_url": lc["upgrade_url"]})
        # Marketplace adds are exactly one space per simulator, so they are not subject to the
        # tier's generic max_spaces cap (Free caps that at 1, which would block AWS+GCP+Azure on Free).
        space = ctx.PLATFORM.create_space({"provider": sim_id, "name": sim["name"]})
        sp = _spaces_map().get(space["space_id"])
        if sp is not None:
            sp["tenant_id"] = ctx.active_tenant_id()
        space["tenant_id"] = ctx.active_tenant_id()
        ctx.record_usage("space.create", {"space_id": space.get("space_id"), "provider": sim_id,
                                          "name": space.get("name"), "tenant_id": ctx.active_tenant_id(), "via": "marketplace"})
        ctx.persist_state()
        if sp is not None and not sim["free_tier"] and not cov[sim_id]:
            mk.start_trial(sp)          # no Free tier: adding it IS starting its one trial
            ctx.persist_state()
        return {"created": True, "space_id": space["space_id"]}

    @app.post("/api/spaces/{space_id}/trial/start")
    def space_trial_start(space_id: str, payload: dict | None = None):
        sp = _spaces_map().get(space_id)
        if not _mine(sp):
            raise HTTPException(404, detail="SimulationSpaceNotFound")
        lc = _license_ctx()
        cov = _covered(lc)
        sim = mk.get_simulator(str(sp.get("provider") or "").lower())
        if sim and cov.get(sim["id"]):
            raise HTTPException(409, detail={"ok": False, "code": "already_licensed",
                                             "reason": "This simulator is already covered by your licence."})
        tier = str((payload or {}).get("tier") or "pro").lower()
        started = mk.start_trial(sp, tier)
        if started:
            ctx.persist_state()
        eff = mk.effective(sp, None)
        return {"started": started, "tier": eff["tier"], "trial": eff["trial"]}
