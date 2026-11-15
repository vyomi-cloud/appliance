# Spike: real azurerm against the simulator's ARM core. Passing = apply, then a no-change plan.
terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
  }
}
variable "metadata_host" { default = "host.docker.internal:8443" }
provider "azurerm" {
  features {}
  metadata_host               = var.metadata_host
  subscription_id             = "00000000-0000-0000-0000-cloudlearn01"
  tenant_id                   = "00000000-0000-0000-0000-0000000000aa"
  client_id                   = "00000000-0000-0000-0000-0000000000bb"
  client_secret               = "vyomi"
  resource_provider_registrations = "none"
}
resource "azurerm_resource_group" "endurance" {
  name     = "rg-endurance-spike"
  location = "eastus"
}
resource "azurerm_virtual_network" "endurance" {
  name                = "vnet-endurance"
  resource_group_name = azurerm_resource_group.endurance.name
  location            = azurerm_resource_group.endurance.location
  address_space       = ["10.40.0.0/16"]
}
