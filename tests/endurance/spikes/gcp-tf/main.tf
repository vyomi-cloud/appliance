terraform {
  required_providers { google = { source = "hashicorp/google", version = "~> 5.40" } }
}
variable "endpoint" { default = "http://host.docker.internal:18741" }
provider "google" {
  project      = "nano-project"
  region       = "us-central1"
  zone         = "us-central1-a"
  access_token = "vyomi-fake-token"

  storage_custom_endpoint = "${var.endpoint}/storage/v1/"
  pubsub_custom_endpoint  = "${var.endpoint}/v1/"
  compute_custom_endpoint = "${var.endpoint}/compute/v1/"
}
resource "google_storage_bucket" "endurance" {
  name          = "endurance-spike-bucket-gcp"
  location      = "US"
  force_destroy = true
}
resource "google_pubsub_topic" "endurance" { name = "endurance-spike-topic" }
resource "google_compute_network" "endurance" {
  name                    = "endurance-spike-net"
  auto_create_subnetworks = false
}
