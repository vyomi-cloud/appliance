# EKS: change requests for the platform layer (core/k3s_runtime.py, core/kube_state_core.py)

EKS (core/aws_eks_core.py, aws_eks_auth.py, aws_eks_nodes.py) is built only on the public K3sRuntime / RealK8sBackend API.
These are the points where the platform branch (v4/k8s-platform) would let EKS become more faithful. None are blockers.

1. **Node pools in the runtime.** `aws_eks_nodes.NodeProvisioner` starts one k3s agent container per node (docker run, labels
   `vyomi.k3s.name`, `vyomi.eks.nodegroup`, kubelet label `eks.amazonaws.com/nodegroup`) using the server's node-token. When the platform
   adds a per-pool API (create/scale/delete pool, labels, taints), EKS should call it instead; the provisioner is the only place to change.
2. **apiserver authentication-token-webhook.** `k3s server --kube-apiserver-arg=authentication-token-webhook-config-file=...` plus a
   mounted kubeconfig pointing at the TokenReview endpoint (see EKS-AUTH.md). Until then access entries and `aws eks get-token` tokens are
   verified and mapped by the simulator but are NOT enforced by the real apiserver: kubectl uses the admin kubeconfig.
3. **`--service-cidr`.** EKS reports 10.43.0.0/16 (k3s default) as `kubernetesNetworkConfig.serviceIpv4Cidr`; a create-time CIDR is recorded
   but not applied. Needs `--service-cidr` on server start.
4. **Version mapping.** k3s is pinned to one Kubernetes minor; EKS accepts 1.30-1.34 and records the requested version, but the running
   control plane is the pinned k3s version. A runtime image-per-minor map would make upgrades real.
5. **OIDC.** `--kube-apiserver-arg=oidc-issuer-url/oidc-client-id/...` for associated OIDC identity providers; currently stored only.
   Also a service-account issuer/JWKS endpoint for the cluster OIDC discovery document (IRSA).
6. **Memory.** A k3s server + agents need ~1 GB each; the Docker Desktop 8 GB VM tops out at about 3 nodes; EKS caps node groups at 3 total.
7. **Stale comment** in core/k3s_runtime.py that says EKS is TODO: EKS now exists. (Not edited, off limits.)
