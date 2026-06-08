"""Real cloud cost estimation — what users would have paid on actual AWS/GCP/Azure.

Pricing tables use on-demand hourly rates (USD) for instance types defined in
core/instance_catalog.py, plus per-service flat monthly rates for managed services.

The savings model: real_cloud_cost > 0, simulator_cost = $0 (runs on localhost).
Savings = 100% of real cloud cost avoided.
"""
from __future__ import annotations

# ── VM Pricing (USD/hour, on-demand) ─────────────────────────────────
# Sources: AWS us-east-1, GCP us-central1, Azure East US (as of 2024-Q4)

AWS_VM_HOURLY: dict[str, float] = {
    "t3.nano": 0.0052, "t3.micro": 0.0104, "t3.small": 0.0208,
    "t3.medium": 0.0416, "t3.large": 0.0832, "t3.xlarge": 0.1664,
    "t3.2xlarge": 0.3328,
    "m5.large": 0.096, "m5.xlarge": 0.192, "m5.2xlarge": 0.384,
    "m5.4xlarge": 0.768, "m5.8xlarge": 1.536,
    "m6i.large": 0.096, "m6i.xlarge": 0.192, "m6i.2xlarge": 0.384,
    "c5.large": 0.085, "c5.xlarge": 0.17, "c5.2xlarge": 0.34,
    "c5.4xlarge": 0.68,
    "c6i.large": 0.085, "c6i.xlarge": 0.17, "c6i.2xlarge": 0.34,
    "r5.large": 0.126, "r5.xlarge": 0.252, "r5.2xlarge": 0.504,
    "r5.4xlarge": 1.008,
    "i3.large": 0.156, "i3.xlarge": 0.312, "i4i.large": 0.149,
    "p3.2xlarge": 3.06, "g5.xlarge": 1.006,
}

AWS_RDS_HOURLY: dict[str, float] = {
    "db.t3.micro": 0.017, "db.t3.small": 0.034, "db.t3.medium": 0.068,
    "db.t3.large": 0.136, "db.t3.xlarge": 0.272, "db.t3.2xlarge": 0.544,
    "db.m5.large": 0.171, "db.m5.xlarge": 0.342, "db.m5.2xlarge": 0.684,
    "db.r5.large": 0.24, "db.r5.xlarge": 0.48, "db.r5.2xlarge": 0.96,
}

GCP_VM_HOURLY: dict[str, float] = {
    "e2-micro": 0.0084, "e2-small": 0.0168, "e2-medium": 0.0336,
    "e2-standard-2": 0.067, "e2-standard-4": 0.134, "e2-standard-8": 0.268,
    "n2-standard-2": 0.0971, "n2-standard-4": 0.1942,
    "n2-standard-8": 0.3884, "n2-standard-16": 0.7769,
    "n2-standard-32": 1.5537,
    "c2-standard-4": 0.2088, "c2-standard-8": 0.4176,
    "c2-standard-16": 0.8352, "c2-standard-30": 1.566,
    "n2-highmem-2": 0.1311, "n2-highmem-4": 0.2622, "n2-highmem-8": 0.5244,
    "a2-highgpu-1g": 3.6732,
}

GCP_SQL_HOURLY: dict[str, float] = {
    "db-f1-micro": 0.0105, "db-g1-small": 0.0255,
    "db-n1-standard-1": 0.0500, "db-n1-standard-2": 0.1000,
    "db-n1-standard-4": 0.2000, "db-n1-standard-8": 0.4000,
    "db-n1-highmem-2": 0.1250, "db-n1-highmem-4": 0.2500,
}

AZURE_VM_HOURLY: dict[str, float] = {
    "Standard_B1s": 0.0104, "Standard_B1ms": 0.0207,
    "Standard_B2s": 0.0416, "Standard_B2ms": 0.0832,
    "Standard_B4ms": 0.166, "Standard_B8ms": 0.333,
    "Standard_D2s_v5": 0.096, "Standard_D4s_v5": 0.192,
    "Standard_D8s_v5": 0.384, "Standard_D16s_v5": 0.768,
    "Standard_D32s_v5": 1.536,
    "Standard_F2s_v2": 0.0846, "Standard_F4s_v2": 0.169,
    "Standard_F8s_v2": 0.338, "Standard_F16s_v2": 0.677,
    "Standard_E2s_v5": 0.126, "Standard_E4s_v5": 0.252,
    "Standard_E8s_v5": 0.504, "Standard_E16s_v5": 1.008,
    "Standard_NC6": 0.90, "Standard_NC12": 1.80,
}

# ── Managed-Service Pricing (USD/month per resource instance) ────────
# Conservative estimates for minimal-usage baseline

SERVICE_MONTHLY: dict[str, float] = {
    # AWS
    "aws.rds": 25.55,         # db.t3.micro on-demand 730h
    "aws.lambda": 0.20,       # minimal invocations
    "aws.s3": 0.50,           # ~20GB storage
    "aws.sqs": 0.40,          # ~1M requests
    "aws.dynamodb": 1.25,     # on-demand, light usage
    "aws.apigateway": 3.50,   # ~1M calls
    "aws.vpc": 0.00,          # free (NAT GW extra)
    # GCP
    "gcp.sql": 25.00,         # db-f1-micro 730h
    "gcp.functions": 0.20,    # minimal invocations
    "gcp.storage": 0.50,      # ~20GB
    "gcp.pubsub": 0.40,       # ~1M messages
    "gcp.firestore": 0.18,    # 1GB stored
    "gcp.apigateway": 3.00,   # ~1M calls
    "gcp.vpc": 0.00,
    "gcp.iam": 0.00,
    # Azure
    "azure.vm": 0.00,         # priced via VM hourly
    "azure.sql": 4.99,        # Basic DTU
    "azure.storage": 0.50,    # ~20GB LRS
    "azure.functionapp": 0.20,# minimal
    "azure.servicebus": 9.81, # Basic namespace
    "azure.cosmos": 24.48,    # 400 RU/s
    "azure.apim": 48.42,      # Developer tier
    "azure.vnet": 0.00,
    "azure.eventgrid": 0.60,  # ~1M events
    "azure.keyvault": 0.03,   # per 10K ops
    "azure.rbac": 0.00,
}

