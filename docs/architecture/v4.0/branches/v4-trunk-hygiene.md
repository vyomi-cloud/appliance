# v4/trunk-hygiene

Base: origin/v4-on-main. Regenerated wasm/service-inventory.json with scripts/gen_service_inventory.py (adds aws/tfstudio and gcp/infra-manager; 86 -> 88 services). test_service_inventory.py passes.

Capabilities: tests/conformance/test_capabilities.py has the same 84 failing ids on trunk and on origin/v4/iam-pickers-integ (none new).
