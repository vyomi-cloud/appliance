#!/usr/bin/env python3
"""Claude Code PreToolUse guard for the v4 branch rules (docs/architecture/v4.0/V4-BRANCH-ARCHITECTURE.md, section 5.1 layer 5).

Reads the hook JSON on stdin; for Bash commands it refuses (exit 2, reason on stderr) what the rules forbid:
  * `git add -A` / `--all` / `.`                     (stage explicit paths)
  * bare `git stash`, `stash pop|drop|clear|save`    (use a WIP commit; `stash push -m <tag>` / `stash apply <sha>` are allowed)
  * any force push (`-f`, `--force`, `--force-with-lease`, `+refspec`)
  * a push to `main`/`master`, any tag push, or `git tag` that is not `archive/*`   (owner's go only)
  * a push to the trunk / release branch / portal trunk unless the command carries VYOMI_INTEGRATOR=1  (integrator only)
Everything else passes. Fail-open on malformed input so a bug here never blocks normal work.
"""
import json
import re
import shlex
import sys

TRUNKS = {"v4-on-main", "release/v4.0.0", "v4-nano-portal"}
PROTECTED = {"main", "master"}


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


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("tool_name") not in (None, "Bash"):
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    why = check(cmd)
    if why:
        sys.stderr.write("v4 branch rules: " + why + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
