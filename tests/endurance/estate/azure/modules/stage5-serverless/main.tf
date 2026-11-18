resource "azurerm_service_plan" "core" {
  name                = "asp-endurance-core"
  resource_group_name = var.rg_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = "B1"
}

resource "azurerm_linux_web_app" "api" {
  name                = "app-endurance-api"
  resource_group_name = var.rg_name
  location            = var.location
  service_plan_id     = azurerm_service_plan.core.id
  site_config {
    application_stack { node_version = "20-lts" }
  }
}

resource "azurerm_linux_function_app" "worker" {
  name                       = "func-endurance-worker"
  resource_group_name        = var.rg_name
  location                   = var.location
  service_plan_id            = azurerm_service_plan.core.id
  storage_account_name       = var.storage_account_name
  storage_account_access_key = var.storage_account_key
  site_config {
    application_stack { node_version = "20" }
  }
}
