"""Shared types of the faithful IAM engine (contract: docs/architecture/v4.0/IAM-ENGINE-CONTRACT.md).

Pure Python, no fastapi / socket / third-party imports: this package is vendored into wasm/core and runs under Pyodide (Nano) and in the
appliance (Mesh) unchanged. Permission IDs are VERBATIM vendor strings; never prefix, rename or case-fold them in stored data."""
from __future__ import annotations

MODES = ("off", "audit", "enforce")
LEVELS = ("resource", "service", "space", "global")          # most specific first


def request(cloud, principal, action, resource="*", context=None, **extra):
    """A normalised authorization request. `principal` is a dict: AWS {"arn","type":"user|role|root|federated","account","tags",
    "session_policy"?,"boundary"?}, GCP {"member":"user:x|serviceAccount:y|group:z","type"}, Azure {"object_id","type","groups":[...]}.
    `action` is the vendor permission ID (s3:GetObject | compute.instances.get | Microsoft.Storage/storageAccounts/read, or a data action).
    `resource` is the vendor resource name (ARN | //service.googleapis.com/projects/... | /subscriptions/.../providers/...).
    `context` carries condition-key values (aws:SourceIp, request tags, time, CEL attributes, Azure @Request/@Resource attributes)."""
    return {"cloud": cloud, "principal": principal, "action": action, "resource": resource, "context": context or {}, **extra}


def decision(allowed, reason, matched=None, **extra):
    """reason: "allow" | "explicit_deny" | "implicit_deny" | "not_applicable" (engine had no opinion). `matched` lists the statements /
    bindings / role assignments that decided it: [{"source": "identity|resource|scp|rcp|boundary|session|allow_policy|deny_policy|pab|
    role_assignment|deny_assignment", "id": "...", "effect": "Allow|Deny", "statement": {...}}]. This is what the effective-access
    view and the audit log show."""
    return {"allowed": bool(allowed), "reason": reason, "matched": matched or [], **extra}
