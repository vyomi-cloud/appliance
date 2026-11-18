resource "azurerm_log_analytics_workspace" "core" {
  name                = "law-endurance-core"
  resource_group_name = var.rg_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_application_insights" "core" {
  name                = "appi-endurance-core"
  resource_group_name = var.rg_name
  location            = var.location
  workspace_id        = azurerm_log_analytics_workspace.core.id
  application_type    = "web"
}

resource "azurerm_monitor_action_group" "ops" {
  name                = "ag-endurance-ops"
  resource_group_name = var.rg_name
  short_name          = "ops"
  email_receiver {
    name          = "oncall"
    email_address = "oncall@vyomi.test"
  }
}

resource "azurerm_app_configuration" "core" {
  name                = "appcs-endurance-core"
  resource_group_name = var.rg_name
  location            = var.location
  sku                 = "standard"
}
