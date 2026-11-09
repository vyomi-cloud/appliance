# v4/k8s-port

Owner: <session / person> - Started: 2026-11-09 - Base: origin/v4-on-main (7f589cba) - Status: in progress

## Purpose
Port the shared managed-Kubernetes platform layer on k3s (versions, node pools, stop/start, upgrade, workload identity, LoadBalancer, storage, user/admin credentials) and Amazon EKS (native REST API, get-token auth, node groups, AWS Backup for EKS) onto the trunk. Managed Kubernetes is Pro/Max/Enterprise only (core/k8s_tier_gate.py, already on the trunk).

## Architecture
`core/k3s_runtime.py` (+ `k3s_versions.py`, `k3s_identity.py`): a privileged k3s server container per cluster (`--disable-agent`) plus one agent container per node-pool node, behind the `KubeBackend` seam in `core/kube_state_core.py`. `core/aws_eks_core.py` / `aws_eks_auth.py` / `aws_eks_nodes.py`: EKS REST wire (SigV4 scope `eks`), `get-token` auth, node groups mapped to agent containers. Console: `consoles/src/aws/services/eks/**`. Detail: `K8S-PLATFORM.md`, `EKS-NEEDS.md`, `EKS-AUTH.md`.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| EKS clusters start control-plane only (`pools=[]`); nodes appear when a node group is created | Platform default pool `ng-default` for EKS | Real EKS has no nodes until a node group exists; the default pool broke DeleteNodegroup |
| Conflict in `azure_arm_core.py`: keep trunk monitoring reconcile, then run the real update / pool hooks after it succeeds | Run the real update first | A rejected reconcile must not leave a half-applied real update |
| Port, not merge, from `v4/k8s-platform` and `v4/eks` | Merge the old-base branches | Stale base; rule 10 |

## Open issues
- [ ] EKS API-server auth: `--authentication-token-webhook-config-file` needs a webhook kubeconfig injected into the k3s server before start (EKS-NEEDS.md item 2); not built, needs a live Docker run (owner: k8s-port)
- [ ] Live tests (`test_k3s_platform_live.py`, `test_aws_eks_live.py`) not run on this base; need a quiet Docker VM
- [ ] EKS console browser check not done

## Testing
<what was run, where (Nano on :8099 / headless Docker), and the result; what was NOT run>
