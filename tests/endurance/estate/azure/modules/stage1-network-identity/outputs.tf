output "rg_name" { value = azurerm_resource_group.core.name }
output "location" { value = azurerm_resource_group.core.location }
output "rg_id" { value = azurerm_resource_group.core.id }
output "identity_id" { value = azurerm_user_assigned_identity.app.id }
output "identity_principal_id" { value = azurerm_user_assigned_identity.app.principal_id }
output "key_vault_id" { value = azurerm_key_vault.core.id }
output "web_subnet_id" { value = azurerm_subnet.web.id }
