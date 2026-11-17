variable "project" {}
variable "kms_key_id" {}
variable "bucket" {}

resource "random_id" "ai" { byte_length = 3 }

resource "google_vertex_ai_dataset" "docs" {
  display_name        = "vyomi-docs-${random_id.ai.hex}"
  metadata_schema_uri = "gs://google-cloud-aiplatform/schema/dataset/metadata/text_1.0.0.yaml"
  region              = "us-central1"
  labels              = { env = "endurance" }
}

resource "google_vertex_ai_endpoint" "serve" {
  name         = "vyomi-serve-${random_id.ai.hex}"
  display_name = "vyomi-serve"
  description  = "Reference estate prediction endpoint"
  location     = "us-central1"
  labels       = { env = "endurance" }
}

resource "google_vertex_ai_tensorboard" "tb" {
  display_name = "vyomi-tb"
  region       = "us-central1"
}

resource "google_vertex_ai_metadata_store" "meta" {
  name        = "vyomi-meta-${random_id.ai.hex}"
  description = "Reference estate metadata store"
  region      = "us-central1"
}

resource "google_vertex_ai_feature_online_store" "fos" {
  name   = "vyomi_fos_${random_id.ai.hex}"
  region = "us-central1"
  bigtable {
    auto_scaling {
      min_node_count         = 1
      max_node_count         = 1
      cpu_utilization_target = 50
    }
  }
}

resource "google_vertex_ai_index" "idx" {
  region       = "us-central1"
  display_name = "vyomi-index"
  description  = "Reference estate vector index"
  metadata {
    contents_delta_uri = "gs://${var.bucket}/index"
    config {
      dimensions                  = 4
      approximate_neighbors_count = 10
      distance_measure_type       = "DOT_PRODUCT_DISTANCE"
      algorithm_config {
        tree_ah_config {
          leaf_node_embedding_count    = 500
          leaf_nodes_to_search_percent = 7
        }
      }
    }
  }
  index_update_method = "BATCH_UPDATE"
}

resource "google_vertex_ai_index_endpoint" "ie" {
  display_name            = "vyomi-index-endpoint"
  region                  = "us-central1"
  public_endpoint_enabled = true
}
