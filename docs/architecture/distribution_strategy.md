# Vyomi Distribution Strategy

## Goal

Make Vyomi easy to install and operate on macOS, Linux, and Windows using one of three familiar patterns:
- package managers,
- `docker compose`,
- or OS-native installers.

The platform should feel like a product, not a hand-wired stack of host processes.

## Distribution Tiers

Vyomi ships as **five tiers** along two axes: three runtime **substrates**
(Multipass-LXD → Docker → WASM) × whether real **compute** is bundled (the
`+` suffix). They form a funnel: CloudNano (a URL, zero install) pulls users
in; CloudLite (`docker compose up`) converts developers; CloudMax serves
teams needing real compute.

| Tier | Substrate | API/SDK conformance pack | Compute (EC2) |
|------|-----------|--------------------------|---------------|
| **Vyomi-CloudMax** | Multipass VM | container (in-VM) | LXD — real VMs/containers |
| **Vyomi-CloudLite+** | host Docker | container | Docker (`docker run` = an instance) |
| **Vyomi-CloudLite** | host Docker | container | — none |
| **Vyomi-CloudNano+** | WASM (browser) | WASM / in-memory | CheerpJ (Java) · Pyodide (Python) · TinyGo (Go), in-tab |
| **Vyomi-CloudNano** | WASM (browser) | WASM / in-memory | — none |

Naming note: the in-browser tier (previously "Vyomi Lite") is **CloudNano**;
"Lite" now denotes the **Docker** tier.

### System requirements (proposed)

| Tier | RAM (rec / min) | CPU | Free disk | Virtualization? | Prereqs | First-run download |
|------|-----------------|-----|-----------|-----------------|---------|--------------------|
| **CloudMax** | **16 GB** / 8 GB ⚠️ | 4 / 2 | ~40 GB | **Required** — VT-x/AMD-V + Hyper-V (Win Pro) or VirtualBox | Multipass + a hypervisor | ~3–4 GB |
| **CloudLite+** | 8 GB / 6 GB | 4 / 2 | ~20 GB | Win/Mac: yes (Docker Desktop→WSL2); **Linux: no** | Docker | ~2–3 GB |
| **CloudLite** | 8 GB / 4 GB | 2 / 2 | ~15 GB | same as Lite+ | Docker | ~1.5–2 GB (lazy-pull cuts this) |
| **CloudNano+** | 8 GB / 4 GB | 2 | <1 GB | **None** | A modern browser | ~150–300 MB (WASM runtimes) |
| **CloudNano** | 4 GB / 2 GB | any | <500 MB | **None** | A modern browser | ~50–150 MB |

Notes / confidence:
- **CloudMax — 16 GB recommended, 8 GB is the degraded edge.** Validated
  2026-06-22: an 8 GB Windows 10 Home laptop **froze** during the image pull
  because the auto-sizer handed the VM 4 GB, starving the host. Two fixes
  this exposed: (1) cap the VM share on ≤8 GB hosts; (2) Wave-1-fast + lazy
  backend pulls to flatten the peak. Confidence: **high** (real failure data).
- **CloudLite** drops the nested VM + LXD (same backend containers, one
  virtualization layer not two) — which is why it fits an 8 GB box.
  Confidence: **medium** (measure once packaged).
- **CloudNano** is the only tier that runs with **no install, no admin, no
  BIOS** — Chromebooks, 4 GB machines, locked-down corporate laptops.
  Confidence: **estimated** (unbuilt; depends on final WASM runtime sizes).

## ADR-001: Single codebase, tier-as-build-profile

**Status:** Accepted (2026-06-23)

**Context.** Five tiers (above) invite a tempting mistake: forking into
separate codebases per tier. But Vyomi's entire value proposition is
native-SDK conformance — *the same SDK code passes the same tests on every
tier*. Separate cores would drift, a green light on one tier would say
nothing about another, and every bug fix / new service would land five
times.

**Decision.** **One codebase.** Tiers are produced by build profiles plus a
runtime compute flag — never by forking.

> **1 codebase → 3 build targets (Max / Lite / Nano substrates) → 5 tiers
> (compute flag on/off).**

**Mechanism.**
- **Across substrates (Max / Lite / Nano) → build profile.** These are
  genuinely different runtime targets (a Linux VM, a host-Docker stack, a
  WASM browser bundle); you cannot ship one artifact that is all three. Each
  substrate is a build target that packages the same core and bundles only
  that tier's seam implementations.
