#!/usr/bin/env python3
"""Merge the `mcp` component (portal-app-component.yaml) into the portal's App Platform spec.

    doctl apps spec get "$PORTAL_APP_ID" > portal-app.yaml
    python3 deploy/mcp-hosted/add-component.py portal-app.yaml            # check only, prints the diff
    python3 deploy/mcp-hosted/add-component.py portal-app.yaml --apply    # rewrite the file
    doctl apps update "$PORTAL_APP_ID" --spec portal-app.yaml

It only ever adds or replaces the `mcp` service and the `/mcp` ingress rule. Every other component, every other
ingress rule and every other key of the spec is left byte-for-byte alone, so the portal cannot be changed by
accident. Re-running it is a no-op once the component is in place.

Needs PyYAML (`pip install pyyaml`), which doctl output requires anyway.
"""
import argparse
import copy
import pathlib
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - environment problem, not logic
    sys.exit("add-component.py needs PyYAML: pip install pyyaml")

HERE = pathlib.Path(__file__).resolve().parent
COMPONENT = HERE / "portal-app-component.yaml"
NAME = "mcp"
PREFIX = "/mcp"


def load(path):
    with open(path) as fh:
        spec = yaml.safe_load(fh)
    if not isinstance(spec, dict):
        sys.exit(f"{path} is not an App Platform spec")
    return spec


def merge(spec, piece, tag=None):
    """Return (new_spec, [what changed]). Never touches anything but the mcp service and the /mcp rule."""
    out = copy.deepcopy(spec)
    changes = []

    service = copy.deepcopy(piece["services"][0])
    if tag:
        service["image"]["tag"] = tag
    services = out.setdefault("services", [])
    for i, existing in enumerate(services):
        if existing.get("name") == NAME:
            if existing != service:
                services[i] = service
                changes.append(f"replaced the {NAME} service (image tag {service['image']['tag']})")
            break
    else:
        services.append(service)
        changes.append(f"added the {NAME} service (image tag {service['image']['tag']})")

    rule = copy.deepcopy(piece["ingress"]["rules"][0])
    rules = out.setdefault("ingress", {}).setdefault("rules", [])
    for i, existing in enumerate(rules):
        if existing.get("component", {}).get("name") == NAME:
            if existing != rule:
                rules[i] = rule
                changes.append(f"replaced the {PREFIX} ingress rule")
            break
    else:
        # A rule whose prefix is "/" matches everything, so the portal's catch-all has to stay last.
        at = len(rules)
        for i, existing in enumerate(rules):
            if existing.get("match", {}).get("path", {}).get("prefix", "") == "/":
                at = i
                break
        rules.insert(at, rule)
        changes.append(f"added the {PREFIX} ingress rule at position {at + 1} of {len(rules)}")

    return out, changes


def check_untouched(before, after):
    """Fail loudly if anything other than the mcp service / rule differs."""
    def strip(spec):
        s = copy.deepcopy(spec)
        s["services"] = [x for x in s.get("services", []) if x.get("name") != NAME]
        rules = s.get("ingress", {}).get("rules")
        if rules is not None:
            s["ingress"]["rules"] = [r for r in rules if r.get("component", {}).get("name") != NAME]
        return s

    if strip(before) != strip(after):
        sys.exit("refusing to write: the merge would change something other than the mcp component")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="the portal app spec, from `doctl apps spec get <app-id>`")
    ap.add_argument("--apply", action="store_true", help="write the merged spec back to the file")
    ap.add_argument("--tag", help="image tag to pin (default: the tag in portal-app-component.yaml)")
    args = ap.parse_args()

    spec = load(args.spec)
    piece = load(COMPONENT)
    merged, changes = merge(spec, piece, args.tag)
    check_untouched(spec, merged)

    others = [c.get("name") for c in merged.get("services", []) if c.get("name") != NAME]
    print(f"other components left untouched: {', '.join(others) or 'none'}")
    if not changes:
        print("nothing to do: the mcp component and its /mcp rule are already exactly as specified")
        return 0
    for c in changes:
        print(f"  - {c}")
    if not args.apply:
        print("\ncheck only; pass --apply to write it, then `doctl apps update <app-id> --spec <file>`")
        return 0
    pathlib.Path(args.spec).write_text(yaml.safe_dump(merged, sort_keys=False, width=120))
    print(f"\nwrote {args.spec}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
