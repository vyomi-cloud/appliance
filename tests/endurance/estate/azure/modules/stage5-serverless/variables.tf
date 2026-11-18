variable "rg_name" {}
variable "location" {}
variable "storage_account_name" {}
variable "storage_account_key" {
  sensitive = true
}
