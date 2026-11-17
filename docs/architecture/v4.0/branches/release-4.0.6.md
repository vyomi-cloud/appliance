# release/v4.0.6

**Why:** fix the release checks that failed on every v4 release and the offline simulator gaps they exposed (DynamoDB console list, GCP DNS/Functions/SCC routing, Azure workbooks / Resource Graph / Defender / netenforce).

**Changes:** version bump, CHANGELOG and notes on top of trunk `v4-on-main` (d49a060ec), which already carries the fixes from `v4/fix-release-checks`.

**Not included:** Nano-side check fixes (azure-cognitiveservices, gcp-container, nano-ui-default-cloud).

**Open:** release-checks.yml must reach `main` for automatic runs (owner go).