# Fallback hourly rates by provider for unknown instance types
_DEFAULT_VM_HOURLY = {"aws": 0.0416, "gcp": 0.0336, "azure": 0.0416}

HOURS_PER_MONTH = 730.0


def vm_hourly_rate(provider: str, instance_type: str) -> float:
    """Look up the on-demand hourly rate for a VM instance type."""
    tables = {"aws": AWS_VM_HOURLY, "gcp": GCP_VM_HOURLY, "azure": AZURE_VM_HOURLY}
    rate = tables.get(provider, {}).get(instance_type)
    if rate is not None:
        return rate
    return _DEFAULT_VM_HOURLY.get(provider, 0.0416)


def db_hourly_rate(provider: str, instance_class: str) -> float:
    """Look up the on-demand hourly rate for a database instance."""
    if provider == "aws":
        rate = AWS_RDS_HOURLY.get(instance_class)
        if rate is not None:
            return rate
        return 0.017  # db.t3.micro fallback
    if provider == "gcp":
        rate = GCP_SQL_HOURLY.get(instance_class)
        if rate is not None:
            return rate
        return 0.0105  # db-f1-micro fallback
    return 0.007  # Azure Basic DTU equivalent


def estimate_resource_cost(provider: str, service: str, kind: str,
                           instance_type: str = "",
                           uptime_hours: float = HOURS_PER_MONTH) -> dict:
    """Estimate what a single resource would cost on real cloud infrastructure.

    Returns:
        {hourly_usd, monthly_usd, uptime_cost_usd, uptime_hours, source}
    """
    # VM instances — use hourly pricing tables
    if kind in ("instance", "vm") and service in ("ec2", "compute", "vm", "gcp_compute"):
        rate = vm_hourly_rate(provider, instance_type)
        return {
            "hourly_usd": round(rate, 4),
            "monthly_usd": round(rate * HOURS_PER_MONTH, 2),
            "uptime_cost_usd": round(rate * uptime_hours, 2),
            "uptime_hours": uptime_hours,
            "source": "on-demand",
        }

    # Database instances — use DB hourly pricing
    if kind in ("db_instance", "database") and service in ("rds", "sql", "gcp_sql", "cloudsql"):
        rate = db_hourly_rate(provider, instance_type)
        return {
            "hourly_usd": round(rate, 4),
            "monthly_usd": round(rate * HOURS_PER_MONTH, 2),
            "uptime_cost_usd": round(rate * uptime_hours, 2),
            "uptime_hours": uptime_hours,
            "source": "on-demand",
        }

    # Managed services — flat monthly rate
    key = f"{provider}.{service}"
    monthly = SERVICE_MONTHLY.get(key, 0.0)
    hourly = monthly / HOURS_PER_MONTH if monthly > 0 else 0.0
    return {
        "hourly_usd": round(hourly, 6),
        "monthly_usd": round(monthly, 2),
        "uptime_cost_usd": round(monthly * (uptime_hours / HOURS_PER_MONTH), 2),
        "uptime_hours": uptime_hours,
        "source": "flat-rate",
    }


def estimate_space_savings(nodes: list[dict],
                           uptime_hours: float = HOURS_PER_MONTH) -> dict:
    """Given resource nodes from _cloudsim_collect_resources, compute total
    real-cloud cost and savings (simulator cost = $0).

    Returns:
        {real_cloud_cost_usd, simulator_cost_usd, savings_usd, savings_pct,
         uptime_hours, resource_count, by_provider, by_service, per_resource_costs}
    """
    total = 0.0
    by_provider: dict[str, float] = {}
    by_service: dict[str, float] = {}
    per_resource: list[dict] = []

    for node in nodes:
        provider = node.get("provider", "aws")
        service = node.get("service", "")
        kind = node.get("kind", "")
        itype = (node.get("instance_type") or node.get("machine_type")
                 or node.get("db_instance_class") or "")

        cost = estimate_resource_cost(provider, service, kind, itype, uptime_hours)
        usd = cost["uptime_cost_usd"]
        total += usd

        by_provider[provider] = round(by_provider.get(provider, 0.0) + usd, 2)
        svc_key = f"{provider}.{service}"
        by_service[svc_key] = round(by_service.get(svc_key, 0.0) + usd, 2)

        per_resource.append({
            "resource_id": node.get("resource_id", ""),
            "provider": provider,
            "service": service,
            "kind": kind,
            "name": node.get("name", ""),
            "instance_type": itype,
            "real_cloud_cost_usd": round(usd, 2),
            "monthly_rate_usd": cost["monthly_usd"],
            "hourly_rate_usd": cost["hourly_usd"],
        })

    return {
        "real_cloud_cost_usd": round(total, 2),
        "simulator_cost_usd": 0.0,
        "savings_usd": round(total, 2),
        "savings_pct": 100.0 if total > 0 else 0.0,
        "uptime_hours": uptime_hours,
        "resource_count": len(nodes),
        "by_provider": by_provider,
        "by_service": by_service,
        "per_resource_costs": per_resource,
    }
