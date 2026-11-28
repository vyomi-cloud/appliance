# release-4.1.2

Cut from `origin/v4-on-main` (448981b1a, 2026-11-28) after the branch baseline: release-fixes-all, tunnel-1-4-1, cloudshell-capacity, cloudpick-wait-for-plan, mcp-via-tunnel-only, branch-cleanup-rebases and the validate-results / vyomi-cloud-privacy-url merges, plus the real-endpoint-urls and nano-image-catalog work other sessions had already landed.

## Open issues
- 16 of the 18 v4.1.1 release-check failures are fixed locally and not yet proven in CI; `nano-ui-azure-metrics` and `nightly-aws-v4-roundtrip` were not reproduced.
- Trunk carries `wip(nano)` image-catalog commits from another session; the Nano image catalog is phase 1 only.
- Release checks tests the released tag, so 4.1.2 is the first release those fixes can be proven on.
