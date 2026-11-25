/* Per-resource IAM wire for the shared ResourcePermissionsPanel: kind -> { label, get(args), set(args, policy) } on the NATIVE
 * getIamPolicy / setIamPolicy of each service. `args` is the resource's own identifiers (the same ones its detail page already has).
 * Services whose real console has a Permissions panel but which this console does not simulate (BigQuery, Spanner, Firestore) are
 * listed in docs/architecture/v4.0/branches/iam-resource-tabs.md as skipped. */
import { restJson } from "../../common/wire.js";
import { getProject } from "../project.js";

const e = encodeURIComponent;
const P = () => e(getProject());
const post = (path) => ({
  get: () => restJson("POST", `${path}:getIamPolicy`, { body: {} }),
  set: (policy) => restJson("POST", `${path}:setIamPolicy`, { body: { policy } }),
});
const get = (path) => ({
  get: () => restJson("GET", `${path}:getIamPolicy`),
  set: (policy) => restJson("POST", `${path}:setIamPolicy`, { body: { policy } }),
});

export const RESOURCE_KINDS = {
  bucket: { label: "Cloud Storage bucket", wire: ({ name }) => ({
    get: () => restJson("GET", `/storage/v1/b/${e(name)}/iam`),
    set: (policy) => restJson("PUT", `/storage/v1/b/${e(name)}/iam`, { body: policy }) }) },
  "pubsub-topic": { label: "Pub/Sub topic", wire: ({ name }) => post(`/v1/projects/${P()}/topics/${e(name)}`) },
  "pubsub-subscription": { label: "Pub/Sub subscription", wire: ({ name }) => post(`/v1/projects/${P()}/subscriptions/${e(name)}`) },
  "run-service": { label: "Cloud Run service", wire: ({ region, name }) => get(`/v2/projects/${P()}/locations/${e(region)}/services/${e(name)}`) },
  "compute-instance": { label: "Compute Engine instance", wire: ({ zone, name }) => ({
    get: () => restJson("GET", `/compute/v1/projects/${P()}/zones/${e(zone)}/instances/${e(name)}/getIamPolicy`),
    set: (policy) => restJson("POST", `/compute/v1/projects/${P()}/zones/${e(zone)}/instances/${e(name)}/setIamPolicy`, { body: { policy } }) }) },
  "compute-disk": { label: "Compute Engine disk", wire: ({ zone, name }) => ({
    get: () => restJson("GET", `/compute/v1/projects/${P()}/zones/${e(zone)}/disks/${e(name)}/getIamPolicy`),
    set: (policy) => restJson("POST", `/compute/v1/projects/${P()}/zones/${e(zone)}/disks/${e(name)}/setIamPolicy`, { body: { policy } }) }) },
  "kms-key": { label: "Cloud KMS key", wire: ({ loc, keyRing, name }) => get(`/v1/projects/${P()}/locations/${e(loc)}/keyRings/${e(keyRing)}/cryptoKeys/${e(name)}`) },
  "kms-keyring": { label: "Cloud KMS key ring", wire: ({ loc, name }) => get(`/v1/projects/${P()}/locations/${e(loc)}/keyRings/${e(name)}`) },
  secret: { label: "Secret", wire: ({ name, location }) => get(`/v1/projects/${P()}${location ? `/locations/${e(location)}` : ""}/secrets/${e(name)}`) },
  "artifact-repo": { label: "Artifact Registry repository", wire: ({ location, name }) => post(`/v1/projects/${P()}/locations/${e(location)}/repositories/${e(name)}`) },
};
