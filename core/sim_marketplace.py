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
# `services` = what the Full Cloud stack contains (the console's service list). Keep in step with the consoles.
SIMULATORS: list[dict[str, Any]] = [
    {"id": "aws",   "name": "AWS",          "free_tier": True, "price_usd": 21, "services": [
        "EC2", "Lambda", "S3", "RDS", "DynamoDB", "SQS", "SNS", "API Gateway", "API Gateway V2", "EventBridge",
        "Step Functions", "Kinesis", "VPC", "Elastic Load Balancing", "IAM", "Secrets Manager", "KMS",
        "CloudWatch Logs", "Systems Manager", "CloudWatch"]},
    {"id": "gcp",   "name": "Google Cloud", "free_tier": True, "price_usd": 21, "services": [
        "Compute Engine", "Cloud Functions", "Kubernetes Engine", "Cloud Storage", "Artifact Registry", "Cloud SQL",
        "Firestore", "Memorystore for Redis", "VPC Network", "Pub/Sub", "API Gateway", "Eventarc", "Cloud Scheduler",
        "Secret Manager", "Cloud KMS", "IAM & Admin", "IAM Service Account Credentials", "Cloud Monitoring"]},
    {"id": "azure", "name": "Azure",        "free_tier": True, "price_usd": 21, "services": [
        "Virtual Machines", "Storage accounts", "SQL servers", "Service Bus", "Cosmos DB", "Function apps", "API Management",
        "Virtual networks", "Network Security Group", "Event Grid topics", "Key vaults", "Container Apps", "App Configuration",
        "DNS zones", "Monitor alerts", "Log Analytics", "Azure AI services", "Role Definition", "Entra ID / RBAC"]},
]

# PRICING LADDER (monthly, USD; the portal owns checkout, pro-rating and billing):
#   Pro  $19  one cloud (switchable every 30 days on the portal)   3-month minimum
#   One simulator (a la carte) $21 (per simulator, set in SIMULATORS[].price_usd)   cancel any month
#   Max  $29  every cloud at once                                   3-month minimum
# Order must hold: Pro < individual < Max. The marketplace never sells Pro/Max itself; it links to the
# portal pricing page. Only the a-la-carte simulator is bought from a card.
PLANS = {
    "pro": {"label": "Pro", "price_usd": 19, "per": "/ month", "min_months": 3, "scope": "One cloud of your choice, switchable every 30 days"},
    "max": {"label": "Max", "price_usd": 29, "per": "/ month", "min_months": 3, "scope": "All clouds, unlimited"},
}
_RANK = {"free": 0, "pro": 1, "max": 2}


def offers_for(sim_id: str, covered_tier: str | None, portal: str = "https://vyomi.cloud") -> list[dict]:
    """The one thing a card can sell: this simulator on its own (month-to-month). Empty when a plan or
    purchase already covers it. Pro/Max are bought on the portal pricing page, never from a card."""
    if covered_tier:
        return []
    sim = get_simulator(sim_id)
    price = (sim or {}).get("price_usd")
    if not price:
        return []
    portal = portal.rstrip("/")
    return [{"kind": "simulator", "price_usd": price, "per": "/ month",
             "url": f"{portal}/checkout?product=simulator&simulator={sim_id}&period=monthly"}]


def licence_summary(tier: str | None, primary: str = "", owned: Iterable[str] = (), portal: str = "https://vyomi.cloud") -> dict:
    """The licence strip at the top of the Marketplace."""
    t = tier if tier in PLANS else "free"
    names = {s["id"]: s["name"] for s in SIMULATORS}
    out = {"tier": t, "primary": primary, "owned": [o for o in owned if o in names],
           "plans": PLANS, "pricing_url": portal.rstrip("/") + "/pricing"}
    if t == "max":
        out["detail"] = "All clouds, unlimited"
    elif t == "pro":
        out["detail"] = "One cloud: " + names.get(primary, primary or "not chosen yet") + " \u00b7 switch it on the portal"
    else:
        out["detail"] = "Free plan"
    return out


