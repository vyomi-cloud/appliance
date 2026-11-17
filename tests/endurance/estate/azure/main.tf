# Vyomi Reference Estate - Azure. One application, composed from stages (tests/endurance/estate/stages.json).
# Gate: `tests/endurance/run_estate.sh estate/azure host.docker.internal:<front-port>` (front.py = HTTPS front for the simulator's ARM).
terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
  }
}

# run_estate.sh passes -var=endpoint=<value>; for Azure this is the metadata host (host:port of the TLS front).
variable "endpoint" { default = "host.docker.internal:19114" }

provider "azurerm" {
  features {}
  metadata_host                   = var.endpoint
  subscription_id                 = "00000000-0000-0000-0000-cloudlearn01"
  tenant_id                       = "00000000-0000-0000-0000-0000000000aa"
  client_id                       = "00000000-0000-0000-0000-0000000000bb"
  client_secret                   = "vyomi"
  resource_provider_registrations = "none"
}

module "network_identity" {
  source = "./modules/stage1-network-identity"
}

module "data" {
  source   = "./modules/stage3-data"
  rg_name  = module.network_identity.rg_name
  location = module.network_identity.location
}
