# v4 — branch architecture

Status: 2026-11-09. This is the rule every session (human or agent) follows for v4 work. Primary rule first.

## 1. Primary rule

**`v4-on-main` (appliance repo) is the shared trunk and the source of truth for all v4 work.**
Every new branch is created from `origin/v4-on-main`. `release/v4.0.0-dev` is superseded (`v4-on-main` already contains it
and is ~800 commits ahead) and takes no new work.

## 1a. Recommended structure (v3) — read this first

Status: RECOMMENDATION (2026-11-09) after review of v2 (section 1b) by the builder session. Where 1a differs from 1b, 2 or 3, 1a wins.
It keeps v2 (one trunk per repo, one release branch, vendor PR with drift check, run-only worktree, claims file, enforcement
layers) and makes four changes:

1. **Nothing is ever lost: topic branches are pushed immediately and kept.** Every session pushes its topic branch to origin as
   soon as it has a commit (`git push -u origin v4/<topic>`), under its own name, and again after every batch. Pushing a topic
   branch needs no approval. What needs the owner or the integrator is only: the trunk, `release/v4.0.0`, `main`, tags.
   A branch is deleted only after it is merged into the trunk AND its tip is tagged `archive/<branch>-<date>` on origin.
2. **Headless testing is a defined gate, not an empty branch.** No long-lived `v4/headless`. Instead a CI job `headless-smoke`
   (and the same script run locally by `scripts/v4-headless-smoke.sh`) builds the booster image from the trunk and runs the real Docker stack:
   core conformance, the live k3s tests (`VYOMI_LIVE_K3S=1 tests/conformance/test_k3s_live.py`, `test_k3s_platform_live.py`, `test_aws_eks_live.py`),
   and the relay tests. It must run on a quiet machine (the shared Docker VM is saturated by parallel sessions, which makes live k3s
   tests time out); preflight to the trunk and go-live both require it green.
3. **One document, one version.** Sections 1b to 3 are kept only as history; sections 1a, 4, 5 and 6 are the rule.
4. **Named integrator.** The owner names one integrator (a person or one session) who merges topic branches into the trunk and
   `release/v4.0.0`. Until named, the owner is the integrator. Topic-branch authors never merge to the trunk themselves.

Also: `origin/release/v4.0.0` already exists and has commits the trunk lacks (6 ahead, 15 behind); reconcile it with the trunk
before the freeze rather than cutting a new release branch.

```
APPLIANCE   v4/<topic> (pushed at once) --PR--> v4-on-main --freeze--> release/v4.0.0 --owner go--> main (tag v4.0.0)
                                                  |  headless-smoke gate (image + live k3s) before every merge to main
                                                  `- vendor_to_portal.py --apply (records the source SHA)
