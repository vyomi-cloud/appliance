resource "azurerm_servicebus_namespace" "core" {
  name                = "sb-endurance-core"
  resource_group_name = var.rg_name
  location            = var.location
  sku                 = "Standard"
}

resource "azurerm_servicebus_queue" "orders" {
  name         = "orders"
  namespace_id = azurerm_servicebus_namespace.core.id
}

resource "azurerm_servicebus_topic" "events" {
  name         = "events"
  namespace_id = azurerm_servicebus_namespace.core.id
}

resource "azurerm_servicebus_subscription" "audit" {
  name               = "audit"
  topic_id           = azurerm_servicebus_topic.events.id
  max_delivery_count = 10
}

resource "azurerm_eventgrid_topic" "core" {
  name                = "egt-endurance-core"
  resource_group_name = var.rg_name
  location            = var.location
}
