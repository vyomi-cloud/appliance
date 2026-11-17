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

output "network_id" { value = google_compute_network.main.id }
output "network_name" { value = google_compute_network.main.name }
output "subnet_ids" { value = [google_compute_subnetwork.public.id, google_compute_subnetwork.private.id] }
output "sa_email" { value = google_service_account.app.email }
output "kms_key_id" { value = google_kms_crypto_key.main.id }
