# v4/gcp-roundtrip-fix

Release checks run 45675991383: `nano-ui (gcp)` failed only on `nightly-gcp-roundtrip` (0/1 after 180s).
Cause: it boots the legacy `/gcp-console.html`, deleted in 253ebd8ce (rule 12), so the page never loads.
Decision: mark the suite `pending` in tests/conformance/hourly/suites.json (same reason text as other legacy suites).
Its v4 replacement `nightly-gcp-v4-roundtrip` passes 93/93.
