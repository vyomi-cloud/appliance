# v4/cloudshell-capacity

Owner: Claude (session with the owner) - Started: 2026-11-27 - Base: origin/v4-on-main (b660a6238) - Status: in progress, NOT merged

## Purpose
Resource management for Mesh compute hosted on a Google Cloud Shell VM, as a second place to run Mesh next to Codespaces.
Cloud Shell hosts the Docker instances only (no LLM pool: it has about 14 GB of free disk, far below the ~45 GB of weights).

## What it does (`VYOMI_MESH_HOST_PROFILE=cloudshell`)
- Every instance is 0.5 vCPU / 2048 MB (`--cpus` / `--memory`), whatever instance type is asked for.
- RAM budget = host RAM - 4096 MB reserve (Docker + agent), all of it compute, AI bucket 0.
- CPU is an ENFORCED slot budget: slots = min(RAM / 2048, (cpus - 1) / 0.5). Measured Cloud Shell (4 vCPU, 15,994 MB) = 5 slots.
- A launch beyond the slots gets the cloud's own capacity error (InsufficientInstanceCapacity / ZONE_RESOURCE_POOL_EXHAUSTED / AllocationFailed).
- `GET /mesh/capacity`: slots, RAM, CPU, session time left (12 h cap, nominal), weekly hours (50, nominal).
- Env overrides: `VYOMI_MESH_PROFILE_INSTANCE_CPUS`, `_INSTANCE_MB`, `_RESERVE_MB`, `_RESERVE_CPUS`.
- No profile set: behaviour is unchanged.

## Measured vs not
Measured on one real Cloud Shell session: 4 vCPU, 15,994 MB total / 13,111 MB available at idle, /home 4.8 GB, ~10 GB free on /, no /dev/kvm.
NOT measured: Mesh's own memory use there, per-instance disk cost, real instance density under load, session lifetime, the Cloud Shell API.
Session length and weekly hours are Google's documented figures (pages disagree) and are not enforced.

## Not done
No provisioner that starts Cloud Shell or Mesh on it (needs the spike: `cloudshell_spike.py`, OAuth scope decision, Google terms).
No console UI for `/mesh/capacity` yet.

## Tests
`tests/conformance/test_mesh_cloudshell_capacity.py` (30 checks, hermetic). `test_mesh_capacity.py` has 2 failures that also fail on untouched trunk (GCP within-budget, Azure resize SkuNotAvailable).
