/* Terraform (google provider) generated in the browser from the project's resources, read through the native Google APIs.
 * Works on every substrate, including Nano. Secret values, passwords and keys are never written; they become sensitive variables.
 * Output is deterministic (every list sorted by name) and split by service: versions.tf, variables.tf, network.tf, compute.tf, ... */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";
import * as net from "../networking/api.js";
import * as compute from "../compute/api.js";
import * as storage from "../storage/api.js";
import * as sql from "../sql/api.js";
import * as pubsub from "../pubsub/api.js";

const e = encodeURIComponent;
const tail = (u) => (u || "").split("/").pop();
const sym = (s) => String(s).replace(/[^A-Za-z0-9_]/g, "_").replace(/^(\d)/, "_$1");
// HCL string: JSON escaping plus the two template introducers HCL treats specially
const q = (v) => JSON.stringify(String(v)).replace(/\$\{/g, "$${").replace(/%\{/g, "%%{");
const safe = async (f) => { try { return (await f()) || []; } catch { return []; } };
const by = (key) => (a, b) => String(key(a)).localeCompare(String(key(b)));
const get = (path, query) => restJson("GET", path, { query });
const ind = (s) => s.split("\n").map((l) => (l ? "  " + l : l)).join("\n");
const list = (xs) => `[${[...xs].map(q).join(", ")}]`;
const mapLit = (o) => `{\n${Object.keys(o).sort().map((k) => `  ${q(k)} = ${q(o[k])}`).join("\n")}\n}`;
const blk = (name, lines) => `${name} {\n${lines.filter(Boolean).map(ind).join("\n")}\n}`;
const res = (type, name, lines) => `resource "${type}" "${sym(name)}" {\n${lines.filter(Boolean).map(ind).join("\n")}\n}\n`;
const attr = (k, v) => (v === undefined || v === null || v === "" ? "" : `${k} = ${typeof v === "boolean" || typeof v === "number" ? v : v.startsWith?.("@") ? v.slice(1) : q(v)}`);
const ref = (s) => `@${s}`; // marks a Terraform reference (unquoted)
const dur = (s) => (s ? String(s) : "");

const FILES = { network: "network.tf", compute: "compute.tf", storage: "storage.tf", messaging: "messaging.tf", database: "database.tf", serverless: "serverless.tf", security: "security.tf", iam: "iam.tf", dns: "dns.tf", registry: "registry.tf", scheduler: "scheduler.tf", cache: "cache.tf" };

/** Fetch everything once (all reads are native Google REST list calls; a service the substrate lacks yields []). */
export async function readProject(project = getProject()) {
  const P = e(project);
  const a = await Promise.all([
    safe(net.listNetworks), safe(net.listAllSubnets), safe(net.listFirewalls), safe(compute.listInstancesAllZones),
    safe(storage.listBuckets), safe(sql.listInstances), safe(pubsub.listTopics), safe(pubsub.listSubscriptions),
    safe(async () => (await get(`/v2/projects/${P}/locations/-/services`)).services),
    safe(async () => (await get(`/v2/projects/${P}/locations/-/functions`)).functions),
    safe(async () => (await get(`/v1/projects/${P}/databases`)).databases),
    safe(async () => (await get(`/v1/projects/${P}/locations/-/keyRings`)).keyRings),
    safe(async () => (await get(`/v1/projects/${P}/locations/-/keyRings/-/cryptoKeys`)).cryptoKeys),
    safe(async () => (await get(`/v1/projects/${P}/secrets`)).secrets),
    safe(async () => (await get(`/v1/projects/${P}/serviceAccounts`)).accounts),
    safe(async () => (await restJson("POST", `/v1/projects/${P}:getIamPolicy`, { body: {} })).bindings),
    safe(async () => (await get(`/dns/v1/projects/${P}/managedZones`)).managedZones),
    safe(async () => (await get(`/v1/projects/${P}/locations/-/repositories`)).repositories),
    safe(async () => (await get(`/v1/projects/${P}/locations/-/jobs`)).jobs),
    safe(async () => (await get(`/v1/projects/${P}/locations/-/instances`)).instances),
  ]);
  const [networks, subnets, firewalls, instances, buckets, sqls, topics, subs, runServices, functions, firestore, keyRings, cryptoKeys, secrets, serviceAccounts, iamBindings, zones, repos, jobs, redis] = a;
  const rrsets = {};
  await Promise.all(zones.map(async (z) => { rrsets[z.name] = await safe(async () => (await get(`/dns/v1/projects/${P}/managedZones/${e(z.name)}/rrsets`)).rrsets); }));
  return { project, networks, subnets, firewalls, instances, buckets, sqls, topics, subs, runServices, functions, firestore, keyRings, cryptoKeys, secrets, serviceAccounts, iamBindings, zones, rrsets, repos, jobs, redis };
}

/** Pure: project snapshot -> { files:{name:text}, count, kinds:{tfType:n}, unsupported:[...] }. */
export function generate(d) {
  const out = {}; // file -> [resource text]
  const kinds = {};
  const vars = [];
  const add = (file, type, name, lines) => { (out[file] ||= []).push({ key: `${type}.${sym(name)}`, text: res(type, name, lines) }); kinds[type] = (kinds[type] || 0) + 1; };

  // ---- ref tables (what is exported, so references become Terraform references) ----
  const nets = new Set(d.networks.map((n) => n.name).filter((n) => n !== "default"));
  const netRef = (u) => (nets.has(tail(u)) ? ref(`google_compute_network.${sym(tail(u))}.id`) : tail(u) || "default");
  const saByEmail = new Map(d.serviceAccounts.filter((s) => !/^(\d+-compute@|.*@appspot|.*@cloudbuild)/.test(s.email || "")).map((s) => [s.email, s.email.split("@")[0]]));
  const saRef = (email) => (saByEmail.has(email) ? ref(`google_service_account.${sym(saByEmail.get(email))}.email`) : email);
  const bucketNames = new Set(d.buckets.map((b) => b.name));
  const topicIds = new Set(d.topics.map((t) => tail(t.name)));
  const topicRef = (t) => (topicIds.has(tail(t)) ? ref(`google_pubsub_topic.${sym(tail(t))}.id`) : t);
  const ringKey = (n) => n.split("/cryptoKeys/")[0];
  const rings = new Map(d.keyRings.map((r) => [r.name, r]));

  // ---- network ----
  [...d.networks].filter((n) => n.name !== "default").sort(by((n) => n.name)).forEach((n) => add(FILES.network, "google_compute_network", n.name,
    [attr("name", n.name), attr("auto_create_subnetworks", !!n.autoCreateSubnetworks), n.routingConfig?.routingMode ? attr("routing_mode", n.routingConfig.routingMode) : ""]));
  [...d.subnets].filter((s) => tail(s.network) !== "default").sort(by((s) => `${tail(s.region)}/${s.name}`)).forEach((s) => add(FILES.network, "google_compute_subnetwork", s.name,
    [attr("name", s.name), attr("ip_cidr_range", s.ipCidrRange), attr("region", tail(s.region)), attr("network", netRef(s.network)), s.privateIpGoogleAccess ? attr("private_ip_google_access", true) : ""]));
  [...d.firewalls].sort(by((f) => f.name)).forEach((f) => add(FILES.network, "google_compute_firewall", f.name, [attr("name", f.name), attr("network", netRef(f.network)), attr("direction", f.direction || "INGRESS"),
    f.priority !== undefined ? attr("priority", f.priority) : "", f.sourceRanges ? `source_ranges = ${list(f.sourceRanges)}` : "", f.destinationRanges ? `destination_ranges = ${list(f.destinationRanges)}` : "",
    f.sourceTags ? `source_tags = ${list(f.sourceTags)}` : "", f.targetTags ? `target_tags = ${list(f.targetTags)}` : "",
    ...(f.allowed || []).map((x) => blk("allow", [attr("protocol", x.IPProtocol), x.ports ? `ports = ${list(x.ports)}` : ""])),
    ...(f.denied || []).map((x) => blk("deny", [attr("protocol", x.IPProtocol), x.ports ? `ports = ${list(x.ports)}` : ""]))]));

  // ---- compute ----
  [...d.instances].sort(by((i) => i.name)).forEach((i) => {
    const ni = i.networkInterfaces?.[0] || {};
    add(FILES.compute, "google_compute_instance", i.name, [attr("name", i.name), attr("machine_type", tail(i.machineType)), attr("zone", tail(i.zone)),
      blk("boot_disk", [blk("initialize_params", [attr("image", "debian-cloud/debian-12")])]),
      blk("network_interface", [attr("network", netRef(ni.network) || "default"), ni.subnetwork ? attr("subnetwork", tail(ni.subnetwork)) : ""]),
      i.labels && Object.keys(i.labels).length ? `labels = ${mapLit(i.labels)}` : ""]);
  });

  // ---- storage ----
  [...d.buckets].sort(by((b) => b.name)).forEach((b) => add(FILES.storage, "google_storage_bucket", b.name, [attr("name", b.name), attr("location", b.location || "US"), attr("storage_class", b.storageClass),
    attr("uniform_bucket_level_access", !!b.iamConfiguration?.uniformBucketLevelAccess?.enabled), b.versioning?.enabled ? blk("versioning", [attr("enabled", true)]) : "",
    b.labels && Object.keys(b.labels).length ? `labels = ${mapLit(b.labels)}` : ""]));

  // ---- messaging ----
  [...d.topics].sort(by((t) => tail(t.name))).forEach((t) => add(FILES.messaging, "google_pubsub_topic", tail(t.name), [attr("name", tail(t.name)), t.labels && Object.keys(t.labels).length ? `labels = ${mapLit(t.labels)}` : ""]));
  [...d.subs].sort(by((s) => tail(s.name))).forEach((s) => add(FILES.messaging, "google_pubsub_subscription", tail(s.name), [attr("name", tail(s.name)), attr("topic", topicRef(s.topic)),
    s.ackDeadlineSeconds ? attr("ack_deadline_seconds", s.ackDeadlineSeconds) : "", s.pushConfig?.pushEndpoint ? blk("push_config", [attr("push_endpoint", s.pushConfig.pushEndpoint)]) : ""]));

  // ---- database ----
  [...d.sqls].sort(by((x) => x.name)).forEach((x) => {
    const v = `db_password_${sym(x.name)}`;
    vars.push({ key: v, text: `variable "${v}" {\n  type      = string\n  sensitive = true\n}\n` });
    add(FILES.database, "google_sql_database_instance", x.name, [attr("name", x.name), attr("database_version", x.databaseVersion || "POSTGRES_15"), attr("region", x.region || "us-central1"),
      `root_password = var.${v}`, "deletion_protection = false", blk("settings", [attr("tier", x.settings?.tier || "db-f1-micro")])]);
  });
  [...d.firestore].sort(by((x) => x.name)).forEach((x) => add(FILES.database, "google_firestore_database", tail(x.name), [attr("name", tail(x.name)), attr("location_id", x.locationId || "nam5"),
    attr("type", x.type || "FIRESTORE_NATIVE"), x.concurrencyMode ? attr("concurrency_mode", x.concurrencyMode) : "", "deletion_policy = \"DELETE\""]));
  [...d.redis].sort(by((x) => x.name)).forEach((x) => {
    const id = tail(x.name), region = x.name.split("/")[3] || x.locationId;
    add(FILES.cache, "google_redis_instance", id, [attr("name", id), attr("region", region), attr("tier", x.tier || "BASIC"), attr("memory_size_gb", x.memorySizeGb || 1), x.redisVersion ? attr("redis_version", x.redisVersion) : "",
      x.displayName ? attr("display_name", x.displayName) : "", x.authorizedNetwork ? attr("authorized_network", netRef(x.authorizedNetwork)) : "", x.authEnabled ? attr("auth_enabled", true) : ""]);
  });

  // ---- serverless ----
  const fnIds = new Set(d.functions.map((f) => tail(f.name)));
  [...d.runServices].filter((s) => !fnIds.has(tail(s.name))).sort(by((s) => s.name)).forEach((s) => {
    const t = s.template || {}, c = (t.containers || [])[0] || {}, lim = c.resources?.limits || {};
    const sa = t.serviceAccount;
    add(FILES.serverless, "google_cloud_run_v2_service", tail(s.name), [attr("name", tail(s.name)), attr("location", s.name.split("/")[3] || "us-central1"), s.ingress ? attr("ingress", s.ingress) : "", "deletion_protection = false",
      blk("template", [sa ? attr("service_account", saRef(sa)) : "",
        t.scaling && (t.scaling.minInstanceCount !== undefined || t.scaling.maxInstanceCount !== undefined) ? blk("scaling", [t.scaling.minInstanceCount !== undefined ? attr("min_instance_count", t.scaling.minInstanceCount) : "", t.scaling.maxInstanceCount !== undefined ? attr("max_instance_count", t.scaling.maxInstanceCount) : ""]) : "",
        blk("containers", [attr("image", c.image || "us-docker.pkg.dev/cloudrun/container/hello"),
          ...(c.ports || []).slice(0, 1).map((p) => blk("ports", [attr("container_port", p.containerPort)])),
          ...[...(c.env || [])].filter((x) => x.value !== undefined).sort(by((x) => x.name)).map((x) => blk("env", [attr("name", x.name), attr("value", x.value)])),
          Object.keys(lim).length ? blk("resources", [`limits = ${mapLit(lim)}`]) : ""])])]);
  });
  [...d.functions].sort(by((f) => f.name)).forEach((f) => {
    const b = f.buildConfig || {}, sc = f.serviceConfig || {}, st = b.source?.storageSource, et = f.eventTrigger;
    add(FILES.serverless, "google_cloudfunctions2_function", tail(f.name), [attr("name", tail(f.name)), attr("location", f.name.split("/")[3] || "us-central1"), f.description ? attr("description", f.description) : "",
      blk("build_config", [attr("runtime", b.runtime), attr("entry_point", b.entryPoint),
        st ? blk("source", [blk("storage_source", [attr("bucket", bucketNames.has(st.bucket) ? ref(`google_storage_bucket.${sym(st.bucket)}.name`) : st.bucket), attr("object", st.object)])]) : ""]),
      blk("service_config", [sc.availableMemory ? attr("available_memory", sc.availableMemory) : "", sc.timeoutSeconds ? attr("timeout_seconds", sc.timeoutSeconds) : "",
        sc.minInstanceCount !== undefined ? attr("min_instance_count", sc.minInstanceCount) : "", sc.maxInstanceCount !== undefined ? attr("max_instance_count", sc.maxInstanceCount) : "",
        sc.serviceAccountEmail ? attr("service_account_email", saRef(sc.serviceAccountEmail)) : "",
        sc.environmentVariables && Object.keys(sc.environmentVariables).length ? `environment_variables = ${mapLit(sc.environmentVariables)}` : ""]),
      et ? blk("event_trigger", [attr("event_type", et.eventType), et.pubsubTopic ? attr("pubsub_topic", topicRef(et.pubsubTopic)) : "", et.triggerRegion ? attr("trigger_region", et.triggerRegion) : "", et.retryPolicy ? attr("retry_policy", et.retryPolicy) : ""]) : ""]);
  });

  // ---- security: KMS + Secret Manager ----
  [...d.keyRings].sort(by((r) => r.name)).forEach((r) => add(FILES.security, "google_kms_key_ring", `${r.name.split("/")[3]}_${tail(r.name)}`, [attr("name", tail(r.name)), attr("location", r.name.split("/")[3])]));
  [...d.cryptoKeys].sort(by((k) => k.name)).forEach((k) => {
    const rn = ringKey(k.name), r = rings.get(rn), vt = k.versionTemplate || {};
    add(FILES.security, "google_kms_crypto_key", `${rn.split("/")[3]}_${rn.split("/")[5]}_${tail(k.name)}`, [attr("name", tail(k.name)), attr("key_ring", r ? ref(`google_kms_key_ring.${sym(`${rn.split("/")[3]}_${tail(rn)}`)}.id`) : rn),
      k.purpose ? attr("purpose", k.purpose) : "", k.rotationPeriod ? attr("rotation_period", dur(k.rotationPeriod)) : "",
      vt.algorithm ? blk("version_template", [attr("algorithm", vt.algorithm), vt.protectionLevel ? attr("protection_level", vt.protectionLevel) : ""]) : ""]);
  });
  [...d.secrets].sort(by((s) => s.name)).forEach((s) => {
    const id = tail(s.name), v = `secret_value_${sym(id)}`;
    const reps = s.replication?.userManaged?.replicas;
    add(FILES.security, "google_secret_manager_secret", id, [attr("secret_id", id),
      s.labels && Object.keys(s.labels).length ? `labels = ${mapLit(s.labels)}` : "",
      blk("replication", reps ? [blk("user_managed", [...reps.map((r) => blk("replicas", [attr("location", r.location)]))])] : ["auto {}"])]);
    vars.push({ key: v, text: `variable "${v}" {\n  description = "Value for secret ${id}. Never exported; supply it at apply time."\n  type        = string\n  sensitive   = true\n}\n` });
    add(FILES.security, "google_secret_manager_secret_version", id, [attr("secret", ref(`google_secret_manager_secret.${sym(id)}.id`)), `secret_data = var.${v}`]);
  });

  // ---- IAM: service accounts + project bindings ----
  [...saByEmail.entries()].sort(by(([em]) => em)).forEach(([email, id]) => {
    const s = d.serviceAccounts.find((x) => x.email === email);
    add(FILES.iam, "google_service_account", id, [attr("account_id", id), s.displayName ? attr("display_name", s.displayName) : "", s.description ? attr("description", s.description) : ""]);
  });
  const members = [];
  d.iamBindings.forEach((bd) => (bd.members || []).forEach((m) => { if (!m.startsWith("deleted:")) members.push([bd.role, m]); }));
  members.sort((x, y) => (x[0] + x[1]).localeCompare(y[0] + y[1])).forEach(([role, m]) => {
    const em = m.startsWith("serviceAccount:") ? m.slice(15) : "";
    const mem = em && saByEmail.has(em) ? ref(`"serviceAccount:\${google_service_account.${sym(saByEmail.get(em))}.email}"`) : m;
    add(FILES.iam, "google_project_iam_member", `${role.replace(/^roles\//, "")}_${m}`, ["project = var.project_id", attr("role", role), attr("member", mem)]);
  });

  // ---- DNS ----
  [...d.zones].sort(by((z) => z.name)).forEach((z) => {
    add(FILES.dns, "google_dns_managed_zone", z.name, [attr("name", z.name), attr("dns_name", z.dnsName), z.description ? attr("description", z.description) : "", z.visibility ? attr("visibility", z.visibility) : ""]);
    [...(d.rrsets[z.name] || [])].filter((r) => !(r.name === z.dnsName && (r.type === "NS" || r.type === "SOA"))).sort(by((r) => `${r.name}/${r.type}`)).forEach((r) =>
      add(FILES.dns, "google_dns_record_set", `${z.name}_${r.name}_${r.type}`, [attr("name", r.name), attr("type", r.type), attr("ttl", r.ttl || 300), attr("managed_zone", ref(`google_dns_managed_zone.${sym(z.name)}.name`)), `rrdatas = ${list(r.rrdatas || [])}`]));
  });

  // ---- Artifact Registry ----
  [...d.repos].sort(by((r) => r.name)).forEach((r) => add(FILES.registry, "google_artifact_registry_repository", `${r.name.split("/")[3]}_${tail(r.name)}`, [attr("repository_id", tail(r.name)), attr("location", r.name.split("/")[3]),
    attr("format", r.format || "DOCKER"), r.description ? attr("description", r.description) : "", r.labels && Object.keys(r.labels).length ? `labels = ${mapLit(r.labels)}` : ""]));

  // ---- Cloud Scheduler ----
  [...d.jobs].filter((j) => j.name.split("/")[3] !== "appengine").sort(by((j) => j.name)).forEach((j) => add(FILES.scheduler, "google_cloud_scheduler_job", `${j.name.split("/")[3]}_${tail(j.name)}`,
    [attr("name", tail(j.name)), attr("region", j.name.split("/")[3]), attr("schedule", j.schedule), attr("time_zone", j.timeZone || "Etc/UTC"), j.description ? attr("description", j.description) : "",
      j.httpTarget ? blk("http_target", [attr("uri", j.httpTarget.uri), attr("http_method", j.httpTarget.httpMethod || "POST"), j.httpTarget.body ? attr("body", j.httpTarget.body) : ""]) : "",
      j.pubsubTarget ? blk("pubsub_target", [attr("topic_name", topicRef(j.pubsubTarget.topicName)), j.pubsubTarget.data ? attr("data", j.pubsubTarget.data) : ""]) : ""]));

  // ---- assemble files ----
  const header = `terraform {\n  required_providers {\n    google = {\n      source  = "hashicorp/google"\n      version = "~> 6.0"\n    }\n  }\n}\n\nprovider "google" {\n  project = var.project_id\n}\n`;
  const files = { "versions.tf": header };
  files["variables.tf"] = [`variable "project_id" {\n  type    = string\n  default = ${q(d.project)}\n}\n`, ...[...vars].sort(by((v) => v.key)).map((v) => v.text)].join("\n");
  for (const f of Object.keys(out).sort()) files[f] = [...out[f]].sort(by((r) => r.key)).map((r) => r.text).join("\n");
  const count = Object.values(kinds).reduce((s, n) => s + n, 0);
  const unsupported = [];
  return { files, count, kinds, unsupported };
}

export async function exportProject(project) {
  return generate(await readProject(project));
}

/** Everything as one zip (store-only, so it works on Nano where no server route can stream one). */
export async function zipOf(files) {
  const { zipBlob, bundleEntries } = await import("../../../common/zip.js");
  return zipBlob(bundleEntries({ files }));
}
