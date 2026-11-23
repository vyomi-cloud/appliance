#!/usr/bin/env python3
"""Claude Code PreToolUse guard for the v4 branch rules (docs/architecture/v4.0/V4-BRANCH-ARCHITECTURE.md, section 5.1 layer 5).

Reads the hook JSON on stdin; for Bash commands it refuses (exit 2, reason on stderr) what the rules forbid:
  * `git add -A` / `--all` / `.`                     (stage explicit paths)
  * bare `git stash`, `stash pop|drop|clear|save`    (use a WIP commit; `stash push -m <tag>` / `stash apply <sha>` are allowed)
  * any force push (`-f`, `--force`, `--force-with-lease`, `+refspec`)
  * a push to `main`/`master`, any tag push, or `git tag` that is not `archive/*`   (owner's go only)
  * a push to the trunk / release branch / portal trunk unless the command carries VYOMI_INTEGRATOR=1  (integrator only)
  * a `git commit` that includes an input of scripts/gen_mcp_matrix.py (core/capabilities/**, wasm/docs/**, ...) while the
    embedded MCP knowledge (cmd/vyomi/mcp_*.json[.gz]) is stale, or regenerated but left out of the commit   (rule 10)
Everything else passes. Fail-open on malformed input so a bug here never blocks normal work.
"""
import json
import os
import re
import shlex
import subprocess
import sys

TRUNKS = {"v4-on-main", "release/v4.0.0", "v4-nano-portal"}
PROTECTED = {"main", "master"}

# Inputs of scripts/gen_mcp_matrix.py (keep in step with its docstring) and the outputs it writes.
MCP_INPUTS = (
    "core/capabilities/", "wasm/docs/", "wasm/nano-docs.js", "services/registry.json", "providers/capabilities.py",
    "core/pack_catalog.py", "providers/aws.py", "providers/gcp.py", "providers/azure.py", "docker-compose.appliance.yml",
    ".env.example", "scripts/mcp_wiring.json", "scripts/gen_mcp_matrix.py", "VERSION",
)
MCP_OUTPUTS = ("cmd/vyomi/mcp_matrix.json", "cmd/vyomi/mcp_caps.json.gz", "cmd/vyomi/mcp_docs.json.gz")
MCP_REGEN = "python3 scripts/gen_mcp_matrix.py"


def statements(cmd):
    return [s.strip() for s in re.split(r"&&|\|\||;|\||\n", cmd) if s.strip()]


def check(cmd):
    """Return a refusal reason or None."""
    for st in statements(cmd):
        try:
            tok = shlex.split(st, posix=True)
        except ValueError:
            continue
        while tok and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok[0]):
            tok = tok[1:]                                   # leading VAR=value words
        if len(tok) < 2 or tok[0] != "git":
            continue
        # skip global options: git -C <dir> ..., git -c k=v ...
        i = 1
        while i < len(tok) and tok[i].startswith("-"):
            i += 2 if tok[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
        if i >= len(tok):
            continue
        sub, args = tok[i], tok[i + 1:]
        if sub == "add":
            flags = [a for a in args if a.startswith("-")]
            if "-A" in flags or "--all" in flags or "." in args:
                return "git add -A / --all / '.' is not allowed: stage explicit paths (V4-BRANCH-ARCHITECTURE.md rule 8)."
        elif sub == "stash":
            action = args[0] if args else ""
            if action in ("", "pop", "drop", "clear", "save") or action.startswith("-"):
                if not (action == "push" or action.startswith("--")) or action in ("", "pop", "drop", "clear", "save"):
                    return ("bare 'git stash' / pop / drop / clear is not allowed: the stash is shared across worktrees. Use a WIP commit, "
                            "or 'git stash push -u -m <unique-tag>' and 'git stash apply <sha>' (rule 8).")
        elif sub == "tag":
            names = [a for a in args if not a.startswith("-")]
            deleting = any(a in ("-d", "--delete", "-l", "--list") for a in args)
            if names and not deleting and not all(n.startswith("archive/") for n in names[:1]):
                return "creating tags is the owner's call; only archive/* tags are allowed (rule 7, layer 2)."
        elif sub == "push":
            flags = [a for a in args if a.startswith("-")]
            pos = [a for a in args if not a.startswith("-")]
            if any(f in ("-f", "--force", "--force-with-lease") or f.startswith("--force-with-lease=") for f in flags) or any(a.startswith("+") for a in pos):
                return "force-push is not allowed on shared branches (rule 9)."
            if "--tags" in flags or "--follow-tags" in flags or "--mirror" in flags or "--all" in flags or any(a.startswith("refs/tags/") or a.startswith("tag") for a in pos[1:2] if a == "tag"):
                return "pushing tags is the owner's call (rule 7/9)."
            refs = pos[1:] if len(pos) > 1 else []
            dests = []
            for r in refs:
                dest = r.split(":")[-1] if ":" in r else r
                dests.append(dest.replace("refs/heads/", ""))
                if dest.startswith("refs/tags/"):
                    return "pushing tags is the owner's call (rule 7/9)."
            if any(d in PROTECTED for d in dests):
                return "pushing to main is the owner's go only (rule 7/9). Ask the owner."
            if any(d in TRUNKS for d in dests) and "VYOMI_INTEGRATOR=1" not in cmd:
                return ("the trunk / release / portal trunk are pushed by the integrator only (rule 9). "
                        "If you are the named integrator, prefix the command with VYOMI_INTEGRATOR=1.")
    return None


def _git(repo, *args):
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=20)
    return out.stdout.splitlines() if out.returncode == 0 else []