PORTAL      portal/<topic> (pushed at once) --PR--> v4-nano-portal --owner go, once--> main (paid deploy)
SANDBOX     main only, by PR; the appliance pins the image tag
```

## 1c. Current state of in-flight work (2026-11-09)

All branches below are pushed to origin under their own names (nothing is lost). None is merged into `v4-on-main` yet.
`v4-on-main` is at `265851d3`; `main` and the portal `v4-nano-portal` / `main` were not touched.

**Appliance repo** (all cut from the old `release/v4.0.0-dev`, ~800 commits behind the trunk; each must be ported onto
`origin/v4-on-main`, not merged as is)

| Branch | Tip | Contents | Port status |
|---|---|---|---|
| `v4/gap-close` | `bf682812` | A1 + A2/A3 + A4 merged | A2/A3 are **already on the trunk** (hostname scope, create-database): drop. A4: port only what the trunk lacks. |
| `v4/gap-A1` | `740844c7` | Azure Backup for AKS, shared kube layer | port (in progress on `v4/merge-to-main`) |
| `v4/gap-A23`, `v4/gap-A4` | `aa2fe828`, `10f419b2` | App Services, APIM capacity | see `v4/gap-close` |
| `v4/k3s-backend`, `v4/k8s-full` | `61d5a0ec` | real k3s runtime, `RealK8sBackend` (headless only) | port (in progress) |
| `v4/k8s-tier-gate` | `f58f3c48` | Pro/Max gate for AKS/EKS/GKE | port (in progress) |
| `v4/k8s-platform` | `6e1b64e1` | versions, pools, identity, LB, storage; live tests not green | port after the three above |
| `v4/eks` | `3ad0fccc` | EKS core + console; live test partly passed | port after the three above |
| `v4/tunnel-keeper`, `v4/tunnel-k3s` | `eacf1ecd`, `dbab8a5d` | keeper, agent roles, `forward` | **do not merge**: the trunk has a redesigned tunnel (stream framework, DNS-only resolver); reconcile separately |
| `v4/docs-branch-arch` | this doc | branch architecture | merge when the owner approves 1a |
| `v4/merge-to-main` | in progress | the port itself | push when the agent finishes |

**Portal repo**

| Branch | Tip | Contents | Status |
|---|---|---|---|
| `portal/wip-snapshot-20261109` | `193e505` | snapshot of the shared `portal-v4nano` working tree (Sandboxes grid, Git runners, Installation restyle, Mesh codespaces grid, plus other sessions' uncommitted edits) | **not for merge**; split per topic into `portal/<topic>` branches, then delete |

Rules that follow from this table:
- A branch cut from a stale base is ported by re-applying its intent onto a fresh `v4/<topic>` from `origin/v4-on-main`
  (cherry-pick by file, rebuild the outputs), never by merging the stale line.
- Before porting, grep the trunk for the feature; other sessions may already have landed it (A2/A3 were).
- Open decisions: approve section 1a; name the integrator (until named, the owner is the integrator).

## 1b. Proposed structure (v2) — one trunk per repo, one release branch

Status: PROPOSAL (2026-11-09), for the owner and the aligning session. If approved it replaces sections 2 and 3 where they differ
(notably `v4/headless`); sections 4 to 6 (why sessions conflict, enforcement, gaps) stay and apply to it.

```
APPLIANCE REPO (vyomi-cloud/appliance)

  v4/<topic> ──PR──▶  v4-on-main  ──freeze──▶  release/v4.0.0  ──owner go──▶  main  (tag v4.0.0)
  (1 per session,     (the trunk: shared cores,    (version bump,            (protected)
   from fresh trunk)   consoles, headless, relay,   changelog, checks;
                       tunnel, wasm/ Nano bundle)   fixes only)
                                │
                                └── vendor_to_portal.py --apply (records the source SHA)
                                          │
PORTAL REPO (vyomi-cloud/portal)          ▼
  portal/<topic> ──PR──▶  v4-nano-portal  ──owner go, once──▶  main  (paid deploy)
  (portal-only code)      (portal code + vendored Nano bundle)   (protected)

