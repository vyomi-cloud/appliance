variable "project" {}
variable "sa_email" {}
variable "bucket" {}

resource "random_id" "sl" { byte_length = 3 }

resource "google_cloud_run_v2_service" "api" {
  name     = "vyomi-api-${random_id.sl.hex}"
  location = "us-central1"
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = { env = "endurance" }
  template {
    service_account = var.sa_email
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      env {
        name  = "STAGE"
        value = "endurance"
      }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_job" "batch" {
  name     = "vyomi-batch-${random_id.sl.hex}"
  location = "us-central1"
  template {
    template {
      containers {
        image = "us-docker.pkg.dev/cloudrun/container/job"
      }
    }
  }
}
