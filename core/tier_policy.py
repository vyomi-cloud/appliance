"""Tier policy — single source of truth for what each license tier unlocks.

CloudLearn licensing model (locked in 2026-06-01):

    free       — build ONE complete e2e app per cloud, all 3 providers visible
                 (10 services per provider: compute + serverless + storage + DB
                 + API GW + IAM + VPC + secrets + KMS + queue). Locked: NoSQL
                 + eventing. Tight quantity caps (1 of each resource per space).
                 ₹0/mo forever.

    student    — pick ONE primary cloud at signup, get all 12 services on it.
                 Other 2 clouds visible but locked. 5 spaces · medium VM size
                 · 10 GB storage · Cloud Shell · CloudSim Power model. ₹299/mo
                 or ₹2099/yr.

    developer  — all 35 services × all 3 clouds. 25 spaces · large VM size ·
                 100 GB storage · Cedar IAM enforcement · full CloudSim · cost
                 simulation · CI integration. ₹599/mo or ₹5099/yr.

    enterprise — everything in developer + multi-tenant · SSO · audit-log
                 sinks · Helm + air-gapped · custom domain · 24/7 support.
                 ₹99/dev/mo, 10-dev minimum (= ₹990/mo).

The reference apps (tests/e2e/java-orders + go-inventory) both fit ENTIRELY
within the Free tier — that's intentional. Free user can run our reference
apps as their first hands-on; building app #2 forces the Student upgrade.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Service category buckets — each provider's catalog services map to one.
# Used by the Free + Student tiers to allow/deny by category, not by per-
# service key (so adding a new EC2-like service later doesn't need a tier
# policy update).
# ---------------------------------------------------------------------------
SERVICE_CATEGORY = {
    # AWS
    "ec2":             "compute",
    "lambda":          "serverless",
    "s3":              "object_storage",
    "rds":             "relational_db",
    "apigateway":      "api_gateway",
    "iam":             "iam",
    "vpc":             "network",
    "secretsmanager":  "secrets",
    "kms":             "kms",
    "sqs":             "queue",
    "dynamodb":        "nosql",
    "eventbridge":     "eventing",
    # GCP
    "compute":         "compute",
    "functions":       "serverless",
    "storage":         "object_storage",
    "cloudsql":        "relational_db",
    # gcp.apigateway → "api_gateway" (already covered by "apigateway")
    # gcp.iam → "iam" (already covered)
    # gcp.vpc → "network" (already covered)
    "secretmanager":   "secrets",
    # gcp kms → "kms" (already covered)
    "pubsub":          "queue",
    "firestore":       "nosql",
    "eventarc":        "eventing",
    # Azure
    "vm":              "compute",
    "functionapp":     "serverless",
    # azure.storage → "object_storage" (already covered)
    "sql":             "relational_db",
    "apim":            "api_gateway",
    "rbac":            "iam",
    "vnet":            "network",
    "keyvault":        "secrets",  # also acts as KMS — Free unlocks both buckets together
    "servicebus":      "queue",
    "cosmos":          "nosql",
    "eventgrid":       "eventing",
}

# Categories the FREE tier unlocks (everything else → locked behind paid tiers).
FREE_UNLOCKED_CATEGORIES = {
    "compute", "serverless", "object_storage", "relational_db",
    "api_gateway", "iam", "network", "secrets", "kms", "queue",
}
FREE_LOCKED_CATEGORIES = {"nosql", "eventing"}


# ---------------------------------------------------------------------------
# Tier policy table — single source of truth.
# ---------------------------------------------------------------------------
# Sentinel for unlimited counts.
UNLIMITED = -1

# Per-tenant rate-limit (requests/second sustained). Token bucket = burst is
# 4× steady. UNLIMITED here = no throttle. Used by the rate-limit middleware
# in server.py. Tuned so Free can run a single boto3 script without hitting
# the limit, while Enterprise gets effectively no ceiling.
RATE_LIMITS_RPS: dict[str, int] = {
    "free":       10,
    "student":    50,
    "developer":  200,
    "enterprise": UNLIMITED,
}


def rate_limit_rps(tier: str) -> int:
    """Return per-tenant requests/second cap. UNLIMITED → no throttle."""
    return RATE_LIMITS_RPS.get(normalize_tier(tier), 10)


def _free_quantities() -> dict[str, int]:
    """Per-space limits for Free — tight. java-orders + go-inventory fit."""
    return {
        "vm":              1,
        "database":        1,
        "api_gateway":     1,
        "bucket":          1,
        "queue":           1,
        "lambda_function": 3,
        "secret":          5,
        "kms_key":         2,
        "iam_user":        5,
    }


def _student_quantities() -> dict[str, int]:
    return {
        "vm":              10,
        "database":        5,
        "api_gateway":     5,
        "bucket":          5,
        "queue":           5,
        "lambda_function": 25,
        "secret":          50,
        "kms_key":         10,
        "iam_user":        50,
    }


def _developer_quantities() -> dict[str, int]:
    return {
        "vm":              50,
        "database":        UNLIMITED,
        "api_gateway":     UNLIMITED,
        "bucket":          UNLIMITED,
        "queue":           UNLIMITED,
        "lambda_function": UNLIMITED,
        "secret":          UNLIMITED,
        "kms_key":         UNLIMITED,
        "iam_user":        UNLIMITED,
    }


def _enterprise_quantities() -> dict[str, int]:
    return {k: UNLIMITED for k in _free_quantities().keys()}


# Master tier policy. Each tier's value is fully self-contained — callers should
# go through ``policy_for(tier)`` rather than reading this dict directly.
_TIER_POLICY: dict[str, dict[str, Any]] = {
    "free": {
        "label":                       "Free",
        "headline":                    "Build & run one complete cloud app, free forever",
        "price_inr_monthly":           0,
        "price_inr_annual":            0,
        "max_seats":                   1,
        "min_seats":                   1,
        "max_tenants":                 1,
        "max_spaces":                  1,
        "primary_cloud_required":      False,
        "providers":                   ["aws", "gcp", "azure"],  # all 3 visible
        "service_categories_unlocked": sorted(FREE_UNLOCKED_CATEGORIES),
        "service_categories_locked":   sorted(FREE_LOCKED_CATEGORIES),
        "per_space_quantities":        _free_quantities(),
        "max_vm_size_tier":            "small",   # from core.runtime_sizer._TIERS
        "max_db_size_tier":            "small",
        "storage_bytes_cap":           1 * 1024 ** 3,    # 1 GB
        "activity_log_retention_hours": 24,
        "features": {
            # DevEx surface for /pricing. cloud_sdks + provider_clis are the
            # same platform promise across all tiers (rendered as a banner
            # ABOVE the cards, not per-tier). Tier escalation = api scope +
            # console access + tier_support.
            "cloud_sdks":      "Native (override endpoint)",
            "provider_clis":   "Native (override endpoint)",
            "api_access":      "10 categories × 3 clouds",
            "workload_scale":  "Hello-world apps · 1 cloud at a time",
            "cloud_consoles":  "3 consoles · locked services read-only",
            "tier_support":    "Community · GitHub",
            # Original feature gates
            "cloud_shell":                  False,
            "cedar_enforcement":            False,
            "cloudsim_power":               False,
            "cloudsim_network_sla_migration": False,
            "cost_simulation":              False,
            "terraform_export":             "basic",
            "terraform_deploy_to_real":     False,
            "audit_export_sinks":           False,
            "sso":                          False,
            "cross_tenant_rbac":            False,
            "helm":                         False,
            "custom_domain":                False,
            "branding":                     False,
            "notifications":                False,
            "ci_integration":               False,
            "scaffolding_generator":        False,
        },
        "support":        "community",
        "update_channel": "quarterly",
    },
    "student": {
        "label":                       "Student",
        "headline":                    "All services on one cloud, build many apps",
        "price_inr_monthly":           299,
        "price_inr_annual":            2099,
        "max_seats":                   1,
        "min_seats":                   1,
        "max_tenants":                 1,
        "max_spaces":                  5,
        "primary_cloud_required":      True,   # picked at signup
        "providers":                   "primary_cloud_only",
        "service_categories_unlocked": "ALL",  # all categories — but only on primary cloud
        "service_categories_locked":   [],
        "per_space_quantities":        _student_quantities(),
        "max_vm_size_tier":            "medium",
        "max_db_size_tier":            "medium",
        "storage_bytes_cap":           10 * 1024 ** 3,
        "activity_log_retention_hours": 7 * 24,
        "features": {
            # Developer-experience surface.
            "cloud_sdks":      "Native (override endpoint)",
            "provider_clis":   "Native (override endpoint)",
            "api_access":      "All services · primary cloud only",
            "workload_scale":  "Full app on your primary cloud",
            "cloud_consoles":  "1 primary unlocked · 2 read-only",
            "tier_support":    "Discord + GitHub",
            # Original feature gates
            "cloud_shell":                  True,
            "cedar_enforcement":            False,
            "cloudsim_power":               True,
            "cloudsim_network_sla_migration": False,
            "cost_simulation":              "totals",
            "terraform_export":             "full",
            "terraform_deploy_to_real":     False,
            "audit_export_sinks":           False,
            "sso":                          False,
            "cross_tenant_rbac":            False,
            "helm":                         False,
            "custom_domain":                False,
            "branding":                     False,
            "notifications":                False,
            "ci_integration":               False,
            "scaffolding_generator":        False,
        },
        "support":        "community + monthly office hours",
        "update_channel": "monthly",
    },
    "developer": {
        "label":                       "Developer",
        "headline":                    "All clouds + advanced features + CI",
        "price_inr_monthly":           599,
        "price_inr_annual":            5099,
        "max_seats":                   1,
        "min_seats":                   1,
        "max_tenants":                 1,
        "max_spaces":                  25,
        "primary_cloud_required":      False,
        "providers":                   ["aws", "gcp", "azure"],
        "service_categories_unlocked": "ALL",
        "service_categories_locked":   [],
        "per_space_quantities":        _developer_quantities(),
        "max_vm_size_tier":            "large",
        "max_db_size_tier":            "large",
        "storage_bytes_cap":           100 * 1024 ** 3,
        "activity_log_retention_hours": 30 * 24,
        "features": {
            # Developer-experience surface.
            "cloud_sdks":      "Native (override endpoint)",
            "provider_clis":   "Native (override endpoint)",
            "api_access":      "All 35 services × 3 clouds",
            "workload_scale":  "Multi-cloud apps · CI workloads",
            "cloud_consoles":  "3 fully unlocked",
            "tier_support":    "Email · 48 h response",
            # Original feature gates
            "cloud_shell":                  True,
            "cedar_enforcement":            True,
            "cloudsim_power":               True,
            "cloudsim_network_sla_migration": True,
            "cost_simulation":              "per_resource",
            "terraform_export":             "full",
            "terraform_deploy_to_real":     "single_cloud",
            "audit_export_sinks":           False,
            "sso":                          False,
            "cross_tenant_rbac":            False,
            "helm":                         False,
            "custom_domain":                False,
            "branding":                     False,
            "notifications":                "webhook",
            "ci_integration":               True,
            "scaffolding_generator":        True,
        },
        "support":        "business-hours email (24h SLA)",
        "update_channel": "weekly + preview channel",
    },
    "enterprise": {
        "label":                       "Enterprise",
        "headline":                    "Team + on-prem + SSO + 24/7 support",
        "price_inr_monthly_per_seat":  99,
        "price_inr_monthly":           99 * 10,  # for display: 10-seat minimum × per-seat rate
        "price_inr_annual":            None,     # custom contract
        "max_seats":                   UNLIMITED,
        "min_seats":                   10,
        "max_tenants":                 UNLIMITED,
        "max_spaces":                  UNLIMITED,
        "primary_cloud_required":      False,
        "providers":                   ["aws", "gcp", "azure"],
        "service_categories_unlocked": "ALL",
        "service_categories_locked":   [],
        "per_space_quantities":        _enterprise_quantities(),
        "max_vm_size_tier":            "huge",
        "max_db_size_tier":            "huge",
        "storage_bytes_cap":           UNLIMITED,
        "activity_log_retention_hours": 90 * 24,
        "features": {
            # Developer-experience surface.
            "cloud_sdks":      "Native (override endpoint)",
            "provider_clis":   "Native (override endpoint)",
            "api_access":      "+ gRPC + signed audit log",
            "workload_scale":  "Production-scale workloads",
            "cloud_consoles":  "+ custom branding / domain / auth",
            "tier_support":    "Dedicated Slack · SLA",
            # Original feature gates
            "cloud_shell":                  True,
            "cedar_enforcement":            True,
            "cloudsim_power":               True,
            "cloudsim_network_sla_migration": True,
            "cost_simulation":              "per_resource_and_chargeback",
            "terraform_export":             "full_plus_import",
            "terraform_deploy_to_real":     "multi_cloud",
            "audit_export_sinks":           True,
            "sso":                          True,
            "cross_tenant_rbac":            True,
            "helm":                         True,
            "custom_domain":                True,
            "branding":                     True,
            "notifications":                "all_channels",
            "ci_integration":               True,
            "scaffolding_generator":        True,
        },
        "support":        "24/7 + dedicated CSM",
        "update_channel": "LTS branches",
    },
}


# ---------------------------------------------------------------------------
# Legacy tier name migration. Old tier names (still in some signed JWTs):
#   "pro" → "developer"
#   "max" → "developer"  (consolidated; both were "more than free, less than ent")
# ---------------------------------------------------------------------------
_LEGACY_TIER_MAP = {
    "pro":  "developer",
    "max":  "developer",
    "dev":  "developer",
    "edu":  "student",
    "ent":  "enterprise",
}

KNOWN_TIERS = ("free", "student", "developer", "enterprise")


def normalize_tier(tier: str | None) -> str:
    """Map any legacy/aliased tier name to the canonical one. Unknown → free."""
    if not tier:
        return "free"
    t = str(tier).strip().lower()
    t = _LEGACY_TIER_MAP.get(t, t)
    return t if t in KNOWN_TIERS else "free"


# ---------------------------------------------------------------------------
# Lookup API — callers should use these, NOT _TIER_POLICY directly.
# ---------------------------------------------------------------------------
def policy_for(tier: str | None) -> dict[str, Any]:
    """Return the full policy dict for a tier. Always returns something (Free
    is the safe fallback for unknown tiers)."""
    import copy
    return copy.deepcopy(_TIER_POLICY[normalize_tier(tier)])


def all_tiers() -> dict[str, dict[str, Any]]:
    """For the SPA pricing page / /api/runtime/tier endpoint."""
    import copy
    return {k: copy.deepcopy(v) for k, v in _TIER_POLICY.items()}


# ---------------------------------------------------------------------------
# Capability checks. These are the ONLY functions enforcement code should call.
# Each returns either {"ok": True} OR {"ok": False, "reason": str, "upgrade_to":
# str, "code": str} — the structured 403 body the SPA shows in upgrade modals.
# ---------------------------------------------------------------------------
def check_service(tier: str, service_key: str,
                  primary_cloud: str | None = None,
                  request_cloud: str | None = None) -> dict[str, Any]:
    """Is this service unlocked for this tier?

    service_key — one of the keys in SERVICE_CATEGORY (e.g. "ec2", "rds",
                  "dynamodb"). Unknown service keys default to ALLOWED — we
                  don't want to break new services we haven't categorized.
    primary_cloud — for Student tier, the cloud they picked at signup.
    request_cloud — which provider the current request is hitting.
    """
    p = policy_for(tier)
    tier_norm = normalize_tier(tier)

    # Provider gate — Student is locked to one cloud.
    providers = p.get("providers", [])
    if providers == "primary_cloud_only":
        if request_cloud and primary_cloud and request_cloud != primary_cloud:
            return {
                "ok": False, "code": "tier_provider_locked",
                "reason": f"Student tier is locked to {primary_cloud}; switch primary cloud or upgrade to Developer",
                "upgrade_to": "developer",
            }
    elif isinstance(providers, list) and request_cloud and request_cloud not in providers:
        return {
            "ok": False, "code": "tier_provider_locked",
            "reason": f"{request_cloud} not available on {tier_norm} tier",
            "upgrade_to": "student" if tier_norm == "free" else "developer",
        }

    # Service category gate.
    unlocked = p.get("service_categories_unlocked", [])
    if unlocked == "ALL":
        return {"ok": True}
    category = SERVICE_CATEGORY.get(service_key)
    if category is None:
        # Unknown service — let it through; safer than blocking by accident.
        return {"ok": True}
    if category not in unlocked:
        return {
            "ok": False, "code": "tier_service_locked",
            "reason": f"{service_key} ({category}) requires {'Developer' if category in {'nosql', 'eventing'} else 'Student'} tier or higher",
            "upgrade_to": "developer" if category in {"nosql", "eventing"} else "student",
            "service": service_key, "category": category,
        }
    return {"ok": True}


def check_quantity(tier: str, resource_type: str, current_count: int) -> dict[str, Any]:
    """Would creating one more of this resource exceed the tier cap?"""
    p = policy_for(tier)
    caps = p.get("per_space_quantities") or {}
    cap = caps.get(resource_type)
    if cap is None or cap == UNLIMITED:
        return {"ok": True}
    if current_count + 1 > cap:
        return {
            "ok": False, "code": "tier_quantity_limit",
            "reason": f"{tier} tier allows max {cap} {resource_type}(s) per space; you have {current_count}",
            "upgrade_to": _next_tier(normalize_tier(tier)),
            "resource_type": resource_type, "limit": cap, "current": current_count,
        }
    return {"ok": True}


def check_storage(tier: str, current_bytes: int, additional_bytes: int) -> dict[str, Any]:
    """Would adding additional_bytes exceed the storage cap?"""
    p = policy_for(tier)
    cap = p.get("storage_bytes_cap")
    if cap is None or cap == UNLIMITED:
        return {"ok": True}
    if current_bytes + additional_bytes > cap:
        return {
            "ok": False, "code": "tier_storage_limit",
            "reason": f"{tier} tier allows {cap // (1024 ** 3)} GB total storage; you have {current_bytes // (1024 ** 2)} MB",
            "upgrade_to": _next_tier(normalize_tier(tier)),
            "limit_bytes": cap, "current_bytes": current_bytes,
        }
    return {"ok": True}


def check_feature(tier: str, feature_name: str) -> dict[str, Any]:
    """Is this feature available for this tier? feature_name is one of the
    keys in the policy's ``features`` dict (e.g. ``cloud_shell``,
    ``cedar_enforcement``, ``sso``)."""
    p = policy_for(tier)
    val = (p.get("features") or {}).get(feature_name)
    if val:
        return {"ok": True, "value": val}
    return {
        "ok": False, "code": "tier_feature_locked",
        "reason": f"{feature_name} requires a higher tier",
        "upgrade_to": _next_tier(normalize_tier(tier)),
        "feature": feature_name,
    }


def check_max_spaces(tier: str, current_spaces: int) -> dict[str, Any]:
    p = policy_for(tier)
    cap = p.get("max_spaces")
    if cap == UNLIMITED:
        return {"ok": True}
    if current_spaces + 1 > cap:
        return {
            "ok": False, "code": "tier_max_spaces",
            "reason": f"{tier} tier allows {cap} space(s); you have {current_spaces}",
            "upgrade_to": _next_tier(normalize_tier(tier)),
            "limit": cap, "current": current_spaces,
        }
    return {"ok": True}


def _next_tier(tier: str) -> str:
    order = ["free", "student", "developer", "enterprise"]
    try:
        i = order.index(tier)
        return order[min(i + 1, len(order) - 1)]
    except ValueError:
        return "student"
