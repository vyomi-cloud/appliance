# v4.0.0 — Native-fidelity consoles on real Vyomi backends

**Status:** proposal (awaiting sign-off) · **Scope:** appliance (offline + Codespaces sandbox) and Nano · **Date:** 2026-10-30

## 1. Goal

A developer who knows the AWS, GCP or Azure console can use the Vyomi console without
relearning anything: same navigation, same list columns, same detail tabs, same create
wizards. Every element is backed by a real Vyomi backend, or honestly marked
"not simulated". Nothing on screen is decorative.

## 2. What changes from v3

| | v3.x today | v4.0.0 |
|---|---|---|
| Console direction | `CONSOLE-UX-REDESIGN.md` §7 "recognizable, not cloned"; console-next as the cloud-agnostic shell | **Native-fidelity per-cloud consoles** as the primary UI; console-next's glass-box (inspector, conformance pill, connect card) becomes an **overlay** on them |
| Console source | 3 drifting copies: `static/*-console.html` (offline), `wasm/*-console.html` (Nano canonical), `portal/app/nano/…` (served) — 180–275 KB single files | **One source per cloud**, split into per-service modules, built once and emitted to all three targets |
| Look and feel | Hand-written CSS that approximates each cloud | Each cloud's **open-source design system**: AWS → Cloudscape (Apache-2.0), Azure → Fluent UI v9 (MIT), GCP → Material Web (Apache-2.0) + GCP tokens |
| Fidelity evidence | Manual review | **UI conformance suite**: every page is checked against a per-service UI spec extracted from the real consoles, in CI, with a published % (like API conformance) |
| Parallel work grain | Per cloud (one HTML per cloud → per-service edits conflict) | **Per service × cloud** (separate module files → conflict-free agent fan-out) |

Why this is a major version: it replaces all three consoles, changes console URLs/routes,
and reverses a documented v3 design tenet.

## 3. Architecture

```
                 PRIVATE                                   PUBLIC (this repo)
 ┌──────────────────────────────┐         ┌──────────────────────────────────────────────────┐
 │ vyomi-cloud/console-captures │ extract │ ui-spec/<cloud>/<service>.json                    │
 │ screenshots + DOM text       │────────▶│  nav tree · list columns · row actions ·          │
 │ (real account, never public) │  (text  │  detail tabs · create steps · form fields ·       │
 └──────────────────────────────┘  facts) │  validation · empty states                         │
                                          └───────────────┬──────────────────────────────────┘
                                                          │ contract
 ┌────────────────────────────────────────────────────────▼──────────────────────────────────┐
 │ consoles/<cloud>/                                                                         │
 │   shell/      top bar · service menu · region/project/subscription picker · side nav ·   │
 │               breadcrumbs · help panel · notifications · dark mode · glass-box overlay   │
 │   kit/        resource table · detail page + tabs · create wizard · split panel ·         │
 │               delete-confirm · tag editor · empty states   (design-system components)     │
 │   services/<service>/  list.jsx · detail.jsx · create.jsx · spec-map.json                 │
 │   api.js      ONE /api contract  ─────────────────────┐                                    │
 └───────────────────────────────────────────────────────┼───────────────────────────────────┘
                     build (esbuild, offline, no CDN)    │
        ┌──────────────────────┬─────────────────────────┼──────────────┐
        ▼                      ▼                         ▼              ▼
  static/ (offline)      wasm/ (Nano canonical)   portal/app/nano   sandbox (= offline image)
  FastAPI routes →       Service Worker → Pyodide cores → in-browser state
  real Docker backends
```

Key properties:

- **The `/api/<cloud>/…` contract is the seam.** The consoles already call the same paths on both
  substrates (`/api/aws/catalog`, `/api/s3/buckets/…`, `/api/cloudsim/events`, the generic
  `/api/{cloud}/sub/{service}/{op}` route). v4 formalises that contract per service, so one console
  build runs unchanged on the offline appliance, the sandbox and Nano.
- **The spec is text, not pictures.** Column names, tab names and field labels are factual UI
  descriptors, so the spec can be committed publicly. Screenshots stay in the private captures repo.
  Agents read both; only the spec and the code land in this repo.
- **Honest gaps.** When the spec has a field the backend can't do (for example S3 Object Lock),
  the console renders it with a "Not simulated in Vyomi" state, and the gap goes to the
  service-expansion backlog. A fake success is a conformance failure.
