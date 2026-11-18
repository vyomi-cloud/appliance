variable "project" {}
variable "kms_key_id" {}
variable "sa_email" {}
variable "network_id" {}

resource "random_id" "sfx" { byte_length = 3 }

resource "google_storage_bucket" "data" {
  name                        = "vyomi-endurance-data-${random_id.sfx.hex}"
  location                    = "US"
  force_destroy               = true
  uniform_bucket_level_access = true
  storage_class               = "STANDARD"
  labels                      = { env = "endurance" }
  versioning { enabled = true }
  lifecycle_rule {
    action { type = "Delete" }
    condition { age = 365 }
  }
  cors {
    origin          = ["https://example.com"]
    method          = ["GET"]
    response_header = ["Content-Type"]
    max_age_seconds = 3600
  }
}

resource "google_storage_bucket_object" "hello" {
  name    = "hello.txt"
  bucket  = google_storage_bucket.data.name
  content = "hello from the endurance estate"
}

resource "google_storage_bucket_iam_member" "app_reader" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${var.sa_email}"
}

resource "google_sql_database_instance" "main" {
  name                = "vyomi-pg-${random_id.sfx.hex}"
  database_version    = "POSTGRES_15"
  region              = "us-central1"
  deletion_protection = false
  settings {
    tier              = "db-f1-micro"
    availability_type = "ZONAL"
    disk_size         = 10
    backup_configuration { enabled = true }
    ip_configuration { ipv4_enabled = true }
  }
}

resource "google_sql_database" "app" {
  name     = "appdb"
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "app" {
  name     = "appuser"
  instance = google_sql_database_instance.main.name
  password = "Endurance-pass-1"
}

resource "google_firestore_database" "main" {
  name            = "vyomi-fs-${random_id.sfx.hex}"
  location_id     = "nam5"
  type            = "FIRESTORE_NATIVE"
  deletion_policy = "DELETE"   # provider default is ABANDON: destroy would leave the database behind
}

resource "google_firestore_document" "doc" {
  database    = google_firestore_database.main.name
  collection  = "endurance"
  document_id = "doc1"
  fields      = jsonencode({ owner = { stringValue = "vyomi" } })
  depends_on  = [google_firestore_database.main]
}

resource "google_redis_instance" "cache" {
  name           = "vyomi-cache-${random_id.sfx.hex}"
  tier           = "BASIC"
  memory_size_gb = 1
  region         = "us-central1"
}

output "bucket" { value = google_storage_bucket.data.name }
output "sql_instance" { value = google_sql_database_instance.main.name }
