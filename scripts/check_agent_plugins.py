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
agents run the old command. This script fails on any such drift. Stdlib only.

  python3 scripts/check_agent_plugins.py [root]     # default root: integrations/claude-plugins
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "integrations" / "claude-plugins"
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
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

    for label, entries in ((".agents/plugins/marketplace.json", codex_entries), (".cursor-plugin/marketplace.json", cursor_entries)):
        extra = set(entries) - {p["name"] for p in cmp.get("plugins", [])}
        if extra:
            errors.append(f"{label} lists plugins not in .claude-plugin/marketplace.json: {sorted(extra)}")
    return errors


def main(argv):
    root = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT
    errors = check(root)
    for e in errors:
        print(f"check_agent_plugins: {e}", file=sys.stderr)
    if errors:
        return 1
    print(f"agent plugin manifests consistent ({root})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
