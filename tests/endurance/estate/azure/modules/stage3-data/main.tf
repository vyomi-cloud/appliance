resource "azurerm_storage_account" "data" {
  name                     = "stendurancedata"
  resource_group_name      = var.rg_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  tags                     = { env = "endurance" }
}

resource "azurerm_storage_container" "assets" {
  name                  = "assets"
  storage_account_id    = azurerm_storage_account.data.id
  container_access_type = "private"
}

resource "azurerm_cosmosdb_account" "core" {
  name                = "cosmos-endurance-core"
  resource_group_name = var.rg_name
  location            = var.location
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  consistency_policy { consistency_level = "Session" }
  geo_location {
    location          = var.location
    failover_priority = 0
  }
}

resource "azurerm_cosmosdb_sql_database" "app" {
  name                = "appdb"
  resource_group_name = var.rg_name
  account_name        = azurerm_cosmosdb_account.core.name
}

resource "azurerm_cosmosdb_sql_container" "orders" {
  name                  = "orders"
  resource_group_name   = var.rg_name
  account_name          = azurerm_cosmosdb_account.core.name
  database_name         = azurerm_cosmosdb_sql_database.app.name
  partition_key_paths   = ["/customerId"]
}

resource "azurerm_mssql_server" "core" {
  name                         = "sql-endurance-core"
  resource_group_name          = var.rg_name
  location                     = var.location
  version                      = "12.0"
  administrator_login          = "vyomiadmin"
  administrator_login_password = "Vyomi-Endurance-1!"
}

resource "azurerm_mssql_database" "app" {
  name      = "appdb"
  server_id = azurerm_mssql_server.core.id
  sku_name  = "S0"
}

resource "azurerm_mssql_firewall_rule" "allow_azure" {
  name             = "allow-azure"
  server_id        = azurerm_mssql_server.core.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}
