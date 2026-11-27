# Branch baseline, 2026-11-27

Trunk = `origin/v4-on-main` @ b660a6238. Goal: no branch left "awaiting"; each is merged to trunk or archived.
Method: `git cherry` (patch-equivalence), feature grep on trunk, `git merge-tree` conflict probe, age.
Archive = tag `archive/<branch>` at the tip, then delete the remote branch (recoverable from the tag).

## A. Already on trunk (patch-equivalent, 0 unique commits) -> ARCHIVE (16)
ami-launch-store, aws-iam-member-shape, aws-nightly-checks, aws-nightly-testbed, credentials-own-page,
fix-408-nano-ui, mcp-claims-cleanup, mcp-guardrails, mesh-drawer-default-open, nav-behind-dock,
release-checks-total, suites-retarget-gcp, terraform-aws-readbacks, tf-azure-complete,
tunnel-claims-cleanup, untrack-claude-lock

## B. Same content already on trunk under different SHAs -> ARCHIVE (9)
- k8s-full, gap-close, gap-A1, gap-A4, gap-A23: AKS backup, RealK8sBackend, APIM capacity and the App Service Database tab are all on trunk.
- terraform-studio, terraform-faithful-export, terraform-throttle-4010: Infrastructure Studio (`tfstudio/Studio.jsx`) is on trunk.
- mesh-tab-same-size: superseded by 2b3aa18f3 on trunk.

## C. MERGE to trunk
| Branch | Why | Notes |
|---|---|---|
| release-fixes-all (+ release-fixes-4-1-2, release-fix-sns/az-gcp/aws-ui) | 16 of 18 v4.1.1 CI failures | clean, 0 behind |
| tunnel-1-4-1 | tunnel 1.4.1 + plugin 4.3.2 (trunk is 1.4.0) | clean, 0 behind |
| cloudshell-capacity | cloudshell host profile + /mesh/capacity | clean, active session |
| nano-image-catalog | image catalog (WIP commits) | clean; owner session must finish (wip) |
| usage-install-id | iid on usage events (not on trunk) | conflicts: rebuild consoles |
| cloudpick-wait-for-plan | 1-file fix | clean |
| dock-mobile-fit, mesh-drawer-aws-align | phone dock + AWS drawer width | conflict only in built wasm/v4: regenerate |
| mcp-via-tunnel-only | MCP only inside tunnel (standalone vyomi-mcp absent on trunk) | clean; check release.yml |
| validate-results, vyomi-cloud-privacy-url | directory submission docs/plugin | review versus 4.3.2 first |
| ai-enterprise-reference-plan, labs-nano-matrix-aws, labs-nano-matrix-gcp-azure | docs only | clean |

## D. ARCHIVE (superseded or stale, never reached trunk)
- tunnel-release-hardening (1.3.2), mcp-codespace-followups (1.3.1), mcp-followups-3 (1.3.3): tunnel is 1.4.x on trunk. First diff for CI/test additions worth cherry-picking.
- guardrail-no-legacy-views: only rule 12 text not on trunk -> cherry-pick the doc line, archive the rest.
- ai-probe-baseline, ai-sdk-probe: probe tools; ai-sdk-probe is a subset of ai-probe-baseline. Archive after reading the 37.7% baseline into the AI plan.
- spike-nano-vm-images: spike report; archive.
- ci-bidi-daily, ci-eod-release: workflows absent from trunk; decide: adopt or drop.
- aws-validation (real AWS error code on invalid input), aws-field-roundtrip, azure-nightly-fixes (WIP): 1000+ behind, conflicts -> re-do on trunk if wanted; archive.
- ui-aws-sqs, ui-azure-apim, ui-azure-appservices, ui-azure-subscriptions, ui-azure-vms: runner output, 2700-3200 behind, 100+ files each -> archive.
