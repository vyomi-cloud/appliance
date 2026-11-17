# Vyomi Reference Estate - GCP. One application, composed from stages. Capabilities are mapped in
# ../coverage-map.gcp.json; `tests/endurance/run_estate.sh tests/endurance/estate/gcp <endpoint>` is the release check.
# Provider talks to the simulator through per-service *_custom_endpoint overrides (see docs/architecture/v4.0/branches/endurance-gcp.md).
terraform {
  required_providers {
    google = { source = "hashicorp/google", version = "~> 5.45" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

variable "endpoint" { default = "http://host.docker.internal:19103" }
variable "project" { default = "vyomi-project" }

provider "google" {
  project      = var.project
  region       = "us-central1"
  zone         = "us-central1-a"
  access_token = "vyomi-fake-token"

  compute_custom_endpoint          = "${var.endpoint}/compute/v1/"
  iam_custom_endpoint              = "${var.endpoint}/"
  kms_custom_endpoint              = "${var.endpoint}/v1/"
  secret_manager_custom_endpoint   = "${var.endpoint}/v1/"
  storage_custom_endpoint          = "${var.endpoint}/storage/v1/"
  resource_manager_custom_endpoint = "${var.endpoint}/v1/"
  cloud_resource_manager_custom_endpoint = "${var.endpoint}/v1/"
  sql_custom_endpoint              = "${var.endpoint}/sql/v1beta4/"
  firestore_custom_endpoint        = "${var.endpoint}/v1/"
  redis_custom_endpoint            = "${var.endpoint}/v1/"
  pubsub_custom_endpoint           = "${var.endpoint}/v1/"
  cloud_scheduler_custom_endpoint  = "${var.endpoint}/v1/"
  artifact_registry_custom_endpoint = "${var.endpoint}/v1/"
  logging_custom_endpoint          = "${var.endpoint}/v2/"
  monitoring_custom_endpoint       = "${var.endpoint}/"
}

module "network_identity" {
  source  = "./modules/stage1-network-identity"
  project = var.project
}

module "data" {
  source     = "./modules/stage3-data"
  project    = var.project
  kms_key_id = module.network_identity.kms_key_id
  sa_email   = module.network_identity.sa_email
  network_id = module.network_identity.network_id
}

module "messaging" {
  source     = "./modules/stage4-messaging"
  project    = var.project
  kms_key_id = module.network_identity.kms_key_id
  bucket     = module.data.bucket
}

module "compute" {
  source     = "./modules/stage2-compute"
  project    = var.project
  network_id = module.network_identity.network_id
  subnet_id  = module.network_identity.subnet_ids[1]
  sa_email   = module.network_identity.sa_email
}

module "observability" {
  source   = "./modules/stage7-observability"
  project  = var.project
  bucket   = module.data.bucket
  topic_id = module.messaging.topic_id
}