THIRD REPO (vyomi-cloud/sandbox): the Codespace image. `main` only, by PR; the appliance pins the image tag.
```

### Changes from sections 2 and 3

1. **No long-lived `v4/headless` branch.** It is 0 commits ahead of the trunk (150 behind), so it adds a merge hop and a place
   where shared changes can get stuck. Headless-only code is isolated by path (`codespace/`, `packaging/`, `wasm/relay/`, the k3s
   runtime) and by its own CI suite, not by a branch. The trunk goes to `main` in one step. If a genuinely separate headless
   release cadence appears later, add the branch then, cut from the trunk.
2. **`release/v4.0.0` is part of the line.** Cut from the trunk at freeze; carries the version bump, changelog and
   `release-checks`; takes fixes only. Go-live is a PR from it to `main` and the owner tags. Afterwards `main` merges back into the
   trunk so `VERSION` matches. Nobody pushes to it outside this flow.
3. **The portal receives two kinds of change only.**
   - Portal-only code (pages, endpoints, Mesh login, keep-alive, tier mapping) on `portal/<topic>` branches.
   - The Nano bundle, only through a vendor PR: run `python3 wasm/vendor_to_portal.py --apply` from a named appliance SHA, which
     writes that SHA to `app/nano/.vendored-from`. CI fails any other PR that touches `app/nano/**`. This removes the
     "portal edit overwritten by the next `--apply`" failure for good. Existing portal-ahead edits are back-ported to `wasm/`
     before the first vendor PR.
4. **A run-only worktree for local testing.** `scripts/v4-run-local.sh` builds `portal-run` from the current `v4-nano-portal`
   plus a vendor of the trunk's latest `wasm/` and serves `:8099`. Nobody edits it. Local testing therefore always shows both
   sides' latest features (the shared, hand-edited checkout is why features go missing today).
5. **Naming.** Appliance topics: `v4/<topic>`. Portal topics: `portal/<topic>`. The old `v4/ng*`, `v4/ns*` and similar branches are
   tagged (archive) and deleted once merged (section 6, item 6).

### Day-to-day

- Start with `scripts/v4-session-start.sh <topic>`: fetch, one worktree off fresh `origin/v4-on-main` (or `origin/v4-nano-portal`),
  claim row added (section 5.2).
- Topic branches live at most 3 days and rebase daily.
- Topic branches may be pushed at any time (nothing is lost). The trunk and the release branch change only through the integrator
  (section 5.3). `main` and tags change only on the owner's go.
- Preflight before merging to the trunk: relay tests (`test-booster-link`, `test-booster-shell`, `test-booster-session-derived`,
  `test-mesh-ssh`), `vendor_to_portal.py --check`, and the substrate tests for the paths touched.

### Go-live sequence

1. Freeze: no new merges to the trunk; claims file is cleared or marked.
2. Vendor sync into `v4-nano-portal`; `--check` shows zero drift; test on `:8099` via `portal-run`.
3. Cut `release/v4.0.0` from the trunk; bump `VERSION`; changelog and notes; run `release-checks`.
4. Owner go: merge `release/v4.0.0` into appliance `main`; owner tags `v4.0.0` (the tag builds the images).
5. If the Codespace devcontainer changed, update `vyomi-cloud/sandbox` and pin the tag.
6. Owner go: merge `v4-nano-portal` into portal `main` once (a single paid deploy).
7. Smoke test; merge `main` back into the trunk.

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

## 4. Why sessions conflict, and the fix for each (observed 2026-11-09)

| Cause | Seen as | Fix |
|---|---|---|
| Several sessions edit one worktree | `portal-v4nano` had 18 uncommitted files from at least three sessions; changes had to be staged hunk by hunk | One worktree per session and topic. A shared checkout (the one serving `:8099`) is run-only and never edited. |
| Stale base | A branch cut from a local `release/v4.0.0` that was 43 commits behind origin was 48 behind the trunk; 3 relay files conflicted | Branch from fresh `origin/v4-on-main` (rule 1), keep branches short-lived, rebase daily, merge to the trunk often. |
| Same file in two places | Portal `vyomi-appbar.js` / `booster-link.js` / `clouds.html` differ from `wasm/` by ~209 / ~206 / ~974 lines; `vendor_to_portal.py --apply` would overwrite portal-side edits | Every file has one owner (section 5). Nano files are edited only under `wasm/` and reach the portal through the vendor script. Back-port portal-ahead edits to the trunk before the next `--apply`. |
| Two sessions in one area, unaware | Relay stream framework, host/k3s reserved targets | Claims file (section 5.2). |
| Parallel pushes to the trunk | Cherry-picking onto a trunk that moved under the branch | One integrator merges to the trunk (section 5.3); others push topic branches. |

## 5. Making every session follow it

A written rule only reaches sessions that read it, and a session's memory is per working folder (a session started in
`portal-v4nano` does not see what another saved from `appliance`). So the rule is carried by files in the repos, by hooks, and
finally by GitHub, which no session can bypass.

### 5.1 Enforcement layers (strongest first)

| # | Layer | Effect | Set up by |
|---|---|---|---|
| 1 | **GitHub branch protection**: appliance `main` and portal `main` require a pull request and the owner's approval, no force-push, no deletion; `v4-on-main` and `v4-nano-portal`: no force-push, no deletion, status checks required | Hard; nothing bypasses it | Owner (repo admin); a script can be prepared for review first |
| 2 | **Tag rule** for `v*` so only the owner creates release tags | Hard | Owner |
| 3 | **Repo `CLAUDE.md`** at the root of both repos (on `v4-on-main` and `v4-nano-portal`) stating the flow, "branch from fresh `origin/v4-on-main`", the claims file, no `git add -A`, no bare `git stash` | Every session in any worktree of the repo loads it | Builder session |
| 4 | **User-level `~/.claude/CLAUDE.md`** with a short pointer to this doc, for sessions started in other folders | Soft | Builder session |
| 5 | **Claude Code hooks** in the repo's `.claude/settings.json`: block `git push origin main`, force-push, tag pushes, `git add -A`, bare `git stash` | Automatic for Claude sessions only | Builder session |
| 6 | **Committed git hooks** (`core.hooksPath`): `pre-push` refuses a branch not based on current `origin/v4-on-main`, runs `vendor_to_portal.py --check` and the relay tests (`test-booster-link`, `test-booster-shell`, `test-booster-session-derived`, `test-mesh-ssh`) | Covers humans too; each clone opts in | Builder session |
| 7 | **`scripts/v4-session-start.sh <topic>`**: `git fetch`, creates `../appliance-<topic>` off `origin/v4-on-main` (or the portal equivalent off `origin/v4-nano-portal`), appends the claim | Convenience; makes the right thing the easy thing | Builder session |
| 8 | **CI drift check**: `vendor_to_portal.py --check` fails the build when the portal copy differs from `wasm/` | Hard for Nano drift | Builder session |

Minimum set: 1, 3, 5, 6. Only layer 1 cannot be bypassed.

### 5.2 Claims file

`docs/architecture/v4.0/SESSION-CLAIMS.md` on `v4-on-main`: one row per active topic with session, branch, repo, paths claimed,
start date. Add the row before editing; remove it when the branch merges. Before editing a path outside your own claim, read the
file and ask the owner if it is claimed. Claims older than 7 days without a push are treated as stale.

### 5.3 Integrator

Sessions push topic branches. One integrator (the owner, or one designated session) merges topic branches into `v4-on-main`,
runs the preflight (6), then runs the vendor step into `v4-nano-portal`. Two sessions never push to the trunk at the same time.

### 5.4 Ownership map (single place each file is edited)

| Files | Edited only in | Reaches |
|---|---|---|
| `core/*.py`, `consoles/src/**`, `core/capabilities/**`, Nano core lists | `v4-on-main` | `v4/headless` by merge; portal via build + vendor |
| `wasm/**` Nano bundle (incl. `vm/`, `vyomi-appbar.js`, `booster-link.js`, `clouds.html`, relay/Worker, `egress.mjs`) | `v4-on-main` | portal `app/nano/**` via `vendor_to_portal.py --apply` |
| `packaging/tunnel/**`, `wasm/relay/mesh-cli.mjs`, relay hub/agent | `v4-on-main` | npm / Homebrew at release |
| Portal pages and endpoints (`app/*.py`, `app/templates/**`: Mesh login, keep-alive, OAuth setup, tier mapping) | `v4-nano-portal` | portal `main` at go-live |
| Codespace image (devcontainer, sshd feature, compose) | `vyomi-cloud/sandbox` | new Codespaces only |

## 6. Gaps found in the lines above (for the aligning session)

1. **`release/v4.0.0` is not in the lines.** It carries the version bump, changelog and release checklist, and periodically merges
   `v4-on-main` in. `v4-on-main` itself still reads `VERSION` 3.0.45. State who updates it and when, and that nobody pushes to it
   directly.
2. **`v4/headless` is empty today** (0 ahead, 150 behind `v4-on-main`). Appliance `main` merges only from it, so before go-live
   `v4/headless` must be brought up to `v4-on-main` or shared changes never reach `main`. Put that step in the go-live checklist.
3. **The tunnel agent row** in the branch table (`v4/headless`) conflicts with the tunnel redesign already on `v4-on-main`.
   Move the row to the trunk (relay and agent code are shared) or restate what stays headless-only.
4. **Portal-ahead Nano edits** (logout/avatar/dismiss in the appbar and booster-link, Mesh widget, `clouds.html`) must be
   back-ported to `wasm/` before the next `--apply`. Run `python3 wasm/vendor_to_portal.py --check` first; classify each drifted
   file as mine / another session's / unclear.
5. **Push rule (rule 9) vs an earlier instruction to push after every batch.** Pick one; suggested: topic branches may be pushed
   at any time (no loss), the trunk and the lines only through the integrator, `main` and tags only on the owner's go.
6. **Branch hygiene:** 487 remote branches in the appliance repo; 310 are fully merged into `v4-on-main`; 176 carry unique
   commits (mostly old `release/v1.x`). Tag the 176 to archive them, then delete the merged ones, only on the owner's go.

## 7. Open points (to be confirmed by the owner)

- Where a Nano change first lands: this doc says the trunk (then vendored to the portal). Portal-first is what lets `--apply` overwrite portal edits, so the trunk-first answer is recommended.
- `v4/headless` is reused as the headless line instead of a new `v4-headless-appliance`; `v4-appliance-on-main` is dropped as
  redundant with the trunk.
- The tunnel redesign already on `v4-on-main` (stream framework, DNS-only agent resolver) supersedes the earlier
  `host`/`k3s` reserved-target branches; they are reconciled separately.
