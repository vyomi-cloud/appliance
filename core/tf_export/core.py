"""Export context + registry for the faithful Terraform exporter.

The exporter reads the simulator through its own AWS API (the same Describe/Get/List calls Terraform's provider makes), so what it
writes is what the provider reads back. References between resources are real references, and the simulator's default objects
(default VPC, default subnets, the implicit main route table, a VPC's default security group) are not exported as managed resources.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from core.tf_export import hcl


@dataclass
class Res:
    type: str
    name: str
    attrs: dict[str, Any]
    blocks: list = field(default_factory=list)
    file: str = "main.tf"
    ident: str = ""


def slug(text: str, fallback: str = "res") -> str:
    t = re.sub(r"[^0-9a-zA-Z_]+", "_", str(text or fallback)).strip("_").lower() or fallback
    return ("r_" + t if t[0].isdigit() else t)[:60]


class Ctx:
    def __init__(self, clients: dict[str, Any], region: str):
        self.c = clients
        self.region = region
        self.resources: list[Res] = []
        self.data: list[tuple[str, str, dict[str, Any]]] = []
        self.variables: dict[str, dict[str, Any]] = {}
        self.tfvars: dict[str, Any] = {}
        self.files_bin: dict[str, bytes] = {}
        self.addr: dict[tuple[str, str], str] = {}
        self.skipped: list[dict[str, str]] = []
        self.interp: dict[str, str] = {}  # generated id -> expression, so ids inside ARNs/strings become references
        self._names: set[tuple[str, str]] = set()

    # -- naming / registration -------------------------------------------------------------------------------------------
    def name_for(self, rtype: str, hint: str) -> str:
        base = slug(hint)
        n, i = base, 1
        while (rtype, n) in self._names:
            i += 1
            n = f"{base}_{i}"
        self._names.add((rtype, n))
        return n

    def reserve(self, rtype: str, ident: str, hint: str) -> str:
        """Give a resource its Terraform address before its attributes are built (lets resources reference each other)."""
        if (rtype, ident) not in self.addr:
            self.addr[(rtype, ident)] = f"{rtype}.{self.name_for(rtype, hint)}"
        return self.addr[(rtype, ident)]

    def add(self, rtype: str, ident: str, hint: str, attrs: dict[str, Any], blocks=(), file: str = "main.tf") -> str:
        addr = self.reserve(rtype, ident, hint)
        self.resources.append(Res(rtype, addr.split(".", 1)[1], attrs, list(blocks), file, ident))
        return addr

    def alias(self, rtype: str, ident: str, address: str) -> None:
        self.addr[(rtype, ident)] = address

    def ref(self, rtype: str, ident: str, attr: str = "id"):
        """A reference to an exported resource, else the literal id (an object the export does not manage)."""
        a = self.addr.get((rtype, ident))
        return hcl.Ref(f"{a}.{attr}") if a else ident

    def skip(self, rtype: str, ident: str, why: str) -> None:
        self.skipped.append({"type": rtype, "id": ident, "why": why})

    def variable(self, name: str, value: Any, description: str = "", sensitive: bool = True) -> hcl.Ref:
        self.variables[name] = {"description": description, "sensitive": sensitive}
        self.tfvars[name] = value
        return hcl.Ref(f"var.{name}")


Exporter = Callable[[Ctx], None]
_REGISTRY: list[tuple[int, str, Exporter]] = []


def exporter(order: int, name: str):
    def deco(fn: Exporter) -> Exporter:
        _REGISTRY.append((order, name, fn))
        return fn
    return deco


def registered() -> list[tuple[int, str, Exporter]]:
    return sorted(_REGISTRY, key=lambda t: t[0])


def tags_of(items) -> dict[str, str]:
    """AWS tag list -> dict, without the aws:* system tags."""
    out: dict[str, str] = {}
    for t in items or []:
        k = t.get("Key") if isinstance(t, dict) else None
        if k and not k.startswith("aws:"):
            out[k] = t.get("Value", "")
    return out


def _interpolate(v, interp: dict[str, str]):
    """Replace known generated ids inside string values with ``${...}`` references (e.g. an API id inside an execute-api ARN)."""
    if isinstance(v, str):
        hits = [k for k in interp if k in v]
        if not hits:
            return v
        pat = re.compile("(" + "|".join(re.escape(k) for k in sorted(hits, key=len, reverse=True)) + ")")
        parts = []
        for i, piece in enumerate(pat.split(v)):
            if i % 2:
                parts.append(hcl.Ref(interp[piece]))
            elif piece:
                parts.append(piece)
        return hcl.Tpl(parts)
    if isinstance(v, dict):
        return {k: _interpolate(x, interp) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_interpolate(x, interp) for x in v]
    return v


def _interpolate_blocks(blocks, interp):
    return [(b[0], _interpolate(b[1], interp), _interpolate_blocks(b[2], interp)) if len(b) > 2 else (b[0], _interpolate(b[1], interp))
            for b in blocks]


_SET_ATTRS = {"subnet_ids", "vpc_security_group_ids", "security_groups", "depends_on", "cidr_blocks", "ipv6_cidr_blocks"}


def _sorted_sets(attrs: dict) -> dict:
    """Terraform treats these attributes as sets; sort them so two exports of the same stack are textually identical."""
    out = {}
    for k, v in attrs.items():
        if k in _SET_ATTRS and isinstance(v, list):
            v = sorted(v, key=lambda x: x.expr if isinstance(x, hcl.Ref) else str(x))
        out[k] = v
    return out


def render_files(ctx: Ctx, provider: str = "aws", providers: dict[str, dict[str, str]] | None = None) -> dict[str, str]:
    header = "# Generated by Vyomi from the simulator's live state. Resource references are real references.\n"
    files: dict[str, list[str]] = {}
    for rtype, name, attrs in ctx.data:
        files.setdefault("data.tf", []).append(hcl.block("data", [rtype, name], attrs))
    for r in sorted(ctx.resources, key=lambda x: (x.file, x.type, x.name)):
        attrs, blocks = _sorted_sets(_interpolate(r.attrs, ctx.interp)), _interpolate_blocks(r.blocks, ctx.interp)
        blocks = [(b[0], _sorted_sets(b[1])) + tuple(b[2:]) for b in blocks]
        files.setdefault(r.file, []).append(hcl.block("resource", [r.type, r.name], attrs, blocks))
    out = {name: header + "\n" + "\n\n".join(blocks) + "\n" for name, blocks in sorted(files.items())}
    out["versions.tf"] = (header + '\nterraform {\n  required_version = ">= 1.6.0"\n  required_providers {\n'
                          '    aws = {\n      source  = "hashicorp/aws"\n      version = "~> 5.0"\n    }\n  }\n}\n')
    out["providers.tf"] = header + "\n" + hcl.block("provider", ["aws"], {"region": ctx.region}) + "\n"
    if ctx.variables:
        out["variables.tf"] = header + "\n" + "\n\n".join(
            hcl.block("variable", [n], {"type": hcl.Ref("string"), "description": v["description"] or None,
                                         "sensitive": True if v["sensitive"] else None})
            for n, v in sorted(ctx.variables.items())) + "\n"
        out["terraform.tfvars"] = "\n".join(f"{hcl.key(k)} = {hcl.value(v)}" for k, v in sorted(ctx.tfvars.items())) + "\n"
    return out
