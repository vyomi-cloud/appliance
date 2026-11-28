# v4/guardrail-no-legacy-views

**Architecture:** documentation only. Adds rule 12 to `docs/architecture/v4.0/V4-BRANCH-ARCHITECTURE.md`: new features and UI changes go only into the v4 consoles on the trunk; the legacy single-file consoles are decommissioned and are never extended, demoed or linked.

**Design decisions:** a rule plus a three-point review checklist (touches `*-console.html`? owner URL under `/nano/v4/` or `/v4/`? change in `consoles/src` / shared chrome, not a hand-edited bundle?). Rejected: a CI gate that fails on any diff to the legacy files - the files still ship for the offline appliance's old routes, so a hard block needs an owner list of what may still be touched.

**Open issues:** (1) Infrastructure Studio (merged 2026-11-23, `wasm/tf-studio.js` + hooks in `wasm/aws-console.html`) lives in the dead view and has no v4 entry - re-home it in `consoles/src` under Management & Governance and remove the legacy hooks (owner: next terraform session). (2) Decide whether to add the CI gate above.
