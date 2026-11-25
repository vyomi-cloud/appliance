# v4/compute-sizes: compute size pickers offer only what the substrate can run

Base: `origin/v4/iam-pickers-integ`. One source: `core/compute_sizes.py` (vendored unchanged to `wasm/core/` by `wasm/build_cores.py`;
`python3 -m core.compute_sizes` prints the whole table as JSON).

## Limits found in the code

| Substrate | Limit | Code source |
|---|---|---|
| Nano (v86 in-browser VM) | 1 vCPU always; 32-bit x86 guest (no arm); guest RAM = `mem_mb` MiB; largest tier ever mapped is 1024 MiB; RAM is also the VM's disk; no concurrency cap exists in code (each VM = one Worker + a golden snapshot per image+RAM in IndexedDB), so `total_mem_mb` 3072 in the source is an advisory browser budget, shown not enforced | `wasm/vm/vm-worker.js` (`memory_size`), `wasm/vm/nano-vm-host.js` (`mem_mb`), `wasm/providers/registry.py` (`_VM_MEM_MB`, `_vm_mem`) |
| Mesh (Docker) | container `--cpus N --memory Mm`; Mesh cap = 70% of host RAM, split 50/50 compute/AI (all compute when the LLM is remote); default Codespace 4 vCPU / 16 GB / 32 GB disk gives compute bucket 5734 MB; one instance may take at most 75% of that bucket (4300 MB; hard max 8192) and at most the host cores | `core/compute/backend.py`, `core/mesh.py` (`resource_budget`, ledger), `server.py` (`_docker_instance_memory_mb`, `_docker_instance_obj`) |
| offline appliance | unrestricted (existing tier caps still apply) | n/a |

Substrate is detected in `compute_sizes.substrate()`: Pyodide = nano, `mesh.mesh_mode()` = mesh, else offline (`VYOMI_COMPUTE_SUBSTRATE` overrides, for tests).
Mesh limits are live: a 2-core/8 GB host (`VYOMI_MESH_CAP_MB=8192`) drops `t3.medium` and keeps `t3.small`.

## Sizes offered (real names verbatim; spec shown is the real cloud spec)

| Cloud | Nano (runs 1 vCPU, RAM as listed) | Mesh (default 4 vCPU/16 GB Codespace) |
|---|---|---|
| AWS | t2.nano, t3.nano, t3a.nano (512 MiB), t2.micro, t3.micro, t3a.micro (1 GiB) | the Nano set + t2/t3/t3a.small (2 GiB), t2/t3/t3a.medium, c5.large, c6i.large (4 GiB) |
| GCP | f1-micro (614 MiB), e2-micro (1 GiB) | f1-micro, e2-micro, g1-small (1.7 GiB), e2-small (2 GiB), e2-medium (4 GiB) |
| Azure | Standard_B1ls (512 MiB), Standard_B1s (1 GiB) | B1ls, B1s, B1ms (2 GiB), B2s (4 GiB), F2s_v2 (4 GiB) |

## Behaviour

- Lists: EC2 `DescribeInstanceTypes`, GCE `machineTypes.list/get`, Azure `vmSizes` return only runnable sizes and mark each row with `vyomiSubstrate`
  (the consoles read it for the note "Showing sizes available on Nano (browser VM) | Mesh (Docker)"). The pickers hide the rest and keep their search/filter UX.
- Enforcement: EC2 RunInstances / ModifyInstanceAttribute -> `Unsupported` 400 (not retried by SDKs); GCE insert / setMachineType -> 400 `INVALID_ARGUMENT`
  (`machineTypes.get` of a hidden type is 404); Azure VM PUT -> 409 `SkuNotAvailable`. The Mesh Docker path in `server.py` enforces the same for EC2 and GCE.
  Existing Mesh capacity errors (InsufficientInstanceCapacity / ZONE_RESOURCE_POOL_EXHAUSTED / AllocationFailed) still apply to sizes that are listed but do not fit the remaining budget.
- Honoured resources: Nano VM RAM = the size's real RAM (`nano_vm_mem_mb`, capped 1024; unlisted legacy types keep the old mapping); Mesh containers get the size's real vCPU capped at the host cores (`mesh_vcpus`) instead of a flat 1.
- Not changed: AKS/EKS/GKE node sizes and RDS classes (not Docker VM compute here), custom GCE machine types (the console has none).

## Tests

`tests/conformance/test_compute_sizes_core.py` (tables, caps, AWS/GCP/Azure describe + enforcement on both substrates; AWS/GCP halves also run under Pyodide),
`consoles/tests/smoke-compute-sizes.mjs` (Playwright per cloud x substrate against two `consoles/dev_server.py` instances).
`tests/conformance/test_mesh_capacity.py` expectations updated: an 8 GB type is now `Unsupported`, a 4 GB Azure resize on a 1.4 GB share is `SkuNotAvailable`.
