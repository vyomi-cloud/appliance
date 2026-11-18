variable "project" {}

# KMS key rings/keys can never be deleted on real GCP (destroy only forgets them), so a rebuild needs a fresh name.
resource "random_id" "kms" { byte_length = 3 }

resource "google_compute_network" "main" {
  name                    = "vyomi-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

resource "google_compute_subnetwork" "public" {
  name          = "vyomi-public"
  ip_cidr_range = "10.10.0.0/24"
  region        = "us-central1"
  network       = google_compute_network.main.id
}

resource "google_compute_subnetwork" "private" {
  name                     = "vyomi-private"
  ip_cidr_range            = "10.10.1.0/24"
  region                   = "us-central1"
  network                  = google_compute_network.main.id
  private_ip_google_access = true
}

resource "google_compute_firewall" "web" {
  name          = "vyomi-allow-web"
  network       = google_compute_network.main.name
  direction     = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["web"]
  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
}

resource "google_compute_firewall" "internal" {
  name          = "vyomi-allow-internal"
  network       = google_compute_network.main.name
  source_ranges = ["10.10.0.0/16"]
  allow { protocol = "icmp" }
  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }
}

resource "google_service_account" "app" {
  account_id   = "vyomi-app"
  display_name = "Vyomi app service account"
}

resource "google_project_iam_member" "app_viewer" {
  project = var.project
  role    = "roles/viewer"
  member  = "serviceAccount:${google_service_account.app.email}"
}

resource "google_kms_key_ring" "main" {
  name     = "vyomi-ring-${random_id.kms.hex}"
  location = "us-central1"
}

resource "google_kms_crypto_key" "main" {
  name            = "vyomi-key"
  key_ring        = google_kms_key_ring.main.id
  rotation_period = "7776000s"
  labels          = { env = "endurance" }
}

resource "google_secret_manager_secret" "db" {
  secret_id = "vyomi-db-password"
  labels    = { env = "endurance" }
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db" {
  secret      = google_secret_manager_secret.db.id
  secret_data = "s3cr3t-endurance"
}

resource "google_project_iam_custom_role" "reader" {
  role_id     = "vyomiEndurance${random_id.kms.hex}"
  title       = "Vyomi endurance reader"
  description = "Custom role for the reference estate"
  permissions = ["storage.buckets.get", "storage.objects.list", "pubsub.topics.get"]
}

resource "google_project_iam_member" "app_custom" {
  project = var.project
  role    = google_project_iam_custom_role.reader.id
  member  = "serviceAccount:${google_service_account.app.email}"
}

resource "google_service_account" "ci" {
  account_id   = "vyomi-ci"
  display_name = "Vyomi CI"
}

resource "google_service_account_iam_member" "ci_impersonates_app" {
  service_account_id = google_service_account.app.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.ci.email}"
}

resource "google_kms_crypto_key_iam_member" "app_use" {
  crypto_key_id = google_kms_crypto_key.main.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.app.email}"
}

resource "google_secret_manager_secret_iam_member" "app_read" {
  secret_id = google_secret_manager_secret.db.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

resource "google_compute_address" "nat" {
  name   = "vyomi-nat-ip"
  region = "us-central1"
}

resource "google_compute_global_address" "lb" {
  name = "vyomi-lb-ip"
}

resource "google_compute_route" "egress" {
  name             = "vyomi-egress"
  network          = google_compute_network.main.name
  dest_range       = "0.0.0.0/0"
  next_hop_gateway = "default-internet-gateway"
  priority         = 1000
  tags             = ["egress"]
}

resource "google_compute_router" "main" {
  name    = "vyomi-router"
  region  = "us-central1"
  network = google_compute_network.main.id
}

resource "google_compute_router_nat" "main" {
  name                               = "vyomi-nat"
  router                             = google_compute_router.main.name
  region                             = "us-central1"
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.nat.self_link]
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_network" "peer" {
  name                    = "vyomi-peer-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_network_peering" "a_to_b" {
  name         = "vyomi-a-to-b"
  network      = google_compute_network.main.self_link
  peer_network = google_compute_network.peer.self_link
}

resource "google_compute_network_peering" "b_to_a" {
  name         = "vyomi-b-to-a"
  network      = google_compute_network.peer.self_link
  peer_network = google_compute_network.main.self_link
}

resource "google_secret_manager_secret" "api" {
  secret_id = "vyomi-api-key"
  labels    = { env = "endurance" }
  annotations = { owner = "platform" }
  ttl         = "31536000s"
  replication {
    user_managed {
      replicas { location = "us-central1" }
    }
  }
}

output "network_id" { value = google_compute_network.main.id }
output "network_name" { value = google_compute_network.main.name }
output "subnet_ids" { value = [google_compute_subnetwork.public.id, google_compute_subnetwork.private.id] }
output "sa_email" { value = google_service_account.app.email }
output "kms_key_id" { value = google_kms_crypto_key.main.id }
