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

AWS_ELBV2_HOURLY: dict[str, float] = {   # us-east-1 on-demand, per load balancer-hour (excl. LCUs)
    "application": 0.0225, "network": 0.0225, "gateway": 0.0125,
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
    "aws.stepfunctions": 2.50, # Standard workflow: $0.025/1K state transitions (~100K/month)
    "aws.vpc": 0.00,          # free (NAT GW extra)
    "aws.logs": 2.53,         # CloudWatch Logs: ~5GB ingested ($0.50/GB) + ~1GB stored ($0.03/GB)
    "aws.secretsmanager": 0.40,  # $0.40 per secret per month
    "aws.kms": 1.00,             # $1.00 per customer-managed key per month
    "aws.eventbridge": 0.00,     # rules / custom buses are free; events billed per use
    "aws.ssm": 0.05,          # Parameter Store advanced-tier parameter $0.05/mo (standard tier is free)
    # GCP
    "gcp.sql": 25.00,         # db-f1-micro 730h
    "gcp.functions": 0.20,    # minimal invocations
    "gcp.storage": 0.50,      # ~20GB
    "gcp.pubsub": 0.40,       # ~1M messages
    "gcp.firestore": 0.18,    # 1GB stored
    "gcp.apigateway": 3.00,   # ~1M calls
    "gcp.vpc": 0.00,
    "gcp.iam": 0.00,
    "gcp.redis": 35.77,         # Basic tier $0.049/GB-hr × 1 GB × ~730 h (Standard doubles it)
    "gcp.container": 73.00,     # $0.10/hr cluster management fee (~730 h); one zonal/Autopilot cluster per account is free
    "gcp.iamcredentials": 0.03,  # per issued credential: the API itself is free; priced at the Cloud KMS software-key signing rate (~$0.03 per 10k ops) it replaces
    "gcp.cloudscheduler": 0.10, # $0.10 per job per month (first 3 jobs per billing account free)
    "gcp.secretmanager": 0.06,  # $0.06 per active secret version per month
    "gcp.kms": 0.06,            # $0.06 per software key version per month
    "gcp.eventarc": 0.04,       # triggers are free; events $0.40 per million delivered (modelled at ~100K events/month)
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
    "azure.appconfiguration": 36.50,  # Standard tier: $1.20 per store per day (~30.4 days/month); requests included to 200K/day
    "azure.cognitiveservices": 1.00,  # S0 pay-as-you-go: ~1K transactions/month (~$1 per 1K text records / transactions); F0 is free
    "azure.operationalinsights": 2.76,  # Log Analytics PerGB2018: $2.76/GB ingested beyond the 5 GB/month free allowance; modelled at ~1 GB/month
    "azure.dns": 0.50,        # Azure DNS: $0.50 per hosted zone per month (first 25 zones; $0.10 beyond) + $0.40 per million queries
    "azure.monitor": 0.10,    # metric alert rule: $0.10 per monitored time series per month (static threshold, 1 resource); action groups: first 1,000 emails/month free
    "azure.app": 39.42,       # Container Apps Consumption: one always-on 0.5 vCPU / 1 GiB replica (~$0.000024/vCPU-s + $0.000003/GiB-s, ~2.63M s/month)
}

# ── Usage-based storage pricing (public list prices, USD) ────────────
# Real clouds bill object storage by GB-month stored plus per-request fees, so
# data written to a bucket / storage account raises the savings, not just its
# existence. Per key: (USD per GB-month, USD per 1,000 write requests).
#   aws.s3         S3 Standard, us-east-1: $0.023/GB-mo, PUT/COPY/POST/LIST $0.005 per 1,000
#   gcp.storage    Cloud Storage Standard, us-central1: $0.020/GB-mo, Class A ops $0.005 per 1,000
#   azure.storage  Blob Hot LRS, East US: $0.0184/GB-mo, write ops $0.055 per 10,000
STORAGE_USAGE_RATES: dict[str, tuple[float, float]] = {
    "aws.s3": (0.023, 0.005),
    "gcp.storage": (0.020, 0.005),
    "azure.storage": (0.0184, 0.0055),
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
    # Azure ARM nodes carry the lower-cased ARM type as their kind ("virtualmachines").
    if kind in ("instance", "vm", "virtualmachines") and service in ("ec2", "compute", "vm", "gcp_compute"):
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

    # ELBv2 load balancers — per-hour pricing by load balancer type
    if provider == "aws" and service == "elbv2":
        rate = AWS_ELBV2_HOURLY.get(instance_type, 0.0225)
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
                           uptime_hours: float = HOURS_PER_MONTH,
                           usage: dict | None = None) -> dict:
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
        rates = STORAGE_USAGE_RATES.get(f"{provider}.{service}")
        if rates and (node.get("stored_bytes") or node.get("write_requests")):
            gb = float(node.get("stored_bytes") or 0) / (1024 ** 3)
            usd += (gb * rates[0] * (uptime_hours / HOURS_PER_MONTH)
                    + float(node.get("write_requests") or 0) / 1000.0 * rates[1])
        total += usd

        by_provider[provider] = round(by_provider.get(provider, 0.0) + usd, 6)
        svc_key = f"{provider}.{service}"
        by_service[svc_key] = round(by_service.get(svc_key, 0.0) + usd, 6)

        per_resource.append({
            "resource_id": node.get("resource_id", ""),
            "provider": provider,
            "service": service,
            "kind": kind,
            "name": node.get("name", ""),
            "instance_type": itype,
            "real_cloud_cost_usd": round(usd, 6),
            "monthly_rate_usd": cost["monthly_usd"],
            "hourly_rate_usd": cost["hourly_usd"],
        })

    # Usage-based billing: bytes stored + write requests metered per provider.
    if usage:
        from core.usage_meter import usage_cost
        for provider, u in usage.items():
            usd = usage_cost(provider, u)
            total += usd
            by_provider[provider] = by_provider.get(provider, 0.0) + usd
            by_service[f"{provider}.usage"] = by_service.get(f"{provider}.usage", 0.0) + usd
    by_provider = {k: round(v, 4) for k, v in by_provider.items()}
    by_service = {k: round(v, 4) for k, v in by_service.items()}

    return {
        "real_cloud_cost_usd": round(total, 6),
        "simulator_cost_usd": 0.0,
        "savings_usd": round(total, 6),
        "savings_pct": 100.0 if total > 0 else 0.0,
        "uptime_hours": uptime_hours,
        "resource_count": len(nodes),
        "by_provider": by_provider,
        "by_service": by_service,
        "per_resource_costs": per_resource,
    }
