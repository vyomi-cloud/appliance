#!/usr/bin/env python3
"""Check that packaging/tunnel/server.json (the MCP Registry entry) matches packaging/tunnel/package.json.

The release workflow publishes vyomi-tunnel to npm, then server.json to the MCP Registry. The registry only accepts the
entry when the npm tarball for packages[0].version carries an "mcpName" equal to server.json's name, so a version or name
bumped in one file but not the other fails the publish after npm already has the new version. This script fails first:

  server.json version == packages[0].version == package.json version
  server.json name == package.json mcpName
  packages[0] is the npm package named in package.json (registryType npm, identifier == package.json name)

Stdlib only.

  python3 scripts/check_server_json.py [dir]     # default dir: packaging/tunnel
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "packaging" / "tunnel"


def load(p, errors):
    try:
        return json.loads(p.read_text())
    except FileNotFoundError:
        errors.append(f"{p}: missing")
    except json.JSONDecodeError as e:
        errors.append(f"{p}: invalid JSON: {e}")
    return None


def check(d):
    errors = []
    pkg = load(d / "package.json", errors)
    srv = load(d / "server.json", errors)
    if pkg is None or srv is None:
        return errors

    packages = srv.get("packages") or []
    if not packages:
        return errors + ["server.json: no packages[]"]
    p0 = packages[0]

    versions = {
        "server.json version": srv.get("version"),
        "server.json packages[0].version": p0.get("version"),
        "package.json version": pkg.get("version"),
    }
    if len(set(versions.values())) != 1:
        errors.append("versions differ: " + ", ".join(f"{k} = {v!r}" for k, v in versions.items()))

    if not pkg.get("mcpName"):
        errors.append("package.json has no mcpName (the MCP Registry needs it in the published npm tarball)")
    elif srv.get("name") != pkg["mcpName"]:
        errors.append(f"server.json name {srv.get('name')!r} != package.json mcpName {pkg['mcpName']!r}")

    if p0.get("registryType") != "npm":
        errors.append(f"server.json packages[0].registryType should be 'npm', got {p0.get('registryType')!r}")
    if p0.get("identifier") != pkg.get("name"):
        errors.append(f"server.json packages[0].identifier {p0.get('identifier')!r} != package.json name {pkg.get('name')!r}")
    return errors


def main(argv):
    d = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT
    errors = check(d)
    for e in errors:
        print(f"check_server_json: {e}", file=sys.stderr)
    if errors:
        return 1
    print(f"server.json matches package.json ({d}): {json.loads((d / 'server.json').read_text())['name']} {json.loads((d / 'package.json').read_text())['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
