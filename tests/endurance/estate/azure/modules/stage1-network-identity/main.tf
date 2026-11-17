resource "azurerm_resource_group" "core" {
  name     = "cloudlearn-rg-endurance"
  location = "eastus"
  tags     = { env = "endurance", app = "vyomi" }
}

resource "azurerm_virtual_network" "core" {
  name                = "vnet-core"
  resource_group_name = azurerm_resource_group.core.name
  location            = azurerm_resource_group.core.location
  address_space       = ["10.50.0.0/16"]
}

resource "azurerm_subnet" "web" {
  name                 = "snet-web"
  resource_group_name  = azurerm_resource_group.core.name
  virtual_network_name = azurerm_virtual_network.core.name
  address_prefixes     = ["10.50.1.0/24"]
}

resource "azurerm_network_security_group" "web" {
  name                = "nsg-web"
  resource_group_name = azurerm_resource_group.core.name
  location            = azurerm_resource_group.core.location
  security_rule {
    name                       = "allow-https"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "web" {
  subnet_id                 = azurerm_subnet.web.id
  network_security_group_id = azurerm_network_security_group.web.id
}

resource "azurerm_subnet" "data" {
  name                 = "snet-data"
  resource_group_name  = azurerm_resource_group.core.name
  virtual_network_name = azurerm_virtual_network.core.name
  address_prefixes     = ["10.50.2.0/24"]
}

resource "azurerm_application_security_group" "app" {
  name                = "asg-app"
  resource_group_name = azurerm_resource_group.core.name
  location            = azurerm_resource_group.core.location
}

resource "azurerm_route_table" "core" {
  name                = "rt-core"
  resource_group_name = azurerm_resource_group.core.name
  location            = azurerm_resource_group.core.location
  route {
    name           = "to-internet"
    address_prefix = "0.0.0.0/0"
    next_hop_type  = "Internet"
  }
}

resource "azurerm_public_ip" "core" {
  name                = "pip-core"
  resource_group_name = azurerm_resource_group.core.name
  location            = azurerm_resource_group.core.location
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_dns_zone" "core" {
  name                = "endurance.vyomi.test"
  resource_group_name = azurerm_resource_group.core.name
}

resource "azurerm_dns_a_record" "www" {
  name                = "www"
  zone_name           = azurerm_dns_zone.core.name
  resource_group_name = azurerm_resource_group.core.name
  ttl                 = 300
  records             = ["10.50.1.10"]
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-app"
  resource_group_name = azurerm_resource_group.core.name
  location            = azurerm_resource_group.core.location
}

data "azurerm_client_config" "current" {}

resource "azurerm_role_assignment" "app_reader" {
  scope                = azurerm_resource_group.core.id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_key_vault" "core" {
  name                       = "kv-endurance-core"
  resource_group_name        = azurerm_resource_group.core.name
  location                   = azurerm_resource_group.core.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  rbac_authorization_enabled = true
}