- **No trademarks.** No AWS/Google/Microsoft logos, service icons or product-name titles
  (today's `<title>AWS Management Console — Vyomi</title>` changes to "Vyomi · AWS lens").
  Layout and interaction follow the native consoles; branding is Vyomi.

## 4. Pipeline (capture → spec → build → verify)

1. **Capture** (done locally, re-run monthly): `console_captures/_tools/capture-*.mjs`. A read-only
   crawl with a network guard; masks the account ID, emails and GUIDs. Upload per service to the
   private repo as soon as that service finishes.
2. **Extract spec**: `tools/ui_spec_extract.py` turns each service's captures (`.txt` + DOM) into
   `ui-spec/<cloud>/<service>.json`. Deterministic parsing where possible; an LLM pass for the rest,
   followed by human review on the pilot services.
3. **Build** (GitHub runner, `console-ui-agent.yml`, `claude-code-action`): one job per
   service × cloud. Inputs: the spec, the private screenshots, the backend routes/cores. Output: the
   `services/<service>/` module plus backend wiring. Opens a PR into `release/v4.0.0-dev`, never
   `main`.
4. **Verify** (same job and again in CI):
   - **UI conformance**: Playwright loads the page and asserts that every spec element (column, tab,
     action, field) is present → per-service %.
   - **UI ↔ backend**: the existing `wasm/ui-tests` harness creates through the UI and reads back
     through the CLI/SDK (and the reverse), on Nano and on the offline appliance.
   - **Visual similarity** (advisory, private artifact): screenshot diff against the native capture.
   - The existing API conformance suite must stay green.

## 5. Phases and exit criteria

| Phase | Work | Exit criteria |
|---|---|---|
| **P0 Foundations** (serial, one owner) | Single-source build emitting to static/, wasm/, portal; per-cloud shell + kit; `/api` contract doc per service; spec extractor; UI conformance harness; private captures repo + uploader; `console-ui-agent.yml` | Shell renders on all 3 substrates; extractor produces specs for S3 + DynamoDB; harness runs in CI |
| **P1 Pilot** | AWS S3 + DynamoDB end to end: list, detail tabs, create wizard, delete, tags, on offline + Nano | ≥ 95 % UI conformance, UI↔CLI green on both substrates, agent cost per service measured |
| **P2 Fan-out** | Tier-A services: AWS 20, GCP ~16, Azure ~16; runner matrix, 4–6 in parallel | Every Tier-A service ≥ 90 % UI conformance, 0 fake states |
| **P3 Hardening** | Substrate parity (offline / sandbox / Nano); Nano bundle budget; dark mode, compact density, mobile, a11y; old-URL redirects; console-next folded into the overlay | Release-checks green on all substrates; Nano cold start within today's budget |
| **P4 Release** | RC builds, release notes, README, Nano bundle synced to the portal in the same release (one portal deploy) | `v4.0.0` tag on appliance; portal Nano sync merged; announcement |

The 3.0.x patch train (hourly conformance agent → daily PR → patch release) keeps running on
`main` throughout. v4 lives on `release/v4.0.0-dev` and is tagged by hand, since the automation
only cuts patch releases.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Native consoles change after capture | Monthly re-crawl; spec diff opens issues automatically |
| Trademark / trade-dress complaints | Open-source design systems only, no logos/icons/product titles, Vyomi branding, screenshots never published |
| Nano bundle size (React + design system in WASM tab) | Per-service lazy chunks; budget enforced in CI |
| Agent cost and quality at 50+ services | Pilot measures cost first; UI conformance + UI↔CLI gates reject self-reported success |
| Backend gaps exposed by the spec | "Not simulated" state + backlog to the service-expansion pipeline; never faked |
| Parallel sessions on one checkout | All v4 work on its own branch / worktree; agents never edit shared files outside P0 |

## 7. Decisions needed

1. Reverse the v3 "recognizable, not cloned" tenet in favour of native fidelity (layout and interaction; still no logos).
2. Adopt React + Cloudscape / Fluent UI / Material Web, prebuilt and served offline.
3. Create the private `vyomi-cloud/console-captures` repo.
4. Pilot on AWS S3 + DynamoDB before fanning out.
5. Integration branch `release/v4.0.0-dev`, tagged by hand.