def _is_mcp_input(path):
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in MCP_INPUTS)


def mcp_check(cmd, cwd):
    """Refuse a commit that changes MCP knowledge inputs without the regenerated outputs (rule 10). Fail-open on any error."""
    cwd = cwd or os.getcwd()
    added, commit = [], None                                  # paths `git add`ed earlier in this command; the commit's args
    repo = cwd
    for st in statements(cmd):
        try:
            tok = shlex.split(st, posix=True)
        except ValueError:
            continue
        while tok and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok[0]):
            tok = tok[1:]
        if tok and tok[0] == "cd" and len(tok) > 1:
            cwd = os.path.join(cwd, os.path.expanduser(tok[1]))
            continue
        if len(tok) < 2 or tok[0] != "git":
            continue
        here, i = cwd, 1
        while i < len(tok) and tok[i].startswith("-"):
            if tok[i] == "-C" and i + 1 < len(tok):
                here = os.path.join(here, os.path.expanduser(tok[i + 1]))
            i += 2 if tok[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
        if i >= len(tok):
            continue
        if tok[i] == "add":
            added += [(here, a) for a in tok[i + 1:] if not a.startswith("-")]
        elif tok[i] == "commit" and commit is None:
            commit, repo = tok[i + 1:], here
    if commit is None:
        return None
    top = _git(repo, "rev-parse", "--show-toplevel")
    if not top or not os.path.isfile(os.path.join(top[0], "scripts", "gen_mcp_matrix.py")):
        return None
    top = top[0]
    paths = set(_git(top, "diff", "--cached", "--name-only"))
    for where, p in added:
        rel = os.path.relpath(os.path.normpath(os.path.join(where, p)), top)
        paths |= {f for f in _git(top, "ls-files", "-m", "-o", "--exclude-standard", "--", rel)} | {rel}
    if any(a == "--all" or re.match(r"^-[a-zA-Z]*a[a-zA-Z]*$", a) for a in commit):   # -a, -am, --all
        paths |= set(_git(top, "diff", "--name-only"))
    if not any(_is_mcp_input(p) for p in paths):
        return None
    try:
        res = subprocess.run([sys.executable, "scripts/gen_mcp_matrix.py", "--check"], cwd=top,
                             capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    if res.returncode == 1:
        detail = (res.stdout + res.stderr).strip().splitlines()
        return ("this commit changes an input of the embedded MCP knowledge but the outputs are stale"
                + (f" ({detail[-1]})" if detail else "") + f". Run `{MCP_REGEN}` and commit "
                + ", ".join(MCP_OUTPUTS) + " in the same commit (rule 10).")
    if res.returncode != 0:
        return None
    dirty = set(_git(top, "diff", "--name-only", "--", *MCP_OUTPUTS)) | set(_git(top, "diff", "--cached", "--name-only", "--", *MCP_OUTPUTS))
    missing = sorted(o for o in dirty if o not in paths)
    if missing:
        return ("the MCP knowledge is regenerated in the working tree but " + ", ".join(missing)
                + " is not in this commit. Stage it explicitly with the input change (rule 10).")
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("tool_name") not in (None, "Bash"):
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    why = check(cmd)
    if not why:
        try:
            why = mcp_check(cmd, data.get("cwd"))
        except Exception:
            why = None
    if why:
        sys.stderr.write("v4 branch rules: " + why + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
