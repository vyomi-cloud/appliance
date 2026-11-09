# v4 session claims

One row per active topic. Add your row BEFORE editing; remove it when the branch merges into the trunk. Before editing a path outside
your own claim, read this file and ask the owner if it is claimed. Claims older than 7 days without a push are stale.
Rule: docs/architecture/v4.0/V4-BRANCH-ARCHITECTURE.md (section 5.2).

| Session | Branch | Repo | Paths claimed | Since |
|---|---|---|---|---|
| builder (k8s port) | v4/merge-to-main | appliance | core/azure_dataprotection_core.py, core/kube_state_core.py, core/k3s_runtime.py, core/k8s_tier_gate.py, core/tier_policy.py, consoles/src/common/kube/**, consoles/src/azure/services/aks/** | 2026-11-09 |
| builder (EKS) | v4/eks | appliance | core/aws_eks_*.py, consoles/src/aws/services/eks/**, core/capabilities/aws/eks.json | 2026-11-09 |
| builder (k8s platform) | v4/k8s-platform | appliance | core/k3s_versions.py, core/k3s_identity.py, core/k3s_runtime.py | 2026-11-09 |
| tunnel redesign | (the tunnel session) | appliance | packaging/tunnel/**, wasm/relay/** | 2026-11-09 |
