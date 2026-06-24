# Vyomi Nano — in-browser substrate (WASM tier)

The **Nano** tiers run the simulator entirely in a browser tab — no server, no
Docker, no Multipass. This directory is the WASM substrate; it reuses the
existing SPA and (eventually) the existing `server.py` handlers, swapping real
backends for in-memory/WASM ones behind the `BackendProvider` seam (ADR-001).

Two Nano variants (flags, not forks):
- **Nano — conformance only**: the cloud API surface, in-memory. No compute.
- **Nano — with compute** (a.k.a. Micro): + in-tab runtimes (Pyodide / CheerpJ /
  TinyGo) so user app code runs in the browser.

## Architecture (the loop)
```
SPA fetch('/api/...')  ->  service worker (sw.js)  ->  Pyodide + wasm/ backend  ->  JSON
        (unchanged)         the fetch-ASGI shim         in-memory stores
```
A browser has no sockets, so the **service worker is the transport** (the P0).

## Provider-pluggable (more clouds joining)
Adding a cloud is **additive** — one module that maps its API to the shared
generic primitives, then `register()`. See `providers/oracle.py` as the proof /
template for the next cloud (IBM, Alibaba, DigitalOcean, …).

```
backends/store.py        generic in-memory primitives (object-store, nosql, queue, …)
providers/registry.py    the plugin registry + dispatch()
providers/{aws,gcp,azure,oracle}.py   per-cloud mappings (oracle = the new-cloud proof)
test_conformance.py      pure-Python conformance test (runs here AND in Pyodide)
index.html               Pyodide harness — loads the backend, runs the self-test, demo
sw.js                    service worker — intercepts /api/* and routes to the backend
```

## Files
```
backends/store.py        generic primitives (object-store/nosql/queue + ResourceStore)
providers/registry.py    plugin registry + dispatch() (incl. generic _resource CRUD)
providers/{aws,gcp,azure,oracle}.py   per-cloud mappings (oracle = new-cloud proof)
build_fixtures.py        dumps the REAL catalogs (aws+gcp) + spaces/tenants/host/runtime + routes.json
make_pages.py            wraps the REAL Pro/Max pages verbatim (dashboard + 3 consoles)
nano-boot.js             consoles: boots Pyodide + the SW<->backend bridge + ready signal
nano-sw.js               dashboard: registers the SW only (its /api reads come from fixtures)
sw.js                    service worker: serves fixtures + provider-aware space + CRUD routing
index.html               the REAL launch dashboard (static/clouds.html), wired (generated)
{aws,gcp,azure}-console.html   the REAL consoles, verbatim + boot loader (generated)
assets/brand/            real brand logo + favicons (copied for the dashboard)
test_conformance.py      pure-Python conformance (runs here AND in Pyodide)
e2e.mjs                  headless Playwright proof of the whole flow
```

## Run it
The `wasm/` folder is a SELF-CONTAINED web root — serve only it, so the repo
source is never exposed (`/server.py` etc. 404). Entry is the real dashboard at `/`.
```sh
python3 wasm/build_fixtures.py            # dump the real catalogs + routes (regen after catalog changes)
python3 wasm/make_pages.py                # wrap the real Pro/Max pages (dashboard + consoles)
python3 wasm/test_conformance.py          # validate the backend (no browser)
cd wasm && python3 -m http.server 8000    # serve wasm/ AS THE ROOT
# open http://localhost:8000/             # real Workspaces dashboard → console
```
Flow replicates Pro/Max as-is: `index.html` = the real **Workspaces** launch
dashboard (`static/clouds.html`) → "Open Console" → the real **`{aws,gcp,azure}-console.html`**.
Each console boots Pyodide via `nano-boot.js`; the dashboard only needs the SW
(`nano-sw.js`). Headless proof of the whole flow: `PW=$(npm root -g)/playwright node wasm/e2e.mjs`.

## Milestones
- **0 (done)**: provider-pluggable in-memory backend + Pyodide harness + SW shim.
  Conformance green in pure Python; 4 clouds incl. additive Oracle.
- **1 (done)**: the REAL `static/aws-console.html` runs fully in-browser — no
  server. SW serves the dumped real catalog/spaces/tenants; the console's
  catalog-driven CRUD (collection_path/resource_path) routes generically to the
  in-browser ResourceStore (all 12 AWS services get CRUD, new services free).
  **Validated headlessly** (`e2e.mjs`): Pyodide boots → catalog renders →
  create→list→delete round-trips through the console's own fetch.
- **2 (in progress)**: the WHOLE Pro/Max front-end replicated as-is — the real
  **Workspaces launch dashboard** (`clouds.html`) is the entry, and **all three
  consoles** (aws/gcp/azure) open verbatim and render against real catalogs
  (gcp catalog dumped; a provider-aware in-browser space lets each console pass
  its gate). **AWS has full CRUD.** Still to do: provider-aware CRUD for
  GCP/Azure (their route tables + dispatch — currently their data-plane is
  AWS-namespaced/partial), the Azure catalog (ARM-based, no dump module yet),
  and S3 multipart object upload (the one known 501).
- **3 (Nano-with-compute / Micro)**: Pyodide (Python) + CheerpJ (Java) + TinyGo
  (Go) in-tab compute.

## Honest limits
- The console **renders** against the real catalog and does generic CRUD, but
  the data-plane is the in-memory wasm backend — NOT the real `server.py`
  handlers (which can't import under Pyodide: `pty`/`socket`/`subprocess`/
  `uvicorn` at module top). True single-handler conformance needs the data-plane
  handlers extracted behind the BackendProvider seam — that's the real v2.3.0
  engineering, tracked separately. Today's cut is honest as a console UX + CRUD
  POC, not as the conformance harness.
- **Known partial**: S3 object upload (multipart form-data) returns 501 for now;
  bucket/table/instance/etc. CRUD works. Other un-mapped endpoints return a
  clean `501 NotTranslatedYet` (no silent fakes).
- Real OS-level compute can't run in a browser; Nano-with-compute runs *language
  runtimes* in-tab, not containers.
- External SDK/CLI access (aws-cli/Terraform → the sim) isn't possible — an
  in-browser app isn't a reachable endpoint. Nano = API/IAM/data-semantics
  conformance, a lower-fidelity SKU.
