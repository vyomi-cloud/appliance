resource "aws_s3_bucket" "uploads" {
  bucket = "uploads"
}

resource "aws_sqs_queue" "jobs" {
  name = "jobs"
}

resource "aws_dynamodb_table" "sessions" {
  name = "sessions"
}

resource "google_storage_bucket" "assets" {
  name = "assets"
}

resource "google_pubsub_topic" "events" {
  name = "events"
}

resource "azurerm_storage_account" "main" {
  name = "main"
}

resource "azurerm_cosmosdb_account" "db" {
  name = "db"
}

resource "azurerm_servicebus_queue" "work" {
  name = "work"
}
