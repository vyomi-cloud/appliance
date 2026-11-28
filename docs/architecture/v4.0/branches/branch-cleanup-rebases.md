# branch-cleanup-rebases
Ports three stale branches onto trunk (dock-mobile-fit, mesh-drawer-aws-align, usage-install-id) and rule 12 from guardrail-no-legacy-views. Built outputs regenerated, not hand-merged (rule 6).
Open: usage-install-id's edits to the dead legacy `wasm/*-console.html` were NOT ported (rule 12); the v4 pages load nano-usage.js, so the iid change is live there.
