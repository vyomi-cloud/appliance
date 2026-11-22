#!/usr/bin/env python3
"""Pin the `mcp` component's image tag in a portal App Platform spec, and change nothing else.

    doctl apps spec get "$PORTAL_APP_ID" > portal-app.yaml
    python3 deploy/mcp-hosted/set-image-tag.py portal-app.yaml 0.1.1
    doctl apps update "$PORTAL_APP_ID" --spec portal-app.yaml

Used by .github/workflows/mcp-hosted-release.yml for a release, and by hand for the runbook's rollback. It exits
non-zero if the spec has no `mcp` service (add it first, per RUNBOOK.md) so a release can never silently deploy
nothing.
"""
import copy
import pathlib
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("set-image-tag.py needs PyYAML: pip install pyyaml")

NAME = "mcp"


def main(argv):
    if len(argv) != 3:
        sys.exit("usage: set-image-tag.py <portal-app-spec.yaml> <tag>")
    path, tag = pathlib.Path(argv[1]), argv[2]
    spec = yaml.safe_load(path.read_text())
    before = copy.deepcopy(spec)
    for service in spec.get("services") or []:
        if service.get("name") == NAME:
            image = service.get("image")
            if not image:
                sys.exit(f"the {NAME} component is not image-based; refusing to change it")
            was = image.get("tag")
            image["tag"] = tag
            # Nothing else may differ: compare with the tag put back.
            check = copy.deepcopy(spec)
            for s in check["services"]:
                if s.get("name") == NAME:
                    s["image"]["tag"] = was
            if check != before:
                sys.exit("refusing to write: more than the image tag would change")
            path.write_text(yaml.safe_dump(spec, sort_keys=False, width=120))
            print(f"{NAME}: image tag {was} -> {tag} in {path} (nothing else changed)")
            return 0
    sys.exit(f"no {NAME} service in {path}: add it first with deploy/mcp-hosted/add-component.py (see RUNBOOK.md)")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
