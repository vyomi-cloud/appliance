"""Marketplace of onboarded simulator platforms + the per-simulator Pro/Max trial.

Pure logic (no FastAPI / no global state) so it is unit-testable; the HTTP wiring
lives in routes/marketplace.py.

RULES
-----
* SIMULATORS is the single registry of onboarded platforms (today AWS, GCP, Azure).
  Add a 4th by appending one dict; the Marketplace UI is generated from it.
* One space per simulator. Adding a simulator is idempotent.
* Every tier a space shows is *effective*, computed here:
    1. licence covers the simulator (tier_policy entitlement: Max = every cloud,
       Pro = its primary cloud)           -> that tier, source "license", never expires
    2. else a per-simulator trial is running (space.trial_ends_at in the future)
                                          -> trial tier (pro|max), source "trial"
    3. else                               -> "free"
* ONE trial clock PER SIMULATOR (TRIAL_DAYS = 14), started explicitly by the user
  ("Try Pro") and stored on the space: trial_started_at / trial_ends_at / trial_tier.
  It is never restarted (one trial per simulator).
* When a trial is exhausted: simulator.free_tier -> the space falls back to Free,
  nothing is deleted. Not free_tier -> the space is REMOVED (data deleted) and the
  simulator is recorded in state["marketplace"]["trial_ended"], which makes the
  Marketplace card show "Trial ended" and refuse re-adding without a licence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

TRIAL_DAYS = 14
TRIAL_TIERS = ("pro", "max")

# Registry of onboarded simulator platforms. free_tier=False means the simulator has
# no Free tier: it can only be used under a licence or a (single) trial.
SIMULATORS: list[dict[str, Any]] = [
    {"id": "aws",   "name": "AWS",          "free_tier": True},
    {"id": "gcp",   "name": "Google Cloud", "free_tier": True},
    {"id": "azure", "name": "Azure",        "free_tier": True},
]

# Paid offers shown on every simulator card. SOURCE OF TRUTH = the portal pricing page
# (portal/app/templates/pricing.html: Pro "$19 / month", Max "$29 / month"; USD, billed in INR at
# checkout). Checkout URLs follow portal/app/checkout.py: /checkout?tier=pro&period=monthly&primary_cloud=<cloud>
# (Pro is per-cloud) and /checkout?tier=max&period=monthly. No payment code lives in the appliance.
OFFERS = {"pro": {"price_usd": 19, "per": "/ month"}, "max": {"price_usd": 29, "per": "/ month"}}
_RANK = {"free": 0, "pro": 1, "max": 2}


def offers_for(sim_id: str, covered_tier: str | None, portal: str = "https://vyomi.cloud") -> list[dict]:
    """Offers still worth buying for this simulator: all of them when unlicensed, Max when on Pro, none on Max."""
    have = _RANK.get(covered_tier or "free", 3 if covered_tier else 0)
    portal = portal.rstrip("/")
    out = []
    for tier, o in OFFERS.items():
        if _RANK[tier] <= have:
            continue
        url = f"{portal}/checkout?tier={tier}&period=monthly" + (f"&primary_cloud={sim_id}" if tier == "pro" else "")
        out.append({"tier": tier, "price_usd": o["price_usd"], "per": o["per"], "url": url})
    return out


_NOT_LICENSED_TIERS = ("free", "nano")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def get_simulator(sim_id: str, sims: Iterable[dict] | None = None) -> dict | None:
    for s in (sims if sims is not None else SIMULATORS):
        if s["id"] == sim_id:
            return s
    return None


def licensed_tier(sim_id: str, tier: str | None, primary_cloud: str | None = "") -> str | None:
    """The paid tier ("pro"/"max"/...) covering this simulator, else None.
    Uses core.tier_policy provider entitlement (Pro = one cloud, Max = all)."""
    from core import tier_policy as tp
    t = tp.normalize_tier(tier)
    if t in _NOT_LICENSED_TIERS:
        return None
    providers = tp.policy_for(t).get("providers")
    if providers == "primary_cloud_only":
        return t if primary_cloud and primary_cloud == sim_id else None
    if isinstance(providers, (list, tuple, set)):
        return t if sim_id in providers else None
    return None


def trial_info(space: dict | None, now: datetime | None = None) -> dict:
    now = now or now_utc()
    started = parse_iso((space or {}).get("trial_started_at"))
    ends = parse_iso((space or {}).get("trial_ends_at"))
    if not started or not ends:
        return {"state": "none"}
    left = (ends - now).total_seconds()
    base = {"tier": (space or {}).get("trial_tier") or "pro",
            "started_at": iso(started), "ends_at": iso(ends)}
    if left > 0:
        return {**base, "state": "active", "seconds_left": int(left),
                "days_left": max(1, int(-(-left // 86400)))}   # ceil, so "1 day left" until it ends
    return {**base, "state": "ended", "seconds_left": 0, "days_left": 0}


def effective(space: dict | None, covered_tier: str | None, now: datetime | None = None) -> dict:
    """{tier, source, trial} for a space (or a not-yet-added simulator when space is None)."""
    tr = trial_info(space, now)
    if covered_tier:
        return {"tier": covered_tier, "source": "license", "trial": tr}
    if tr["state"] == "active":
        return {"tier": tr["tier"], "source": "trial", "trial": tr}
    return {"tier": "free", "source": "free", "trial": tr}


def start_trial(space: dict, tier: str = "pro", now: datetime | None = None) -> bool:
    """Start the one 14-day trial for this simulator's space. False if one was already
    started (active or ended): the clock is never reset."""
    if space.get("trial_started_at"):
        return False
    tier = tier if tier in TRIAL_TIERS else "pro"
    now = now or now_utc()
    space["trial_started_at"] = iso(now)
    space["trial_ends_at"] = iso(now + timedelta(days=TRIAL_DAYS))
    space["trial_tier"] = tier
    return True


def ended_map(state: dict, scope: str = "default") -> dict:
    return state.setdefault("marketplace", {}).setdefault("trial_ended", {}).setdefault(scope, {})


def sweep_expired(state: dict, spaces_map: dict, covered: dict[str, str | None],
                  sims: Iterable[dict] | None = None, now: datetime | None = None,
                  scope: str = "default", delete=None) -> list[dict]:
    """Remove spaces of no-free-tier simulators whose trial ran out (and whose
    simulator is not licensed). `covered` = {sim_id: licensed tier or None}.
    `delete(space_id)` performs the removal (defaults to popping from spaces_map).
    Returns [{space_id, simulator}] removed."""
    now = now or now_utc()
    removed: list[dict] = []
    for sid, sp in list(spaces_map.items()):
        if not isinstance(sp, dict):
            continue
        sim = get_simulator(str(sp.get("provider") or "").lower(), sims)
        if not sim or sim.get("free_tier", True) or covered.get(sim["id"]):
            continue
        if trial_info(sp, now)["state"] != "ended":
            continue
        (delete or (lambda i: spaces_map.pop(i, None)))(sid)
        ended_map(state, scope)[sim["id"]] = sp.get("trial_ends_at") or iso(now)
        removed.append({"space_id": sid, "simulator": sim["id"]})
    return removed


def card_state(sim: dict, space: dict | None, covered_tier: str | None, ended: dict,
               now: datetime | None = None) -> dict:
    """What the Marketplace shows for one simulator (NO countdown: that is Spaces-only)."""
    eff = effective(space, covered_tier, now)
    trial_ended = sim["id"] in ended and not covered_tier
    return {
        "id": sim["id"], "name": sim["name"], "free_tier": bool(sim.get("free_tier", True)),
        "added": space is not None, "space_id": (space or {}).get("space_id"),
        "tier": eff["tier"], "licensed": bool(covered_tier), "enabled_tier": covered_tier or "",
        "offers": offers_for(sim["id"], covered_tier),
        "trial_ended": trial_ended,
        # a no-free-tier simulator is only addable under a licence or before its single trial
        "can_add": bool(space) or bool(covered_tier) or (not trial_ended),
    }
