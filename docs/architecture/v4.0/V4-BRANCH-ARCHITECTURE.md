# v4 — branch architecture

Status: 2026-11-09. This is the rule every session (human or agent) follows for v4 work. Primary rule first.

## 1. Primary rule

**`v4-on-main` (appliance repo) is the shared trunk and the source of truth for all v4 work.**
Every new branch is created from `origin/v4-on-main`. `release/v4.0.0-dev` is superseded (`v4-on-main` already contains it
and is ~800 commits ahead) and takes no new work.

## 2. The lines

```
SHARED TRUNK   v4-on-main                         (appliance repo)
               shared cores (core/*.py) and consoles (consoles/src) are changed ONLY here

NANO           local -> v4-on-main -> [vendor the Nano bundle] -> v4-nano-portal -> main (portal)
                                         (vendor_to_portal.py)     (portal repo;      (go-live)
                                                                    test on :8099)

HEADLESS       local -> v4-on-main -> v4/headless -> main (appliance)
                                       (headless-only code;  (go-live)
                                        test on the real Docker stack)
```

| Branch | Repo | Role | Takes |
|---|---|---|---|
| `v4-on-main` | appliance | shared trunk | shared cores, consoles, registry, tests, docs |
| `v4-nano-portal` | portal (`vyomi-cloud/portal`) | Nano line | vendored Nano bundle, portal pages/endpoints (Mesh login, VM-name reservation, key injection, runner dispatch, tier-to-licence mapping) |
| `v4/headless` | appliance | Headless line | headless-only code: k3s runtime, tunnel agent, booster image, boot scripts; hand-offs to the Codespace image |
| `main` (appliance) | appliance | go-live, headless | merges from `v4/headless` only when the owner says go-live; the release tag builds the booster image |
| `main` (portal) | portal | go-live, Nano | merges from `v4-nano-portal` only when the owner says go-live; a push auto-deploys and costs money |
| `vyomi-cloud/sandbox` | third repo | Codespace image (devcontainer, sshd feature, compose) | updated separately; not part of the lines above |

## 3. Rules

1. **Branch from the trunk.** `git fetch`; `git worktree add ../appliance-<topic> -b v4/<topic> origin/v4-on-main`.
   Before building a gap, grep `origin/v4-on-main` for it: other sessions may have landed it already.
2. **Shared files change only on the trunk.** `core/*.py`, `consoles/src/**`, `core/capabilities/**` and the Nano core lists
   are never hand-edited on `v4/headless` or `v4-nano-portal`. If a headless or Nano need changes shared code, land it on
   `v4-on-main` first.
3. **Merges flow one way:** `v4-on-main` into `v4/headless` and into the Nano bundle that is vendored into `v4-nano-portal`.
   Nothing flows back except through `v4-on-main`.
4. **Substrate-only code starts on its own line.** Headless-only (k3s runtime, tunnel agent, booster image) on `v4/headless`;
   Nano-only (portal) on `v4-nano-portal`.
5. **Test each line in its own substrate** before it moves on: Nano on the localhost portal (:8099, `.env` loaded) with the
   service worker and Pyodide; headless on the real Docker stack. A dev server is not a substitute for a container-backed feature.
6. **Built outputs are never merged by hand.** `wasm/v4`, `static/v4` and the vendored `wasm/core` copies are regenerated
   (`cd consoles && node build.mjs`, `python3 wasm/build_cores.py`) after a source merge.
7. **Nothing reaches `main`, a tag, a release or a deploy** until the owner says the release is ready to go live.
8. **Commit hygiene.** Explicit `git add <paths>`, never `git add -A`; never touch another session's worktree or branch
   (`appliance-v4main`, `appliance-v4headless` and the tunnel redesign belong to other sessions); never use bare `git stash`.
9. **Pushing:** push work branches only on the owner's say-so; do not force-push the trunk or the lines.

## 4. Open points (to be confirmed by the owner)

- Where a Nano change first lands (this doc: the trunk, then the portal). The owner's first sketch put the portal first.
- `v4/headless` is reused as the headless line instead of a new `v4-headless-appliance`; `v4-appliance-on-main` is dropped as
  redundant with the trunk.
- The tunnel redesign already on `v4-on-main` (stream framework, DNS-only agent resolver) supersedes the earlier
  `host`/`k3s` reserved-target branches; they are reconciled separately.
