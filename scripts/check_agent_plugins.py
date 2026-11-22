#!/usr/bin/env python3
"""Check that every manifest in integrations/claude-plugins describes the same plugin.

One package serves several coding agents, each through its own manifest:

  plugins/<p>/plugin.json + mcp.json       Agent Plugins 1.0 (Codex 0.146+, Cursor 3.13+, Copilot, VS Code, Kiro, ChatGPT)
  plugins/<p>/.claude-plugin/plugin.json   Claude Code
  plugins/<p>/.codex-plugin/plugin.json    Codex before 0.146
  plugins/<p>/.cursor-plugin/plugin.json   Cursor before 3.13
  plugins/<p>/.mcp.json                    Claude Code, older Codex, older Cursor
  .claude-plugin/marketplace.json          Claude Code, Copilot CLI
  .agents/plugins/marketplace.json         Codex
  .cursor-plugin/marketplace.json          Cursor team marketplaces

A version bumped in one but not the others means some agents never update; an MCP server changed in one means some
agents run the old command; a "Needs vyomi-tunnel ..." note changed in one means some listings promise the wrong
tunnel. Icon paths (logo, composerIcon) must exist inside the plugin, manifests that state a license agree on it, and the
root has LICENSE and SECURITY.md. This script fails on any such drift. Stdlib only.

  python3 scripts/check_agent_plugins.py [root]     # default root: integrations/claude-plugins

With --schemas, it also validates the files against the published JSON Schemas (needs the `jsonschema` package):
plugin.json and mcp.json against Agent Plugins 1.0.0 (github.com/agentplugins/agent-plugins-spec, schemas/1.0.0), and
.cursor-plugin/plugin.json and .cursor-plugin/marketplace.json against Cursor's (github.com/cursor/plugins, schemas/).
Claude Code's files are covered by `claude plugin validate`; Codex publishes no JSON Schema for .codex-plugin/ or
.agents/plugins/ (its loader is codex-rs/core-plugins in openai/codex).

  python3 scripts/check_agent_plugins.py [root] --schemas <agent-plugins-spec checkout> <cursor-plugins checkout>
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "integrations" / "claude-plugins"
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
# The tunnel requirement every description repeats, e.g. "Needs vyomi-tunnel 1.3.0+ (1.4.0+ for the AGENTS.md step)".
TUNNEL_NOTE_RE = re.compile(r"Needs vyomi-tunnel [0-9][^\s]*(?: \([^)]*\))?")
NAME_RE = re.compile(r"^(?!.*--)(?!.*\.\.)[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$")


def load(p, errors):
    try:
        return json.loads(p.read_text())
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        errors.append(f"{p}: invalid JSON: {e}")
        return None


def servers(d):
    """{name: (command, args)} from an mcpServers object."""
    out = {}
    for name, s in (d or {}).get("mcpServers", {}).items():
        out[name] = (s.get("command"), tuple(s.get("args", [])), s.get("url"))
    return out


def frontmatter(md):
    m = re.match(r"^---\n(.*?)\n---\n", md, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def check(root):
    errors = []
    root = pathlib.Path(root)
    cmp = load(root / ".claude-plugin" / "marketplace.json", errors)
    if not cmp:
        return [f"{root}/.claude-plugin/marketplace.json is missing"]
    meta_ver = cmp.get("metadata", {}).get("version")
    codex_mp = load(root / ".agents" / "plugins" / "marketplace.json", errors)
    cursor_mp = load(root / ".cursor-plugin" / "marketplace.json", errors)
    codex_entries = {p["name"]: p for p in (codex_mp or {}).get("plugins", [])}
    cursor_entries = {p["name"]: p for p in (cursor_mp or {}).get("plugins", [])}

    for entry in cmp.get("plugins", []):
        name, ver = entry["name"], entry.get("version")
        pdir = (root / entry["source"]).resolve()
        where = f"plugin {name}"
        if not NAME_RE.match(name):
            errors.append(f"{where}: name must be lowercase letters, digits, '.' and '-' (Agent Plugins)")
        if meta_ver and meta_ver != ver:
            errors.append(f"{where}: marketplace metadata.version {meta_ver} != plugin entry {ver}")

        manifests = {
            "plugin.json": load(pdir / "plugin.json", errors),
            ".claude-plugin/plugin.json": load(pdir / ".claude-plugin" / "plugin.json", errors),
            ".codex-plugin/plugin.json": load(pdir / ".codex-plugin" / "plugin.json", errors),
            ".cursor-plugin/plugin.json": load(pdir / ".cursor-plugin" / "plugin.json", errors),
        }
        for rel in ("plugin.json", ".claude-plugin/plugin.json"):
            if manifests[rel] is None:
                errors.append(f"{where}: {rel} is missing")
        for rel, m in manifests.items():
            if m is None:
                continue
            if m.get("name") != name:
                errors.append(f"{where}: {rel} name is {m.get('name')!r}")
            if m.get("version") != ver:
                errors.append(f"{where}: {rel} version {m.get('version')} != marketplace {ver}")

        # License: the same SPDX id in every manifest that states one (the Claude directory refuses a plugin without one).
        licenses = {rel: m["license"] for rel, m in manifests.items() if m is not None and "license" in m}
        if len(set(licenses.values())) > 1:
            errors.append(f"{where}: manifests disagree on the license: {licenses}")

        portable = manifests["plugin.json"]
        if portable is not None and portable.get("$schema") != PLUGIN_SCHEMA:
            errors.append(f"{where}: plugin.json $schema must be {PLUGIN_SCHEMA}")

        # MCP: the portable mcp.json and the legacy .mcp.json must declare the same servers.
        pmcp, lmcp = load(pdir / "mcp.json", errors), load(pdir / ".mcp.json", errors)
        if pmcp is not None:
            if pmcp.get("$schema") != MCP_SCHEMA:
                errors.append(f"{where}: mcp.json $schema must be {MCP_SCHEMA}")
            for sname, s in pmcp.get("mcpServers", {}).items():
                if s.get("type") not in ("stdio", "streamable-http", "sse"):
                    errors.append(f"{where}: mcp.json server {sname} needs a transport type (stdio, streamable-http, sse)")
        if (pmcp is None) != (lmcp is None):
            errors.append(f"{where}: mcp.json and .mcp.json must both exist or both be absent")
        elif pmcp is not None and servers(pmcp) != servers(lmcp):
            errors.append(f"{where}: mcp.json {servers(pmcp)} != .mcp.json {servers(lmcp)}")
        claude = manifests[".claude-plugin/plugin.json"] or {}
        if lmcp is not None and "mcpServers" in claude:
            errors.append(f"{where}: .claude-plugin/plugin.json declares mcpServers inline while .mcp.json exists; Claude Code would register the server twice")
        for rel in (".codex-plugin/plugin.json", ".cursor-plugin/plugin.json"):
            m = manifests[rel]
            if m is None:
                continue
            ref = m.get("mcpServers")
            if lmcp is not None and ref != "./.mcp.json":
                errors.append(f"{where}: {rel} mcpServers should be './.mcp.json', got {ref!r}")
            if m.get("skills") and not (pdir / m["skills"]).is_dir():
                errors.append(f"{where}: {rel} skills path {m['skills']} does not exist")

        # Descriptions: every manifest and marketplace entry carries the same tunnel requirement note.
        notes = {}
        described = [(rel, m) for rel, m in manifests.items() if m is not None]
        described += [(".claude-plugin/marketplace.json entry", entry)]
        if cursor_mp is not None and name in cursor_entries:
            described.append((".cursor-plugin/marketplace.json entry", cursor_entries[name]))
        if codex_mp is not None and name in codex_entries:
            described.append((".agents/plugins/marketplace.json entry", codex_entries[name]))
        for rel, m in described:
            found = TUNNEL_NOTE_RE.findall(m.get("description") or "")
            if len(found) != 1:
                errors.append(f"{where}: {rel} description needs exactly one 'Needs vyomi-tunnel ...' note, found {found}")
            else:
                notes[rel] = found[0]
        if len(set(notes.values())) > 1:
            errors.append(f"{where}: descriptions disagree on the tunnel requirement: {notes}")

        # Icons: logo / composerIcon paths stay inside the plugin and exist. Codex ignores paths without a leading './'.
        icons = {".cursor-plugin/plugin.json logo": (manifests[".cursor-plugin/plugin.json"] or {}).get("logo")}
        for rel, iface in (("plugin.json extensions.com.openai.interface", ((portable or {}).get("extensions", {}).get("com.openai", {}).get("interface") or {})),
                           (".codex-plugin/plugin.json interface", ((manifests[".codex-plugin/plugin.json"] or {}).get("interface") or {}))):
            for key in ("logo", "logoDark", "composerIcon"):
                icons[f"{rel}.{key}"] = iface.get(key)
                if iface.get(key) and not iface[key].startswith("./"):
                    errors.append(f"{where}: {rel}.{key} must start with './' (Codex ignores it otherwise)")
        for label, icon in icons.items():
            if not icon or re.match(r"^https?://", icon):
                continue
            ip = (pdir / icon).resolve()
            if pdir not in ip.parents or not ip.is_file():
                errors.append(f"{where}: {label} {icon} is not a file inside the plugin")

        # Skills (Agent Skills): skills/<dir>/SKILL.md with name == dir and a description.
        skills = sorted((pdir / "skills").glob("*/SKILL.md"))
        if not skills:
            errors.append(f"{where}: no skills/<name>/SKILL.md")
        for sk in skills:
            fm = frontmatter(sk.read_text())
            if fm.get("name") != sk.parent.name:
                errors.append(f"{where}: {sk.relative_to(pdir)} frontmatter name {fm.get('name')!r} != directory {sk.parent.name!r}")
            if not fm.get("description"):
                errors.append(f"{where}: {sk.relative_to(pdir)} has no description")
        onboarding = ((portable or {}).get("extensions", {}).get("com.openai", {}).get("onboardingSkill"))
        if onboarding and not (pdir / onboarding).is_file():
            errors.append(f"{where}: extensions.com.openai.onboardingSkill {onboarding} does not exist")

        # Other marketplaces list the same plugin at the same place.
        src = (root / entry["source"]).resolve()
        if codex_mp is not None:
            ce = codex_entries.get(name)
            path = ce and (ce["source"] if isinstance(ce["source"], str) else ce["source"].get("path"))
            if not ce or (root / path).resolve() != src:
                errors.append(f"{where}: .agents/plugins/marketplace.json must list it at {entry['source']}")
            elif not ce.get("policy", {}).get("installation") or not ce.get("category"):
                errors.append(f"{where}: .agents/plugins/marketplace.json entry needs policy.installation and category")
        if cursor_mp is not None:
            ue = cursor_entries.get(name)
            if not ue or (root / ue["source"]).resolve() != src:
                errors.append(f"{where}: .cursor-plugin/marketplace.json must list it at {entry['source']}")

    # The marketplace repo root carries the license and the security policy (directory listings link to both).
    for f in ("LICENSE", "SECURITY.md"):
        if not (root / f).is_file():
            errors.append(f"{root}/{f} is missing")

    for label, entries in ((".agents/plugins/marketplace.json", codex_entries), (".cursor-plugin/marketplace.json", cursor_entries)):
        extra = set(entries) - {p["name"] for p in cmp.get("plugins", [])}
        if extra:
            errors.append(f"{label} lists plugins not in .claude-plugin/marketplace.json: {sorted(extra)}")
    return errors


def check_schemas(root, spec_dir, cursor_dir):
    """Validate the portable and Cursor files against their published JSON Schemas."""
    import jsonschema  # only needed for --schemas

    root, errors = pathlib.Path(root), []
    spec, cursor = pathlib.Path(spec_dir) / "schemas" / "1.0.0", pathlib.Path(cursor_dir) / "schemas"
    mp = json.loads((root / ".claude-plugin" / "marketplace.json").read_text())
    jobs = [(root / ".cursor-plugin" / "marketplace.json", cursor / "marketplace.schema.json")]
    for entry in mp.get("plugins", []):
        pdir = root / entry["source"]
        jobs += [(pdir / "plugin.json", spec / "plugin.schema.json"), (pdir / "mcp.json", spec / "mcp.schema.json"),
                 (pdir / ".cursor-plugin" / "plugin.json", cursor / "plugin.schema.json")]
    for doc, sch in jobs:
        if not doc.exists():
            continue
        schema = json.loads(sch.read_text())
        validator = jsonschema.validators.validator_for(schema)(schema, format_checker=jsonschema.FormatChecker())
        for e in validator.iter_errors(json.loads(doc.read_text())):
            errors.append(f"{doc.relative_to(root)} vs {sch.name}: {'/'.join(map(str, e.path)) or '(root)'}: {e.message}")
    return errors


def main(argv):
    args = argv[1:]
    schemas = None
    if "--schemas" in args:
        i = args.index("--schemas")
        schemas, args = args[i + 1:i + 3], args[:i] + args[i + 3:]
        if len(schemas) != 2:
            sys.exit("check_agent_plugins: --schemas needs <agent-plugins-spec dir> <cursor-plugins dir>")
    root = pathlib.Path(args[0]) if args else DEFAULT
    errors = check(root)
    if schemas and not errors:
        errors = check_schemas(root, *schemas)
    for e in errors:
        print(f"check_agent_plugins: {e}", file=sys.stderr)
    if errors:
        return 1
    print(f"agent plugin manifests consistent ({root})" + (" and valid against the published schemas" if schemas else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
