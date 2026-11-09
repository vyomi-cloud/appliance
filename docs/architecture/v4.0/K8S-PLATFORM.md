# Managed Kubernetes platform layer (AKS / EKS / GKE on real k3s)

Shared layer in `core/k3s_runtime.py` (+ `core/k3s_versions.py`, `core/k3s_identity.py`). Offline appliance only; the substrate-free cores see
only `kube_state_core.CLUSTER_RUNTIME`. Enable with `VYOMI_K8S_BACKEND=k3s`; `server.py` startup (`_install_k3s_backend`) calls
`k3s_runtime.install_if_enabled()` (wires the runtime + backend factory and starts the LoadBalancer controller). Without Docker, clusters fall back
to the simulated control plane. Tests: `tests/conformance/test_k3s_platform.py` (fake docker, always), `test_k3s_platform_live.py` (`VYOMI_LIVE_K3S=1`).

State is Docker itself (labels on containers/volumes), so an appliance restart finds clusters again. `cluster_id` is any stable string
(ARM resource id, GKE `projects/p/locations/l/clusters/c`, EKS ARN). `cloud` is `azure | aws | gcp`.

## Topology
`vyomi-k3s-<hash>` = control plane only (`--disable-agent`); workers are `vyomi-k3s-<hash>-<pool>-<i>` agents. A 2-node cluster = 2 agents.
Volumes: `<container>-data` (server: etcd/certs/SA signing key; agent: containerd + local-path PV data), `<server>-pool-<pool>` (pool definition marker).

## API (stable)
| Area | Call |
|---|---|
| Lifecycle | `create_cluster(cloud, id, version, node_count, tls_sans, on_ready, wait, ready_timeout, pools=None, oidc=None)`, `delete_cluster`, `exists`, `is_ready`, `list_clusters`, `wait_ready` |
| Versions | `k3s_versions.resolve(cloud, requested) -> {minor,k3sTag,version}`; tables `K3S_BY_MINOR`, `SUPPORTED` (AKS 1.29-1.32, EKS/GKE 1.28-1.32). A request maps to the NEAREST supported minor (ties to newer); `info["actualVersion"]` is what really runs |
| Upgrade | `upgrade_cluster(cloud, id, version)`: server container replaced on the same data volume (same token + SA key), then agents drained and replaced one at a time keeping their volumes. Downgrade refused. `cluster_version()` |
| Node pools | pool = `{name,count,vmSize,labels,taints}`; `add_pool`, `scale_pool` (down = highest ordinals, drain + delete node), `delete_pool`, `list_pools`, `sync_pools(desired)` (used by AKS `agentPools` and GKE `nodePools`). Labels: AKS `agentpool=`, `kubernetes.azure.com/agentpool=`; EKS `eks.amazonaws.com/nodegroup=`; GKE `cloud.google.com/gke-nodepool=`; plus `node.kubernetes.io/instance-type=<vmSize>` and user labels; taints become kubelet `--node-taint` |
| Stop/start | `stop_cluster` (agents then server `docker stop`; volumes kept), `start_cluster(wait, on_ready)`, `is_running`. Wired to the AKS `stop`/`start` actions (GKE has none) |
| Credentials | `kubeconfig(cloud,id,server_url=None,role="admin"|"user")`. admin = k3s admin client cert (cluster-admin). user = bearer token of `kube-system/vyomi-cluster-user` (ClusterRole `view` cluster-wide + `edit` in `default`; no secrets, no kube-system writes). AKS `listClusterUserCredential`/`listClusterAdminCredential` use these |
| Workload identity | API server runs with `--kube-apiserver-arg service-account-issuer=<VYOMI_OIDC_BASE>/oidc/<cloud>/<hash>` and `service-account-jwks-uri=<issuer>/keys`. The simulator (`server.py`) serves `GET /oidc/<cloud>/<hash>/.well-known/openid-configuration` and `/keys` (the cluster's real public keys read from `kubectl get --raw /openid/v1/jwks`). `<hash>` = `k3s_runtime.cluster_hash(cloud, id)`. `k3s_identity.verify_token(token, audience=None, jwks_fetcher=None) -> {sub,aud,iss,namespace,serviceAccount,cloud,clusterHash,claims}` (pure-Python RS256, exp/nbf/aud checks, JWKS cached 5 min, one refetch on unknown kid; raises `TokenError`). Cloud STS/Entra cores call it, then map `sub` to their own role/identity. The API server REQUIRES https issuer/jwks URLs (k3s refuses to start with http), so `VYOMI_OIDC_BASE` defaults to the logical issuer `https://oidc.vyomi.local`; token verification never dials it (the simulator reads the keys from the cluster and serves them on its own `/oidc/...` routes, plain http on the appliance port). Point `VYOMI_OIDC_BASE` at the appliance's HTTPS front if an external verifier must fetch discovery by the issuer URL |
| API-server OIDC auth | `create_cluster(..., oidc=True | {issuerUrl,clientId,usernameClaim,groupsClaim,usernamePrefix})` adds `--kube-apiserver-arg oidc-*` (default issuer `<base>/oidc/idp/<cloud>`, to be served by the cloud's identity core) |
| LoadBalancer | `reconcile_loadbalancers(cloud,id)` (background controller started by `install()` every 5 s; callable directly). For each `type: LoadBalancer` Service: `lb_allocator(cloud,id,ns,svc,used)` -> `{"ip"}` (AKS/GKE) or `{"hostname"}` (EKS ELB name), written to `status.loadBalancer.ingress`; a host forward per port is recorded as annotation `vyomi.cloud/host-endpoint` (`{"80":"127.0.0.1:PORT"}`). Default pool is a /24 per cluster in a per-cloud range; **replace `runtime().lb_allocator`** to draw from the cloud core's own public-IP/LB pool |
| Storage | per-cloud StorageClasses on `rancher.io/local-path` (azure `managed-csi` (default), `managed-csi-premium`, `azurefile-csi`, `default`; aws `gp2` (default), `gp3`; gcp `standard-rwo` (default), `premium-rwo`, `standard`), re-applied on every ready. `volumes(cloud,id) -> [{pv,claim,namespace,storageClass,size,node,dockerVolume,path,diskName,phase}]` is the PV -> Docker volume data model for the cloud's disk list |
| GKE data plane | `clusters/{c}/k8s/<path>` goes to the real API server via `api_request(cloud,id,method,path,body)` when the cluster is real (the simulated object store is only used without the runtime) |

## Design notes / limits (honest)
- LB reachability: a Python forwarder dials `<agent container IP>:<nodePort>` when the simulator shares the Docker network (appliance in a container); on Docker Desktop
  (container IPs not routable from the host) it falls back to `kubectl port-forward` on the host (needs `kubectl` there).
- User credential is a ServiceAccount bearer token, not a per-user client certificate: the k3s image has no key/CSR tooling and the appliance has no crypto library.
- Pool scale-down deletes the node's data volume (as a real node pool does); `PATCH` on the raw API passthrough is a JSON merge patch (GET+merge+PUT).
- Cloud identity -> Kubernetes RBAC mapping (Entra groups etc.) is not built here; the OIDC option only configures the API server.
- EKS has no control-plane core yet; it only needs the same hooks as AKS/GKE (`create_cluster("aws", arn, ...)`, `sync_pools`, `kubeconfig`).
