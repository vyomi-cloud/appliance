# Branch v4/suites-azure-landing

Landing branch for the Azure and AWS suite retargets: `v4/suites-retarget-azure` (b56929b85, fast-forward of the trunk 0b5f55c68) plus `v4/suites-retarget-aws` (0923dba40), merged. Only conflict: `SESSION-CLAIMS.md` (kept both rows; the diff3 base side was empty, markers removed by hand). Per-suite tables and run evidence: `suites-retarget-azure.md`, `suites-retarget-aws.md`.

Result: pending suites 106 -> 82 of 325 (AWS 10, Azure 14 now live, with GCP 13 earlier). Includes one source fix from the AWS work: `wasm/nano-boot.js` now writes the resource census on `/v4/<cloud>/` pages (Nano cost savings and host distribution never moved there).
