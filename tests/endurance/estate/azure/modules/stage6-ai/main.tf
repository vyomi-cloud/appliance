resource "azurerm_cognitive_account" "openai" {
  name                  = "oai-endurance-core"
  resource_group_name   = var.rg_name
  location              = var.location
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "oai-endurance-core"
}

resource "azurerm_cognitive_deployment" "chat" {
  name                 = "gpt-4o-mini"
  cognitive_account_id = azurerm_cognitive_account.openai.id
  model {
    format  = "OpenAI"
    name    = "gpt-4o-mini"
    version = "2024-07-18"
  }
  sku {
    name     = "Standard"
    capacity = 10
  }
}

resource "azurerm_cognitive_account" "language" {
  name                = "cog-endurance-language"
  resource_group_name = var.rg_name
  location            = var.location
  kind                = "TextAnalytics"
  sku_name            = "S"
}
