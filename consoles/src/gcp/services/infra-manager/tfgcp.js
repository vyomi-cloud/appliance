/* Terraform (google provider) generated in the browser from the project's resources, read through the native Google APIs.
 * Works on every substrate, including Nano. Passwords and keys are never written; secrets become variables. */
import * as net from "../networking/api.js";
import * as compute from "../compute/api.js";
import * as storage from "../storage/api.js";
import * as sql from "../sql/api.js";
import * as pubsub from "../pubsub/api.js";

const tail = (u) => (u || "").split("/").pop();
const sym = (s) => String(s).replace(/[^A-Za-z0-9_]/g, "_").replace(/^(\d)/, "_$1");
const q = (v) => JSON.stringify(String(v));
const safe = async (f) => { try { return (await f()) || []; } catch { return []; } };
const block = (type, name, lines) => `resource "${type}" "${sym(name)}" {\n${lines.filter(Boolean).map((l) => "  " + l).join("\n")}\n}\n`;

export async function exportProject(project) {
  const [networks, subnets, firewalls, instances, buckets, sqls, topics, subs] = await Promise.all([
    safe(net.listNetworks), safe(net.listAllSubnets), safe(net.listFirewalls), safe(compute.listInstancesAllZones),
    safe(storage.listBuckets), safe(sql.listInstances), safe(pubsub.listTopics), safe(pubsub.listSubscriptions)]);
  const out = [], unsupported = [];
  const nets = new Set(networks.map((n) => n.name));
  networks.filter((n) => n.name !== "default").forEach((n) => out.push(block("google_compute_network", n.name, [`name = ${q(n.name)}`, `auto_create_subnetworks = ${!!n.autoCreateSubnetworks}`])));
  const netRef = (u) => (nets.has(tail(u)) && tail(u) !== "default" ? `google_compute_network.${sym(tail(u))}.id` : q(tail(u)));
  subnets.filter((s) => tail(s.network) !== "default").forEach((s) => out.push(block("google_compute_subnetwork", s.name, [`name = ${q(s.name)}`, `ip_cidr_range = ${q(s.ipCidrRange)}`, `region = ${q(tail(s.region))}`, `network = ${netRef(s.network)}`])));
  firewalls.forEach((f) => out.push(block("google_compute_firewall", f.name, [`name = ${q(f.name)}`, `network = ${netRef(f.network)}`, `direction = ${q(f.direction || "INGRESS")}`,
    f.sourceRanges ? `source_ranges = ${JSON.stringify(f.sourceRanges)}` : "", f.targetTags ? `target_tags = ${JSON.stringify(f.targetTags)}` : "",
    ...(f.allowed || []).map((a) => `allow {\n    protocol = ${q(a.IPProtocol)}${a.ports ? `\n    ports    = ${JSON.stringify(a.ports)}` : ""}\n  }`)])));
  instances.forEach((i) => out.push(block("google_compute_instance", i.name, [`name = ${q(i.name)}`, `machine_type = ${q(tail(i.machineType))}`, `zone = ${q(tail(i.zone))}`,
    `boot_disk {\n    initialize_params {\n      image = "debian-cloud/debian-12"\n    }\n  }`, `network_interface {\n    network = ${q(tail(i.networkInterfaces?.[0]?.network) || "default")}\n  }`])));
  buckets.forEach((b) => out.push(block("google_storage_bucket", b.name, [`name = ${q(b.name)}`, `location = ${q(b.location || "US")}`, b.storageClass ? `storage_class = ${q(b.storageClass)}` : "", `uniform_bucket_level_access = ${!!b.iamConfiguration?.uniformBucketLevelAccess?.enabled}`])));
  topics.forEach((t) => out.push(block("google_pubsub_topic", tail(t.name), [`name = ${q(tail(t.name))}`])));
  subs.forEach((s) => out.push(block("google_pubsub_subscription", tail(s.name), [`name = ${q(tail(s.name))}`, `topic = google_pubsub_topic.${sym(tail(s.topic))}.id`, s.ackDeadlineSeconds ? `ack_deadline_seconds = ${s.ackDeadlineSeconds}` : ""])));
  const vars = [];
  sqls.forEach((d) => {
    const v = `db_password_${sym(d.name)}`;
    vars.push(`variable "${v}" {\n  type      = string\n  sensitive = true\n}\n`);
    out.push(block("google_sql_database_instance", d.name, [`name = ${q(d.name)}`, `database_version = ${q(d.databaseVersion || "POSTGRES_15")}`, `region = ${q(d.region || "us-central1")}`, `root_password = var.${v}`, `deletion_protection = false`, `settings {\n    tier = ${q(d.settings?.tier || "db-f1-micro")}\n  }`]));
  });
  unsupported.push("Cloud Run, Cloud Functions, Firestore, KMS, Secret Manager and IAM are not exported yet.");
  const header = `terraform {\n  required_providers {\n    google = {\n      source  = "hashicorp/google"\n      version = "~> 6.0"\n    }\n  }\n}\n\nprovider "google" {\n  project = var.project_id\n}\n\nvariable "project_id" {\n  type    = string\n  default = ${q(project)}\n}\n`;
  return { files: { "main.tf": [header, ...vars, ...out].join("\n") }, count: out.length, unsupported };
}
