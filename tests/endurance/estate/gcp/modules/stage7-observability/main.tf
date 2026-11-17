variable "project" {}
variable "bucket" {}
variable "topic_id" {}

resource "google_logging_project_bucket_config" "ops" {
  project        = var.project
  location       = "global"
  retention_days = 30
  bucket_id      = "vyomi-ops"
}

resource "google_logging_metric" "errors" {
  name   = "vyomi-error-count"
  filter = "severity>=ERROR"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }
}

resource "google_logging_project_sink" "to_bucket" {
  name                   = "vyomi-archive"
  destination            = "storage.googleapis.com/${var.bucket}"
  filter                 = "severity>=WARNING"
  unique_writer_identity = true
}

resource "google_monitoring_notification_channel" "email" {
  display_name = "Vyomi on-call"
  type         = "email"
  labels       = { email_address = "oncall@example.com" }
}

resource "google_monitoring_alert_policy" "cpu" {
  display_name = "Vyomi high CPU"
  combiner     = "OR"
  conditions {
    display_name = "cpu > 80%"
    condition_threshold {
      filter          = "metric.type=\"compute.googleapis.com/instance/cpu/utilization\" AND resource.type=\"gce_instance\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0.8
      duration        = "300s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email.name]
}

resource "google_monitoring_uptime_check_config" "web" {
  display_name = "vyomi-web-uptime"
  timeout      = "10s"
  period       = "300s"
  http_check {
    path = "/"
    port = 443
    use_ssl = true
  }
  monitored_resource {
    type   = "uptime_url"
    labels = { project_id = var.project, host = "example.com" }
  }
}

resource "google_monitoring_dashboard" "main" {
  dashboard_json = jsonencode({
    displayName = "Vyomi estate"
    gridLayout = { widgets = [{ title = "CPU", xyChart = { dataSets = [{ timeSeriesQuery = { timeSeriesFilter = { filter = "metric.type=\"compute.googleapis.com/instance/cpu/utilization\"" } } }] } }] }
  })
}
