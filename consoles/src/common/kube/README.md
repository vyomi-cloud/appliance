# Shared kube backup/restore layer

Cloud-agnostic pieces for "back up a Kubernetes cluster, break it, restore it" consoles. First consumer: Azure Backup for AKS
(`consoles/src/azure/services/aks/BackupPanel.jsx`). EKS (AWS Backup) and GKE (Backup for GKE) plug in with an **adapter**.

## Files
| file | what |
|---|---|
| `kubectl.js` | kubectl emulator (get / delete / apply -f - / create namespace\|deployment; `-n`, `-A`, `-o wide\|json\|yaml\|name`; real "No resources found in <ns> namespace." text). Runs over a **KubeStore**. |
| `Terminal.jsx` | xterm-style terminal (history, `clear`, `help`, `ref.exec(line)` echoes a command). No xterm bundle exists in the repo; this is plain React. |
| `BackupDashboard.jsx` | split screen: dashboard left (cluster health, namespaces+pods, vault/storage, recovery points, jobs), terminal right, **Deploy mock application** and **Inject disaster** buttons. Polls the adapter every 2 s. |
| `mockApp.js` | the mock app (namespace `simulation-app` + deployment `web` + pods `web-0/1`) and the disaster command. |

## Backend side (Python, both substrates)
`core/kube_state_core.py` is the cloud-agnostic Kubernetes state, keyed by `(cloud, cluster_id)`:
`backend_for(store, cloud, cluster_id, rec=None) -> KubeBackend`.

`KubeBackend` interface: `list_namespaces, list(kind, ns), apply(manifests), delete(kind, name, ns), delete_namespace(name),
export_resources(namespaces=None) -> {namespaces, objects, counts}, health(), kubectl(command)`.

* `InMemoryKubeBackend` - JSON tree (Nano, dev server, default offline). The kubectl engine is `core/azure_aks_k8s_core.py`.
* `RealK8sBackend` - **seam only**, NOT implemented here: the offline appliance will back each cluster with a real k3s API server;
  that backend must talk to the API server (no assumption that state lives in our process), return the same `export_resources`
  document shape, and use server-side apply. Install it through `kube_state_core.BACKEND_FACTORY = lambda cloud, cluster_id: ...`.
* Backup engines (see `core/azure_dataprotection_core.py`) only call `export_resources` / `apply` through the backend - never the tree.
  A new cloud's backup core: PUT vault/plan -> protected instance -> async job (`tick`) writing `export_resources()` JSON as a blob in the
  simulator's own store -> recovery point -> restore job calling `backend.apply(...)`.

## Adapter (what a cloud passes to `<BackupDashboard adapter={...} />`)
```js
{
  cliName: "az",                       // shown in the "command not found" hint
  terminalTitle: "aks-cluster terminal",
  banner: "text printed when the terminal opens",
  help: ["az ... lines for `help`"],
  labels: { cluster, vault, storage, recoveryPoints },   // optional lens vocabulary

  // kubectl: EITHER native (preferred when the cloud has an action that runs it)...
  kubectl: async (commandLine) => ({ exitCode, logs }),
  // ...OR a KubeStore the shared emulator runs over:
  store: { list(kind, ns), apply(manifests) -> ["pod/x created"], delete(kind, name, ns), deleteNamespace(name) },

  // cloud CLI backup commands (vault create / adhoc backup / restore trigger ...). Return true if handled.
  commands: async (line, io) => { /* io.print(s) io.error(s) io.wait(ms) */ return handled; },

  getCluster: async () => ({ name, state: "Running", version, location }),
  getBackup:  async () => ({
    vault: { name, state } | null, instance: { name, state } | null,
    storage: { account, container, blobs } | null,
    recoveryPoints: [{ id, time, contents }], jobs: [{ id, operation, status, start }], note,
  }),
  deployCommand, disasterCommand,      // optional overrides of the quick buttons
  footer,                              // optional extra JSX (e.g. a NotSimulated limits note)
}
```
Native calls only: `commands`/`getBackup` must use the cloud's real API (ARM / AWS Backup / Backup for GKE), never a bespoke `/api/*`.
Anything not truly implemented (persistent-volume data, ...) goes in `footer` as a capability-registry-driven NotSimulated panel.
