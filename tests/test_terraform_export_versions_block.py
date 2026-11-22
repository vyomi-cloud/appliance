"""versions.tf of a Terraform export must be valid HCL: `required_providers` is a nested block, not an attribute."""
from core.terraform_export import terraform_hcl_files


def test_required_providers_is_a_block_not_an_attribute():
    files = terraform_hcl_files({"terraform_json": {"terraform": {
        "required_version": ">= 1.6.0",
        "required_providers": {"aws": {"source": "hashicorp/aws", "version": "~> 5.0"}}}}})
    v = files["versions.tf"]
    assert "required_providers {" in v
    assert "required_providers = " not in v
    assert 'required_version = ">= 1.6.0"' in v
    assert 'source = "hashicorp/aws"' in v


def test_empty_terraform_meta_still_renders():
    assert "terraform {}" in terraform_hcl_files({"terraform_json": {}})["versions.tf"]
