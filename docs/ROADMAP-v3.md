# Vyomi — Release 3.0 Roadmap: "From runtime to platform"

> Status: **active** · Owner: portal+appliance · Supersedes ad-hoc tier work in v2.2.x
> Single release (**3.0**), delivered in **three phases**. Phase completions may tag
> `3.0.0 → 3.0.1 → 3.0.2`, but the release identity stays **3.0**; full 3.0 GA = end of Phase 3.

## Why 3.0
v2.2.2 is a **single-developer local runtime** with all-3-cloud fidelity, Docker/VM
compute, Terraform, IAM, and a ~70%-built in-browser core (Nano/WASM). **3.0 is the
release where Vyomi becomes multi-user and segment-aware** — free in the browser,
managed for cohorts, on-prem for enterprise. ~60% of the capability already ships; the
net-new center of gravity is a **multi-user control plane + content**.

## The two axes
**Solutions (the *what*)** — a flat, capability-named set (firstshift-style), one flagship:
- ⭐ **Multi-Cloud Digital Twin** (flagship / platform)
1. **Local Cloud Development** — real cloud APIs on localhost, unmodified SDKs/CLIs/Terraform
2. **Cross-Cloud Portability** — the same workload across AWS, GCP, Azure
3. **Offline & Air-Gapped Cloud** — a full cloud with no account, bill, or network
4. **Cloud CI Testing** — ephemeral cloud twin for real integration tests in CI
5. **IAM & Policy Testing** — validate IAM/Cedar authorization locally
6. **Infrastructure-as-Code** — develop Terraform against the twin, export/promote to prod
7. **In-Browser Cloud (Nano)** — the whole simulator in a browser tab, zero install

**Segments (the *who*)** — our "Industries" equivalent (horizontal product → segment by buyer):
- **Universities** · **Developers** · **Enterprises** · **Trainers**
- Enterprises carries three **role lenses** (one offer, three narratives):
  **DevOps/Platform** · **Architects** · **Engineering**

### Solutions × Segments (leads-with map)
`●● leads · ● supporting · ○ situational · – n/a`

| Solution | Universities | Developers | Enterprises | Trainers |
|---|:--:|:--:|:--:|:--:|
| Local Cloud Development | ○ | ●● | ●● | ○ |
| Cross-Cloud Portability | ○ | ● | ●● | – |
| Offline & Air-Gapped | ● | ○ | ●● | ● |
| Cloud CI Testing | ○ | ●● | ●● | – |
| IAM & Policy Testing | ○ | ○ | ● | ○ |
| Infrastructure-as-Code | ○ | ● | ●● | – |
| In-Browser Cloud (Nano) | ●● | ●● | ○ | ●● |

## Decisions locked (defaults; adjust later)
- **Nav:** primary tabs = the 4 segments + a **Solutions** mega-menu →
  `Logo · Solutions ▾ · Universities · Developers · Enterprises · Trainers · Pricing · Resources ▾ · Get started →`
  (honors the original "4 audience tabs" ask + adds firstshift-style Solutions).
- **Currency: USD ($)**, replacing INR (₹).
- **Pricing (starting points):** Developers **$0 / $9 / $19 / $29** (Free/Lite/Pro/Max);
  Enterprise **~$12/dev/mo, min 10**; Trainers **~$39/mo**; Universities **custom / site license**.
- **Payments:** keep Razorpay for India; add a global processor (Stripe / MoR) for USD.
  Razorpay *can* charge USD (100+ currencies) but settles INR (~5% all-in) unless EEFC;
  it's an add-on requiring underwriting. → `PAYMENT_PROVIDER` already abstracts this.
- **URL structure:**
  ```
  /solutions, /solutions/<slug> (7)
  /universities  /developers  /enterprises (+/devops /architects /engineering)  /trainers
  /pricing   Resources ▸ /docs /downloads /blog   /about
  ```

## Phases

### 3.0 · Phase 1 — Repackage + the free wedge goes live
Ships: portal nav (Solutions/Segments) + 4 segment landing pages + 7 solution pages ·
**$ pricing + new SKUs + payment abstraction** · **Nano hosted** (deploy relay,
multi-tenant, session persistence) · Developer self-serve onboarding ·
**Ephemeral/CI profile + GitHub Action** · IaC round-trip polish.
Unlocks: **Developers (paid, $)** · **Free (Nano)**.
GA cut line for a credible "3.0 launch": Nano hosted + $ pricing/SKUs + Solutions/Segments
site + Developer self-serve.

### 3.0 · Phase 2 — Cohorts (the multi-user control plane)
Ships: **Cohort Control Plane** (instructor/trainer dashboard, rosters, per-seat Nano
orchestration, shareable lab links, reset-between-sessions, monitoring) ·
**Content: labs/scenarios/courseware** · LMS/SSO + academic SKU.
Unlocks: **Universities · Trainers** (shared plane; only dashboards + SKUs differ).
Depends on: Phase-1 Nano-hosted being stable.

### 3.0 · Phase 3 — Enterprise at scale
Ships: **Config-as-code golden environments** + seed data · **Air-gapped + offline
license/activation** · **Cost & parity dashboards** · Enterprise role lenses (DevOps/
Architects/Engineering) + SSO/RBAC/audit polish.
Unlocks: **Enterprises** (all three role narratives).
Watch: **offline license** is the sneaky-hard item (today licensing phones the portal ~daily).

## Workstream → phase
| # | Workstream | Phase | Reuse vs new |
|---|---|---|---|
| Portal: nav + pages + $ + SKUs | P1 | new (portal) |
| 2 | Nano productization (deploy relay, host, persist) | P1 | ~70% built → finish + deploy |
| 3 | Ephemeral / CI profile + Action | P1 | new |
| 8 | IaC round-trip (import + plan/apply) | P1 | polish |
| 1 | Cohort Control Plane | P2 | **new (big build)** |
| 5 | Content: labs / courseware | P2 | new (content) |
| 6 | Config-as-code environments | P3 | new |
| 4 | Air-gapped + offline license | P3 | new (offline activation = hard) |
| 7 | Cost & parity dashboards | P3 | new |

## External blockers (need real resources — scaffolded until provided)
- **Payment**: Stripe/Razorpay-international API keys + business underwriting.
- **Nano hosting**: deploy `relay.vyomi.cloud` (domain + infra) + hosted multi-tenant runner.
- **CI**: publish the GitHub Action to the Marketplace (org + secrets).
- **Universities**: LMS/SSO app registrations (per-institution).
These are stubbed in code with clear `TODO(3.0)` markers; no fabricated integrations.

## Coordination
Multiple Claude sessions share this checkout. Per project rule: **no self-commits, never
`git add -A`, don't edit other sessions' files.** 3.0 portal work lives in the portal repo
(`../portal`); appliance work is additive. Nano/WASM is owned by a parallel session — this
roadmap consumes its output, does not modify `wasm/`.
