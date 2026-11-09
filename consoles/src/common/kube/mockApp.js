/* The "Deploy mock application" payload shared by every cloud's backup dashboard: namespace + deployment (2 replicas; its pods are derived by the deployment controller) + service.
 * JSON documents separated by `---` (valid YAML, so a native runCommand/kubectl accepts it and the JS emulator can parse it).
 * Pods are real Pod objects; nothing schedules them (Vyomi runs no kubelet) so their STATUS is honestly Pending. */
export const MOCK_NS = "simulation-app";
const labels = { app: "web" };
const container = { name: "web", image: "nginx:1.27" };
export const MOCK_MANIFESTS = [
  { apiVersion: "v1", kind: "Namespace", metadata: { name: MOCK_NS } },
  { apiVersion: "apps/v1", kind: "Deployment", metadata: { name: "web", namespace: MOCK_NS, labels },
    spec: { replicas: 2, selector: { matchLabels: labels }, template: { metadata: { labels }, spec: { containers: [container] } } } },
  { apiVersion: "v1", kind: "Service", metadata: { name: "web", namespace: MOCK_NS }, spec: { selector: labels, ports: [{ port: 80 }] } },
];
export const MOCK_YAML = MOCK_MANIFESTS.map((m) => JSON.stringify(m)).join("\n---\n") + "\n";
export const APPLY_MOCK = `kubectl apply -f - <<'VYOMI_EOF'\n${MOCK_YAML}VYOMI_EOF`;
export const DISASTER = `kubectl delete namespace ${MOCK_NS}`;