- **The `+` (compute on/off) → runtime flag.** Lite and Lite+ are the *same*
  artifact with the compute backend enabled/disabled by config; likewise
  Nano and Nano+. So three builds yield five tiers.
- **One shared conformance pack** — the simulator/handlers (cloud-API logic)
  are a single implementation, identical across all tiers.
- **Two seams carry all variation:** `ComputeBackend` (LXD / Docker /
  browser-runtime) and `BackendProvider` (real container / WASM-in-memory).
  Tier-specific code lives **only** in these adapters; the core never imports
  a tier.

**Invariants (CI-enforced).**
1. **WASM-clean core.** The shared core must compile/run in WASM (Pyodide).
   Native/heavy dependencies (real Postgres, LXD, etc.) live behind the
   seams, never in the core. *This is the rule that stops CloudNano becoming
   an accidental fork* — if native deps leak into the core, Nano is forced
   into a parallel implementation.
2. **Conformance parity.** The same native-SDK conformance suite runs on
   every tier. A backend with no implementation in a given substrate is
   marked *unsupported there* — never reported as a false green.
3. **No tier imports in the core.** A CI grep-gate asserts that core modules
   never reference tier-specific adapters.

**Consequences.**
- (+) A fix lands once; conformance is comparable across tiers; the funnel
  (Nano → Lite → Max) behaves consistently; five tiers from three builds.
- (−) The seams demand discipline, and the WASM-clean invariant constrains
  the core's library choices (push native concerns into adapters).
- (−) Three build targets + per-tier CI to maintain.

**Rejected alternative — separate codebase per tier.** 5× maintenance and
drift; breaks conformance integrity (the core value prop); guarantees funnel
inconsistency. Not viable.

## ADR-002: Packs as composable modules

**Status:** Accepted — roadmap (Core Pack ships first) (2026-06-23)

**Context.** Beyond the runtime tiers, Vyomi will offer vertical capability
**Packs** — domain bundles of cloud service families plus an optional real
backing engine:
- **Core Pack** — the base cloud APIs (what ADR-001 calls "the conformance pack").
- **AI Pack** — Bedrock / Vertex AI / Azure AI, backed privately by **Ollama** (and WebLLM in the browser).
- **IoT Pack**, **Security / Identity / Compliance Pack**, **ML Pack**, …

This adds a second product axis — **Pack × Tier** — which could explode into
dozens of hand-built SKUs and tempt a fork per pack.

**Decision.** Packs are **composable modules**, never pre-built bundles or
forks. A pack = {service-family conformance handlers} + {an optional real
backing engine}. Users pick a **tier** and **enable packs**; the
build/runtime assembles the combination. **Compose, don't pre-build.**

**Mechanism.**
- A pack's **real engine** (Ollama for AI, a device sim for IoT, a policy
  engine for Security) is just another **`BackendProvider`**. The
  `+`/Max-vs-Lite split repeats inside every pack with the same meaning:
  engine on (`+`/Max) vs API/SDK conformance only (Lite).
- A pack's **handlers** (e.g. the Bedrock/Vertex/Azure-AI SDK surface) are
  **service-family modules** registered onto the core, not hard-wired.
- **Pack selection is a build/runtime flag** — the natural extension of
  ADR-001's "compute = a runtime flag." One artifact per tier; packs toggle
  in. No per-combination artifact.

**WASM parallel.** Even AI has a zero-install tier: **AI-Pack-Nano+** runs
in-browser inference via **WebLLM / transformers.js** (the AI analog of
CheerpJ/Pyodide for compute); **AI-Pack-Nano** validates SDK shape only.

**Invariants (extend ADR-001).**
1. **Conformance per pack, per tier.** Each pack proves its native cloud SDKs
   (Bedrock/Vertex/Azure-AI, …) as-is; the backing engine (Ollama/WebLLM) is
   our private pick, never surfaced. A pack/tier combo with no engine
   implementation is marked *unsupported*, never reported green.
2. **Packs are additive, not invasive.** A pack registers handlers + an
   optional `BackendProvider`; it must not modify the core or other packs.
   CI gate: removing a pack leaves the rest building and passing.
3. **WASM-clean still applies** to any pack targeting Nano — its handlers
   must be Pyodide-portable; its engine (if any) is an in-browser WASM runtime.

**System-requirements impact.** Requirements become **tier baseline + pack
overhead.** Real engines are heavy — Ollama + a 7B model ≈ **+5–8 GB RAM and
several GB disk** — so AI-Pack-Max realistically wants 24–32 GB while
AI-Pack-Nano needs almost nothing. The requirements table gains a per-pack
adder.

