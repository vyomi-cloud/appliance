variable "project" {}
variable "kms_key_id" {}
variable "bucket" {}

resource "google_pubsub_schema" "event" {
  name       = "vyomi-event-schema"
  type       = "AVRO"
  definition = "{\"type\":\"record\",\"name\":\"Event\",\"fields\":[{\"name\":\"id\",\"type\":\"string\"}]}"
}

resource "google_pubsub_topic" "events" {
  name   = "vyomi-events"
  labels = { env = "endurance" }
  message_retention_duration = "86600s"
}

resource "google_pubsub_topic" "dead" {
  name = "vyomi-events-dead"
}

resource "google_pubsub_subscription" "pull" {
  name                 = "vyomi-events-pull"
  topic                = google_pubsub_topic.events.id
  ack_deadline_seconds = 20
  retain_acked_messages = false
  message_retention_duration = "604800s"
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead.id
    max_delivery_attempts = 5
  }
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

resource "google_pubsub_subscription" "push" {
  name  = "vyomi-events-push"
  topic = google_pubsub_topic.events.id
  push_config { push_endpoint = "https://example.com/push" }
}

resource "google_pubsub_topic_iam_member" "pub" {
  topic  = google_pubsub_topic.events.name
  role   = "roles/pubsub.publisher"
  member = "allAuthenticatedUsers"
}

resource "google_cloud_scheduler_job" "tick" {
  name     = "vyomi-tick"
  schedule = "*/30 * * * *"
  region   = "us-central1"
  pubsub_target {
    topic_name = google_pubsub_topic.events.id
    data       = base64encode("tick")
  }
}
