"""RDS (subnet groups, instances) and Secrets Manager (secrets + current values). Secret values go to variables / tfvars."""
from __future__ import annotations

from core.tf_export import hcl
from core.tf_export.core import Ctx, exporter, tags_of


@exporter(60, "rds")
def export_rds(ctx: Ctx) -> None:
    rds = ctx.c["rds"]
    for g in rds.describe_db_subnet_groups().get("DBSubnetGroups", []):
        if g["DBSubnetGroupName"] == "default":
            continue
        ctx.add("aws_db_subnet_group", g["DBSubnetGroupName"], g["DBSubnetGroupName"],
                {"name": g["DBSubnetGroupName"], "description": g.get("DBSubnetGroupDescription") or None,
                 "subnet_ids": [ctx.ref("aws_subnet", s["SubnetIdentifier"]) for s in g.get("Subnets", [])]}, file="database.tf")
    for d in rds.describe_db_instances().get("DBInstances", []):
        ident = d["DBInstanceIdentifier"]
        tags = tags_of(rds.list_tags_for_resource(ResourceName=d["DBInstanceArn"]).get("TagList")) if d.get("DBInstanceArn") else {}
        pw = ctx.variable(f"db_password_{ident.replace('-', '_')}", "ChangeMe12345",
                          f"Master password for {ident} (not readable from the API; set before applying)")
        attrs = {"identifier": ident, "engine": d.get("Engine"), "engine_version": d.get("EngineVersion"),
                 "instance_class": d.get("DBInstanceClass"), "allocated_storage": d.get("AllocatedStorage"),
                 "storage_type": d.get("StorageType") if d.get("StorageType") not in (None, "gp2") else None,
                 "username": d.get("MasterUsername"), "password": pw, "db_name": d.get("DBName") or None,
                 "multi_az": True if d.get("MultiAZ") else None,
                 "publicly_accessible": True if d.get("PubliclyAccessible") else None,
                 "storage_encrypted": True if d.get("StorageEncrypted") else None,
                 "backup_retention_period": d.get("BackupRetentionPeriod") if d.get("BackupRetentionPeriod") not in (None, 0) else None,
                 "db_subnet_group_name": ctx.ref("aws_db_subnet_group", (d.get("DBSubnetGroup") or {}).get("DBSubnetGroupName", ""), "name")
                 if (d.get("DBSubnetGroup") or {}).get("DBSubnetGroupName") not in (None, "default") else None,
                 "vpc_security_group_ids": [ctx.ref("aws_security_group", s["VpcSecurityGroupId"]) for s in d.get("VpcSecurityGroups", [])
                                           if s.get("VpcSecurityGroupId")] or None,
                 "skip_final_snapshot": True, "tags": tags or None}
        ctx.add("aws_db_instance", ident, ident, attrs, file="database.tf")


@exporter(70, "secretsmanager")
def export_secrets(ctx: Ctx) -> None:
    sm = ctx.c["secretsmanager"]
    secrets = []
    for page in sm.get_paginator("list_secrets").paginate():
        secrets += page.get("SecretList", [])
    for s in secrets:
        name = s["Name"]
        addr = ctx.add("aws_secretsmanager_secret", s["ARN"], name,
                       {"name": name, "description": s.get("Description") or None, "tags": tags_of(s.get("Tags")) or None},
                       file="secrets.tf")
        try:
            val = sm.get_secret_value(SecretId=name)
        except Exception:  # noqa: BLE001 - secret without a current value
            continue
        v = ctx.variable(f"secret_{name.replace('-', '_').replace('/', '_')}", val.get("SecretString", ""),
                         f"Current value of secret {name}")
        ctx.add("aws_secretsmanager_secret_version", s["ARN"], name,
                {"secret_id": hcl.Ref(f"{addr}.id"), "secret_string": v}, file="secrets.tf")
