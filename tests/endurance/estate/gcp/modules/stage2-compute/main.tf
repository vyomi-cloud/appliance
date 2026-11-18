variable "project" {}
variable "network_id" {}
variable "subnet_id" {}
variable "sa_email" {}

resource "google_compute_disk" "data" {
  name   = "vyomi-data-disk"
  type   = "pd-balanced"
  zone   = "us-central1-a"
  size   = 20
  labels = { env = "endurance" }
}

resource "google_compute_snapshot" "data" {
  name        = "vyomi-data-snap"
  source_disk = google_compute_disk.data.name
  zone        = "us-central1-a"
}

resource "google_compute_health_check" "http" {
  name = "vyomi-http-hc"
  http_health_check { port = 80 }
  check_interval_sec = 10
  timeout_sec        = 5
}

resource "google_compute_instance_template" "web" {
  name         = "vyomi-web-tpl"
  machine_type = "e2-small"
  tags         = ["web"]
  disk {
    source_image = "debian-cloud/debian-12"
    auto_delete  = true
    boot         = true
  }
  network_interface {
    network    = var.network_id
    subnetwork = var.subnet_id
  }
  service_account {
    email  = var.sa_email
    scopes = ["cloud-platform"]
  }
}

resource "google_artifact_registry_repository" "apps" {
  location      = "us-central1"
  repository_id = "vyomi-apps"
  format        = "DOCKER"
  description   = "Vyomi estate images"
}

resource "google_compute_project_metadata_item" "env" {
  key   = "vyomi-env"
  value = "endurance"
}