# AI STACK add-on (monthly, USD; portal owns checkout): $12 for ONE cloud's AI services (Bedrock / Vertex / Azure OpenAI
# + that cloud's agent/knowledge-base plumbing). No all-clouds card is shown (a licence claim of "all" still enables every cloud). It is an ADD-ON to the simulator (independent of
# Pro/Max, runs on top of any tier) and needs that cloud's simulator in Spaces. No MySQL/RDS dependency of its own.
AI_STACK = {"per_cloud_usd": 12, "all_usd": 19, "per": "/ month"}
AI_INCLUDES = {
    "aws": {"product": "Amazon Bedrock", "includes": [
        "Model invoke and Converse, with streaming", "Foundation-model catalogue (Claude, Titan, Nova, Llama, Mistral formats)",
        "Agents", "Knowledge Bases: ingest from S3, Retrieve, RetrieveAndGenerate", "AgentCore runtimes and gateway (MCP)"]},
    "gcp": {"product": "Google Vertex AI", "includes": [
        "Gemini generateContent, with streaming", "Token counting", "Embeddings (embedContent)", "Predict endpoints"]},
    "azure": {"product": "Azure OpenAI", "includes": [
        "Chat completions and completions", "Embeddings", "Model deployments under Cognitive Services accounts",
        "AI Search: vector and hybrid search, integrated vectorization"]},
}


def _ai_set(ai: Any) -> tuple[bool, set]:
    """licence claim -> (all_clouds, {cloud ids}); accepts "all", ["aws", ...] or {"all": true}."""
    if ai in ("all", True) or (isinstance(ai, dict) and ai.get("all")):
        return True, set()
    if isinstance(ai, (list, tuple, set)):
        return ("all" in ai), {str(x).lower() for x in ai if x and x != "all"}
    return False, set()


def ai_stack_cards(ai: Any, added: Iterable[str] = (), portal: str = "https://vyomi.cloud",
                   sims: Iterable[dict] | None = None) -> list[dict]:
    """AI-stack cards: one per cloud + one 'all clouds'. `ai` = licence claim, `added` = simulator ids in Spaces."""
    portal = portal.rstrip("/")
    all_on, owned = _ai_set(ai)
    added = set(added)
    sims = list(sims if sims is not None else SIMULATORS)
    url = lambda scope: f"{portal}/checkout?product=ai_stack&scope={scope}&period=monthly"
    cards = []
    for sim in sims:
        on = all_on or sim["id"] in owned
        meta = AI_INCLUDES.get(sim["id"], {})
        cards.append({"id": sim["id"], "name": sim["name"], "scope": sim["id"], "enabled": on,
                      "product": meta.get("product", sim["name"] + " AI"), "includes": meta.get("includes", []),
                      "via": "all" if all_on else ("single" if on else ""),
                      "price_usd": AI_STACK["per_cloud_usd"], "per": AI_STACK["per"],
                      "requires_simulator": sim["id"] not in added and not on,
                      "url": "" if on else url(sim["id"])})
    return cards


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


def licensed_tier(sim_id: str, tier: str | None, primary_cloud: str | None = "", owned: Iterable[str] = ()) -> str | None:
    """The paid tier ("pro"/"max"/...) covering this simulator, else None.
    Uses core.tier_policy provider entitlement (Pro = one cloud, Max = all)."""
    from core import tier_policy as tp
    t = tp.normalize_tier(tier)
    if t in _NOT_LICENSED_TIERS:
        return "pro" if sim_id in set(owned) else None   # a simulator bought on its own = Pro on that cloud
    providers = tp.policy_for(t).get("providers")
    if providers == "primary_cloud_only":
        return t if primary_cloud and primary_cloud == sim_id else ("pro" if sim_id in set(owned) else None)
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
        "price_usd": sim.get("price_usd"), "services": list(sim.get("services") or []),
        "trial_ended": trial_ended,
        # a no-free-tier simulator is only addable under a licence or before its single trial
        "can_add": bool(space) or bool(covered_tier) or (not trial_ended),
    }