**Rollout (roadmap).** Core Pack ships first (it is the current product).
Then AI Pack (Ollama / WebLLM), then IoT / Security-Identity-Compliance / ML —
order driven by demand and engine maturity.

**Consequences.**
- (+) New domains = new modules, not new repos or SKUs; the matrix scales by
  composition.
- (+) Conformance integrity extends cleanly to every pack.
- (−) Requires a real pack-registration/module system + a per-pack conformance suite.
- (−) Combinatorial test surface (pack × tier × cloud) — mitigated by
  composition + per-pack CI, not exhaustive bundle builds.

**Rejected alternatives.**
- *Pre-built bundle per Pack×Tier combination* — dozens of artifacts to
  build and maintain; drift. No.
- *A fork/repo per pack* — same conformance-integrity and maintenance failure
  as ADR-001's rejected forking. No.

---

> The sections below describe the **CloudMax** tier specifically (its
> Multipass launcher, packaging, and runtime layout). CloudLite reuses the
> same core via the repo's host `docker-compose.yml`; CloudNano runs that
> core in Pyodide (see `docs/browser-lite/`).

## Recommended Shape

The cleanest operational model is:

1. The host installs a small launcher and Multipass.
2. The launcher creates one durable Multipass VM appliance.
3. The VM runs the full Vyomi runtime.
4. The host only starts, stops, and updates the appliance.

This gives us:
- one installation story,
- one restart boundary,
- and one place where the durable simulation state lives.

## Single Launcher

Vyomi now has one launcher path:

```bash
bash ./scripts/cloud-learn up
```

or on Windows:

```powershell
.\scripts\cloud-learn.ps1 up
```

The launcher starts one durable Multipass VM appliance and then starts the full Vyomi runtime inside that VM from `docker-compose.appliance.yml`.

## Packaging

The packaging targets are wrappers around the same launcher:
- Homebrew
- Snap
- MSI / winget

They all bring up the same appliance boundary and should not reintroduce a separate developer runtime path.

What runs inside the VM:
- simulator UI/API
- CloudSim backbone
- provider emulators
- VM-local runtime bridge
- persistent state
- EC2-like sandboxes backed by LXD

Why:
- the VM becomes the durable boundary,
- host restarts are much less disruptive,
- and the platform no longer depends on host-native runtime wiring after startup.

## What Should Live Where

### Host

Keep the host thin:
- launcher
- VM lifecycle management
- optional port forwarding or SSH tunnel
- package-manager integration

Do not keep the business logic on the host.

### Inside the VM

Keep the runtime self-contained:
- simulator
- CloudSim
- providers
- sandbox runtime
- deployment workspaces
- persistent state

## What To Use For Runtime Orchestration

Recommended:
- `docker compose` inside the VM for the simulator stack
- or `systemd` if you want tighter OS integration

Avoid:
- Multipass inside Multipass
- laptop-side runtime bridges as a long-term dependency

## User Experience

The target UX should be:

1. Install once.
2. Start one command or one app.
3. Open a browser.
4. Create resources locally.
5. Export Terraform.
6. Deploy to real AWS/GCP/Azure when ready.

## Implementation Order

1. Make the appliance VM the first-class runtime.
2. Move durable state into the VM.
3. Start the full runtime stack inside the VM.
4. Keep the host launcher thin.
5. Add installer packaging per OS.
6. Add Terraform export/import workflows.

## Rollout Checklist

This is the execution checklist for the distribution workstream.

- [x] Define the distribution modes: developer, appliance, end-user.
- [x] Persist host OS and bridge metadata in the launcher-written host config.
- [x] Make the launcher expose a distribution mode field in the runtime contract.
- [x] Add a first-class appliance bootstrap path that starts the full stack inside one VM.
- [x] Wire the launcher to route top-level lifecycle commands through appliance mode.
- [x] Make appliance runtime detection ignore host bridge/config and use appliance-local state.
- [x] Add package-manager metadata for macOS, Linux, and Windows installers.
- [x] Add a VM bootstrap health check that fails fast if the appliance cannot reach its internal services.
- [x] Move the remaining runtime assumptions away from the host OS and into the appliance boundary.
- [x] Add a clean UI entry point for the Terraform export / deploy workflow.

## Recommendation Summary

- **Developer path:** `docker compose` or the launcher script.
- **End-user path:** OS-native installer or package manager.
- **Runtime path:** one Multipass VM appliance.
- **Inside the appliance:** simulator, CloudSim, provider services, and sandboxes.

This gives the simplest combination of:
- installability,
- restart safety,
- and future Terraform deployment support.
