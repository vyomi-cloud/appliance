"""Small HCL writer for the faithful Terraform exporter: values, nested blocks and raw expressions (references)."""
from __future__ import annotations

import json
import re
from typing import Any

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


class Ref:
    """A raw HCL expression, rendered unquoted (e.g. ``aws_vpc.main.id`` or ``jsonencode({...})``)."""
    __slots__ = ("expr",)

    def __init__(self, expr: str):
        self.expr = expr

    def __repr__(self) -> str:  # pragma: no cover
        return f"Ref({self.expr})"


class Tpl(Ref):
    """A quoted string with ``${expr}`` interpolations, e.g. ``"arn:aws:execute-api:...:${aws_api_gateway_rest_api.api.id}/*/*"``."""

    def __init__(self, parts: list):  # parts: str literals and Ref expressions
        out = []
        for p in parts:
            out.append(p.expr and "${" + p.expr + "}" if isinstance(p, Ref) else
                       json.dumps(p, ensure_ascii=False)[1:-1].replace("${", "$${").replace("%{", "%%{"))
        super().__init__('"' + "".join(out) + '"')


def string(text: str) -> str:
    # `${` and `%{` start template sequences in HCL strings; a literal one must be doubled.
    return json.dumps(text, ensure_ascii=False).replace("${", "$${").replace("%{", "%%{")


def key(k: Any) -> str:
    k = str(k)
    return k if _IDENT.match(k) else json.dumps(k, ensure_ascii=False)


def value(v: Any, ind: int = 0) -> str:
    pad, inner = "  " * ind, "  " * (ind + 1)
    if isinstance(v, Ref):
        return v.expr
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return string(v)
    if isinstance(v, dict):
        items = [(k, x) for k, x in v.items() if x is not None]
        if not items:
            return "{}"
        return "{\n" + "\n".join(f"{inner}{key(k)} = {value(x, ind + 1)}" for k, x in items) + f"\n{pad}}}"
    if isinstance(v, (list, tuple)):
        if not v:
            return "[]"
        return "[\n" + "\n".join(f"{inner}{value(x, ind + 1)}," for x in v) + f"\n{pad}]"
    return string(str(v))


def _canon(o: Any) -> Any:
    """Deterministic key order, so two exports of the same policy are textually identical."""
    if isinstance(o, dict):
        return {k: _canon(o[k]) for k in sorted(o)}
    if isinstance(o, list):
        return [_canon(x) for x in o]
    return o


def jsonencode(obj: Any) -> Ref:
    """A JSON document (IAM / bucket policy) as ``jsonencode({...})``: readable and diff-stable."""
    return Ref(f"jsonencode({value(_canon(obj), 1)})")


def body(attrs: dict[str, Any], blocks: list[tuple[str, dict[str, Any]]] | tuple = (), ind: int = 1) -> list[str]:
    pad = "  " * ind
    lines = [f"{pad}{key(k)} = {value(v, ind)}" for k, v in attrs.items() if v is not None]
    for blk in blocks:  # (name, attrs) or (name, attrs, [child blocks...])
        name, battrs = blk[0], blk[1]
        lines.append(f"{pad}{name} {{")
        lines.extend(body(battrs, blk[2] if len(blk) > 2 else (), ind + 1))
        lines.append(f"{pad}}}")
    return lines


def block(kind: str, labels: list[str], attrs: dict[str, Any], blocks: list[tuple[str, dict[str, Any]]] | tuple = ()) -> str:
    head = kind + "".join(f" {json.dumps(label)}" for label in labels)
    return "\n".join([f"{head} {{", *body(attrs, blocks), "}"])
