# v4 — branch architecture

Status: 2026-11-09, ONE version (v4 of this document; earlier drafts are summarised in the appendix). This is the rule every
session (human or agent) follows for v4 work. Anything not in sections 1 to 5 is not a rule.

## 1. Primary rule

**`v4-on-main` (appliance repo) is the shared trunk and the source of truth for all v4 work.**
Every new branch is created from `origin/v4-on-main`. `release/v4.0.0-dev` is superseded (the trunk contains it and is ~800
commits ahead) and takes no new work.

## 2. Structure

```
APPLIANCE   v4/<topic> (pushed at once) --PR--> v4-on-main --freeze--> release/v4.0.0 --owner go--> main (tag v4.0.0)
                                                  |  headless-smoke (nightly + before the release cut and go-live)
                                                  `- vendor_to_portal.py --apply (records the source SHA)
PORTAL      portal/<topic> (pushed at once) --PR--> v4-nano-portal --owner go, once--> main (paid deploy)
SANDBOX     vyomi-cloud/sandbox (Codespace image): main only, by PR; the appliance pins the image tag
```

| Branch | Repo | Role | Takes |
|---|---|---|---|
| `v4/<topic>` | appliance | one per session and topic, from a fresh trunk | any change; lives at most 3 days, rebased daily |
| `v4-on-main` | appliance | the trunk | shared cores, consoles, registry, headless code (k3s runtime, booster image, tunnel and relay), the `wasm/` Nano bundle, tests, docs |
| `release/v4.0.0` | appliance | the release cut | version bump, changelog, release checks, fixes only. The branch already exists on origin and holds commits the trunk lacks: reconcile it with the trunk before the freeze instead of cutting a new one. Nobody pushes to it outside this flow. |
| `main` | appliance | go-live | merges from `release/v4.0.0` on the owner's go; the owner tags `v4.0.0` (the tag builds the images); then `main` merges back into the trunk so `VERSION` matches |
| `portal/<topic>` | portal | one per session and topic | portal-only code: pages, endpoints, Mesh login, keep-alive, VM-name reservation, key injection, runner dispatch, tier-to-licence mapping |
| `v4-nano-portal` | portal | the portal trunk | `portal/<topic>` merges and vendor PRs |
| `main` | portal | go-live | merges from `v4-nano-portal` once, on the owner's go (a push auto-deploys and costs money) |

### 2.1 Decisions that shape it

1. **Nothing is ever lost: topic branches are pushed at once and kept.** Every session pushes its topic branch as soon as it has a
   commit (`git push -u origin v4/<topic>`) under its own name, and again after every batch. Pushing a topic branch needs no
   approval. What needs the owner or the integrator is only: the trunk, `release/v4.0.0`, `main`, tags. A branch is deleted only
   after it is merged into the trunk AND its tip is tagged `archive/<branch>-<date>` on origin.
2. **No long-lived `v4/headless` branch.** It carried nothing the trunk lacked and only added a merge hop. Headless-only code is
   isolated by path (`codespace/`, `packaging/`, `wasm/relay/`, the k3s runtime) and checked by a defined gate (2.2).
3. **The portal receives two kinds of change only.** Portal-only code on `portal/<topic>`; and the Nano bundle, only through a
   vendor PR: `python3 wasm/vendor_to_portal.py --apply` from a named appliance SHA, which writes that SHA to
   `app/nano/.vendored-from`. CI fails any other PR that touches `app/nano/**`. This removes the "portal edit overwritten by the
   next `--apply`" failure. Existing portal-ahead edits are back-ported to `wasm/` first (section 6, row P1).
4. **A run-only worktree for local testing.** `scripts/v4-run-local.sh` builds `portal-run` from the current `v4-nano-portal` plus
   a vendor of the trunk's latest `wasm/` and serves `:8099`. Nobody edits it, so local tests always show both sides' latest
   features (a shared, hand-edited checkout is why features go missing).
5. **One named integrator.** The owner names one integrator (a person or one session) who merges topic branches into the trunk and
   `release/v4.0.0`. Until named, the owner is the integrator. Topic-branch authors never merge to the trunk themselves.
6. **Naming.** Appliance topics `v4/<topic>`, portal topics `portal/<topic>`. Old `v4/ng*`, `v4/ns*` and similar branches are
   archived (tagged) and deleted once merged.

### 2.2 Headless gate (`headless-smoke`)

A CI job, and the same script locally (`scripts/v4-headless-smoke.sh`), that builds the booster image from the trunk and runs the real
Docker stack: core conformance, the live k3s tests (`VYOMI_LIVE_K3S=1 tests/conformance/test_k3s_live.py`,
`test_k3s_platform_live.py`, `test_aws_eks_live.py`) and the relay tests. It needs a quiet machine: the shared Docker VM is
saturated by parallel sessions and live k3s tests then time out.

- **Every merge to the trunk (fast preflight):** relay tests (`test-booster-link`, `test-booster-shell`,
  `test-booster-session-derived`, `test-mesh-ssh`), core conformance, `vendor_to_portal.py` (check-only; the script has no `--check` flag, `--apply` copies), and the substrate tests for the
  paths touched.
- **Full `headless-smoke` (image + live k3s):** nightly, before the release cut, and before go-live. It must be green for both.
- The live k3s tests live on branches not yet ported to the trunk, so the full gate exists only once those land.

### 2.3 Go-live sequence

1. Freeze: no new merges to the trunk; the claims file is cleared or marked.
2. Vendor sync into `v4-nano-portal`; `--check` shows zero drift; test on `:8099` via `portal-run`.
3. Reconcile and update `release/v4.0.0` from the trunk; bump `VERSION`; changelog and notes; run `release-checks` and the full `headless-smoke`.
4. Owner go: merge `release/v4.0.0` into appliance `main`; the owner tags `v4.0.0`.
5. If the Codespace devcontainer changed, update `vyomi-cloud/sandbox` and pin the tag.
6. Owner go: merge `v4-nano-portal` into portal `main` once (a single paid deploy).
7. Smoke test; merge `main` back into the trunk.

## 3. Rules

1. **Branch from the trunk.** `git fetch`; `git worktree add ../appliance-<topic> -b v4/<topic> origin/v4-on-main` (portal:
   `../portal-<topic>`, `-b portal/<topic>`, `origin/v4-nano-portal`). Before building a gap, grep `origin/v4-on-main` for it: other
   sessions may have landed it already.
2. **Shared files change only on the trunk.** `core/*.py`, `consoles/src/**`, `core/capabilities/**`, the Nano core lists and the
   `wasm/` bundle are never hand-edited on `v4-nano-portal`. If a Nano or headless need changes shared code, land it on
   `v4-on-main` first.
3. **Merges flow one way:** topic branch into the trunk; the trunk into `release/v4.0.0`; the trunk's `wasm/` into `v4-nano-portal`
   through a vendor PR. Nothing flows back except through the trunk.
4. **Substrate-only code** stays in its own paths (headless) or its own branches (`portal/<topic>`).
5. **Test each line in its own substrate** before it moves on: Nano on the localhost portal (`:8099`, `.env` loaded) with the
   service worker and Pyodide; headless on the real Docker stack. A dev server is not a substitute for a container-backed feature.
6. **Built outputs are never merged by hand.** `wasm/v4`, `static/v4` and the vendored `wasm/core` copies are regenerated
   (`cd consoles && node build.mjs`, `python3 wasm/build_cores.py`) after a source merge.
7. **Nothing reaches `main`, a tag, a release or a deploy** until the owner says the release is ready to go live.
8. **Commit hygiene.** Explicit `git add <paths>`, never `git add -A`; never touch another session's worktree or branch; never use
   bare `git stash`.
9. **Pushing.** Topic branches: push at once and after every batch, no approval. The trunk and `release/v4.0.0`: the integrator
   only. Never force-push any shared branch. `main` and tags: the owner's go only.
10. **A branch cut from a stale base is ported, not merged:** re-apply its intent onto a fresh topic branch from the trunk
    (cherry-pick by file, rebuild the outputs). A merge pulls in old release-prep commits.
11. **Every topic branch carries a branch document.** `scripts/v4-session-start.sh` creates it from a template:
    appliance `docs/architecture/v4.0/branches/<topic>.md`, portal `docs/branches/<topic>.md`. It records the **architecture**
    (what is built and where), the **design decisions** (what was chosen, the alternatives rejected and why) and the **open issues**
    (what is unfinished, unverified or deferred, with an owner). Commit it with the first push, update it with every batch, and
    have it complete before the branch is merged. It is merged with the branch and kept after the branch is deleted, so the reasoning
    survives; the integrator does not merge a branch whose document is missing or still the empty template. The pre-push hook warns
    on a topic branch that has no document.

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
| 2 | **Tag rule** for `v*` so only the owner creates release tags. `archive/*` tags are NOT protected: sessions create them when archiving a merged branch | Hard | Owner |
| 3 | **Repo `CLAUDE.md`** (built 2026-11-09) at the root of both repos (on `v4-on-main` and `v4-nano-portal`) stating the flow, "branch from fresh `origin/v4-on-main`", the claims file, no `git add -A`, no bare `git stash` | Every session in any worktree of the repo loads it | Builder session |
| 4 | **User-level `~/.claude/CLAUDE.md`** with a short pointer to this doc, for sessions started in other folders | Soft | Builder session |
| 5 | **Claude Code hooks** (built: `.claude/settings.json` + `scripts/claude-hooks/v4-guard.py`) in the repo's `.claude/settings.json`: block `git push origin main`, force-push, tag pushes, `git add -A`, bare `git stash` | Automatic for Claude sessions only | Builder session |
| 6 | **Committed git hooks** (`.githooks/pre-push`, enabled per clone by `scripts/v4-install-hooks.sh`): topic branches are NEVER blocked (a stale base only prints a warning, so work is never lost); `main`/`master` and tags (except `archive/*`) are refused; `v4-on-main`, `release/v4.0.0` and `v4-nano-portal` are refused unless `VYOMI_INTEGRATOR=1`, and then must fast-forward and (with `WS_PKG` set) pass the relay tests (`test-booster-link`, `test-booster-shell`, `test-booster-session-derived`, `test-mesh-ssh`) | Covers humans too; each clone opts in | Built (2026-11-09) |
| 7 | **`scripts/v4-session-start.sh <topic>`** (built): `git fetch`, creates `../appliance-<topic>` off `origin/v4-on-main` (or the portal equivalent off `origin/v4-nano-portal`), appends the claim | Convenience; makes the right thing the easy thing | Builder session |
| 8 | **CI drift check**: `vendor_to_portal.py` (check-only; the script has no `--check` flag, `--apply` copies) fails the build when the portal copy differs from `wasm/` | Hard for Nano drift | Builder session |

Minimum set: 1, 3, 5, 6. Only layer 1 cannot be bypassed.

### 5.2 Claims file

`docs/architecture/v4.0/SESSION-CLAIMS.md` on `v4-on-main` (created 2026-11-09, seeded with the active sessions): one row per active topic with session, branch, repo, paths claimed,
start date. Add the row before editing; remove it when the branch merges. Before editing a path outside your own claim, read the
file and ask the owner if it is claimed. Claims older than 7 days without a push are treated as stale.

### 5.3 Integrator

Sessions push topic branches. One integrator (the owner, or one designated session) merges topic branches into `v4-on-main`,
runs the preflight (6), then runs the vendor step into `v4-nano-portal`. Two sessions never push to the trunk at the same time.

### 5.4 Ownership map (single place each file is edited)

| Files | Edited only in | Reaches |
|---|---|---|
| `core/*.py`, `consoles/src/**`, `core/capabilities/**`, Nano core lists | `v4-on-main` | `release/v4.0.0` then `main`; portal via build + vendor |
| `wasm/**` Nano bundle (incl. `vm/`, `vyomi-appbar.js`, `booster-link.js`, `clouds.html`, relay/Worker, `egress.mjs`) | `v4-on-main` | portal `app/nano/**` via `vendor_to_portal.py --apply` |
| `packaging/tunnel/**`, `wasm/relay/mesh-cli.mjs`, relay hub/agent | `v4-on-main` | npm / Homebrew at release |
| Portal pages and endpoints (`app/*.py`, `app/templates/**`: Mesh login, keep-alive, OAuth setup, tier mapping) | `v4-nano-portal` | portal `main` at go-live |
| Codespace image (devcontainer, sshd feature, compose) | `vyomi-cloud/sandbox` | new Codespaces only |

### 5.5 Session checklist (copy to any session that is finishing or starting work)

**Finishing in-flight work**
1. `git fetch origin`; trunks are `origin/v4-on-main` (appliance) and `origin/v4-nano-portal` (portal).
2. Commit with explicit paths only (never `git add -A` / `.`; never a bare `git stash`, use a WIP commit).
   Update your branch document (rule 11): architecture, design decisions, open issues.
3. Push your topic branch now and after every batch: `git push -u origin v4/<topic>` (portal: `portal/<topic>`). No approval needed.
   Never force-push. If a rebase makes the push fail, push under a new name (`v4/<topic>-r2`).
4. Do NOT push `v4-on-main`, `release/v4.0.0`, `v4-nano-portal`, `main` or any tag (integrator / owner only; portal `main` auto-deploys and costs money).
5. Tell the owner your branch name and the shared files you touched (`core/*.py`, `consoles/src/**`, `core/capabilities/**`, `wasm/**`, `server.py`); the integrator ports or merges it.
6. A branch cut from an old base is ported, not merged: never merge the trunk into it, never hand-merge `wasm/v4`, `static/v4`, `wasm/core`
   (rebuild: `cd consoles && node build.mjs`, `python3 wasm/build_cores.py`).

**Starting new work**
1. `scripts/v4-session-start.sh <topic>` (portal: `--portal`) creates a worktree off a fresh trunk.
2. Add your row to `SESSION-CLAIMS.md` before editing shared paths.
   Fill in the branch document the script created (rule 11) and commit it with your first push.
3. Grep `origin/v4-on-main` for the gap first; another session may have landed it.

**Managed Kubernetes gate (landed 2026-11-09, `8424b286`)**
AKS / GKE / EKS are Pro / Max / Enterprise only (`core/k8s_tier_gate.py`). Nano runners and Playwright tests set
`localStorage.vyomi_ci_tier = "max"` via `addInitScript` (honoured on localhost / 127.0.0.1 only). Any test that touches AKS/GKE on Nano needs it.

### 5.6 Hand-off log (2026-11-09)

- **P1 Nano back-port: done and merged to the trunk** (`v4/p1-nano-backport`: `wasm/vyomi-appbar.js`, `wasm/booster-link.js`; details and defaults in `P1-NANO-BACKPORT.md`). Claim row removed.
- **Owner defaults accepted:** `booster-widget.js` stays portal-only; `APPLIANCE_SYNC.json` is the vendor marker (no `.vendored-from`).
- **Open (integrator):** scratch-portal browser check (step 6 of `P1-NANO-BACKPORT.md`), then the first vendor PR on `portal/vendor-<date>`, then the CI rule that fails portal PRs touching `app/nano/**` other than vendor PRs.
- **Open (owner):** GitHub branch protection + `v*` tag rule; name the integrator.

**Asks to the P1 / mesh-tunnel session (from the integrator, 2026-11-09):**
1. Confirm you have **no other unpushed or unmerged branches**; list any by name. This was the only one found.
2. `v4/p1-nano-backport` was applied to the trunk by cherry-pick (so git does not show it as merged). Delete the remote branch and your worktree
   `appliance-p1-nano-backport`: `git push origin --delete v4/p1-nano-backport` is allowed for your own topic branch.
3. Do **not** edit `app/nano/**` in the portal and do not touch `portal/vendor-20261109`; the integrator owns the vendor merge and the browser check (step 6 of `P1-NANO-BACKPORT.md`).
4. Fetch `origin/v4-on-main` (`d5b6a5a7` or later) before any new work; start new topics with `scripts/v4-session-start.sh <topic>`.
5. If your tunnel/mesh work continues, add a new claim row first and reconcile with the managed-Kubernetes tunnel branches (`v4/tunnel-keeper`, `v4/tunnel-k3s`) before changing `packaging/tunnel/**` or `wasm/relay/**`.

**Asks to every session that owns portal work (from the integrator, 2026-11-09):**
Portal state: `v4-nano-portal` = `3cb7de3` (33 ahead of portal `main`, 0 behind); portal `main` is untouched. Unpushed work is lost work.
1. **Commit and push your own uncommitted portal edits to a topic branch** (`portal/<topic>`, explicit paths only, no `git add -A`). Worktrees found dirty on 2026-11-09:
   `portal-OLD` (46 files, `feat/personal-sandbox-byo-pat`), `portal-rel45` (9, `local/v3.0.45-preview`), `portal` (4, `nano-sync/reconcile-v3.0.44`),
   `portal-v4nano` (20, shared checkout on `v4-nano-portal`). The owner of each pushes it; nobody commits another session's files.
2. **Stop using the shared `portal-v4nano` checkout for edits.** New portal work: `scripts/v4-session-start.sh <topic> --portal` (worktree off fresh `origin/v4-nano-portal`).
3. **Say whether your branch is still needed.** Unmerged branches with no clear owner: `enterprise/P1-sandbox-webhooks`, `feat/sandbox-open-gate`, `brand/landing-screenshots-v3036`,
   `feat/vyomi-asset-names`, `feature/issue-reporting`, `fix/nano-video-byte-ranges`, `fix/signin-google-linkedin`. Reply with merge-to-trunk / keep / delete.
4. **Old vendor and stale branches** (`nano-sync/*`, `nano/sync-*`, 5-month-old `fix/install-*`, `feat/install-per-os-commands`, `cleanup/drop-unsupported-pkg-formats`,
   `feat/founding-1000-and-tier-rename`): superseded by `portal/vendor-20261109`. The owner archives (`archive/*` tag) or deletes; the integrator does not.
5. **Do not edit `app/nano/**`** in the portal; Nano files arrive only through the vendor PR (`portal/vendor-20261109` is pending the browser check).
6. Integrator-owned (no action from others): the browser check, merging the vendor branch, splitting `portal/wip-snapshot-20261109`, the `app/nano/**` CI rule.

## 6. State of in-flight work (a dated snapshot, not a rule — refresh or delete when stale)

As of 2026-11-09. All branches are pushed under their own names; none of the appliance ones is merged into the trunk yet.

**Appliance repo** (all cut from the old `release/v4.0.0-dev`; each must be ported onto `origin/v4-on-main`, not merged as is)

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
| `v4/docs-branch-arch` | this doc | branch architecture | merge when the owner approves this document |
| `v4/merge-to-main` | in progress | the port itself | push when the agent finishes |

**Portal repo**

| Id | Branch / area | Contents | Status |
|---|---|---|---|
| P1 | Nano files edited in the portal: `app/nano/vyomi-appbar.js`, `booster-link.js`, `clouds.html` (and the Mesh widget) | logout, avatar, dismissible notices, Mesh widget; they differ from `wasm/` by roughly 200, 200 and 1000 lines | **Unprotected.** `vendor_to_portal.py --apply` would overwrite them. Before the first vendor PR: run `--check`, classify each drifted file (mine / another session's / unclear), back-port the portal-ahead edits to the trunk, then enable the `app/nano/**` CI rule. |
| P2 | `portal/wip-snapshot-20261109` | snapshot of the shared `portal-v4nano` working tree (Sandboxes grid, Git runners, Installation restyle, Mesh codespaces grid, plus other sessions' uncommitted edits) | **not for merge**; split per topic into `portal/<topic>` branches, then delete |
| P3 | `v4-nano-portal` | Mesh rename and GitHub-App routes, SSH keep-alive probe, OAuth setup page, browser-VM egress sync | pushed; portal `main` untouched |

## 7. Open decisions (owner)

- Approve this document; name the integrator (until named, the owner is the integrator).
- Apply GitHub branch protection and the `v*` tag rule (layers 1 and 2).
- Where a Nano change first lands: the trunk, then vendored to the portal (recommended; portal-first is what lets `--apply`
  overwrite portal edits).

## Appendix — history of this document

v1 (trunk + Nano and Headless lines with a long-lived `v4/headless`) → v2 (one trunk per repo, a release branch, vendor PR with
drift check, run-only worktree, claims file, enforcement layers, no `v4/headless`) → v3 (topic branches pushed at once and archived
by tag, `headless-smoke` as a gate instead of an empty branch, a named integrator, one document) → this version, which adds:
the fast preflight versus full `headless-smoke` split, `archive/*` tags exempt from the tag rule, the portal drift item (P1),
and removes the status SHAs and the resolved gap list.
