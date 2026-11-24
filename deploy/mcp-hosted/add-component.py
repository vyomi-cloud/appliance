#!/usr/bin/env python3
"""Merge the `mcp` component (portal-app-component.yaml) into the portal's App Platform spec.

    doctl apps spec get "$PORTAL_APP_ID" > portal-app.yaml
    python3 deploy/mcp-hosted/add-component.py portal-app.yaml            # check only, prints the diff
    export GHCR_PULL_CREDENTIALS='<github-user>:<token with read:packages>'   # the image is private
    python3 deploy/mcp-hosted/add-component.py portal-app.yaml --apply    # rewrite the file
    doctl apps update "$PORTAL_APP_ID" --spec portal-app.yaml
    rm portal-app.yaml                                                    # it held the token in plain text

The GHCR package is private, so App Platform pulls it with `registry_credentials` ("username:token"). They come
from GHCR_PULL_CREDENTIALS and are never printed. App Platform stores them encrypted: a later
`doctl apps spec get` returns an `EV[...]` value, which this script keeps as it is when GHCR_PULL_CREDENTIALS is
unset, so re-running it stays a no-op. Set GHCR_PULL_CREDENTIALS again to rotate the token. --public skips
credentials (only for a public package).

It only ever adds or replaces the `mcp` service and the `/mcp` ingress rule. Every other component, every other
ingress rule and every other key of the spec is left byte-for-byte alone, so the portal cannot be changed by
accident. Re-running it is a no-op once the component is in place.

Needs PyYAML (`pip install pyyaml`), which doctl output requires anyway.
"""
import argparse
import copy
import os
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
CREDS_ENV = "GHCR_PULL_CREDENTIALS"


def load(path):
    with open(path) as fh:
        spec = yaml.safe_load(fh)
    if not isinstance(spec, dict):
        sys.exit(f"{path} is not an App Platform spec")
    return spec


def merge(spec, piece, tag=None, creds=None, public=False):
    """Return (new_spec, [what changed]). Never touches anything but the mcp service and the /mcp rule.

    creds: "username:token" for the private GHCR package, or None to keep the credentials already in the spec
    (App Platform returns them encrypted as EV[...]). public=True: no credentials at all.
    """
    out = copy.deepcopy(spec)
    changes = []

    service = copy.deepcopy(piece["services"][0])
    if tag:
        service["image"]["tag"] = tag
    services = out.setdefault("services", [])
    existing = next((x for x in services if x.get("name") == NAME), None)
    if public:
        note = "no registry credentials (public package)"
    elif creds:
        if ":" not in creds or creds.startswith(":") or creds.endswith(":"):
            sys.exit(f"{CREDS_ENV} must look like <github-user>:<token>")
        service["image"]["registry_credentials"] = creds
        note = f"registry credentials from {CREDS_ENV}"
    else:
        kept = (existing or {}).get("image", {}).get("registry_credentials")
        if not kept:
            sys.exit(f"the GHCR package is private: set {CREDS_ENV}=<github-user>:<token with read:packages> "
                     "(or pass --public for a public package)")
        service["image"]["registry_credentials"] = kept
        note = "registry credentials kept from the current spec"
    for i, x in enumerate(services):
        if x is existing:
            if x != service:
                services[i] = service
                changes.append(f"replaced the {NAME} service (image tag {service['image']['tag']}; {note})")
            break
    else:
        services.append(service)
        changes.append(f"added the {NAME} service (image tag {service['image']['tag']}; {note})")

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
    ap.add_argument("--public", action="store_true", help="the GHCR package is public: no registry credentials")
    args = ap.parse_args()

    spec = load(args.spec)
    piece = load(COMPONENT)
    merged, changes = merge(spec, piece, args.tag, os.environ.get(CREDS_ENV) or None, args.public)
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
    path = pathlib.Path(args.spec)
    path.write_text(yaml.safe_dump(merged, sort_keys=False, width=120))
    if os.environ.get(CREDS_ENV) and not args.public:
        path.chmod(0o600)
        print(f"\nwrote {args.spec} (mode 600: it holds the GHCR token in plain text; delete it after "
              "`doctl apps update`, and don't paste a diff of it anywhere)")
    else:
        print(f"\nwrote {args.spec}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
