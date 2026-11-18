# v4/az-ref-app: Azure implementation of the 13-component reference application

Lane 1 of the Azure 13/13 build. Base: `origin/v4-on-main`.

## Changes
- `examples/enterprise-facilities-agent/facilities/azure/` (13 components, `AzCtx`, IO adapter, function sources, in-process https server, Azurite helper), `run_e2e.py --cloud azure` (+ `--start-azurite`), `README-AZURE.md`, `requirements-azure.txt`, `tests/conformance/test_azure_ref_app.py` (model-free). AWS and GCP behaviour unchanged (harness only gained a detail-length env).
- Results: `results/azure-e2e-result.json` (trunk) and `azure-e2e-result-integ.json` (local merge `v4/az-ref-app-integ` = this branch + the five lane tips at the time).

## Design decisions
- Real Azure SDKs only; a gap is BLOCKED(lane) via `classify()` (named lane), never a hand-rolled fallback or a pass.
- https with a local CA for SDKs that refuse plain http (Key Vault, identity); a plain-http port serves call-backs, AMQP and the function sandbox.
- Function calls use the host key returned by ARM `list_host_keys` (`x-functions-key`); APIM forwards it by policy.
- Approval assembled; memory is an app pattern; no Cedar (APIM expressions).

## Status (observed, no model)
Trunk: 0 PASS, 13 BLOCKED, 0 FAIL. Integ: 0 PASS, 11 BLOCKED, 2 FAIL (APIM 401 on tool calls: see open issues). Many steps inside each component PASS.

## Open issues
- Integ: ARM `list_host_keys` returns keys from `arm_ext_core` `_hostkeys`, but the front door (`azure_functions_host`) checks `webapp_core` `_host` keys: every keyed function call is 401 (BLOCKED az-ref-runtime). The three APIM FAILs on integ are the same 401 forwarded or a gateway issue, not yet separated.
- AI Search `indexes('facilities-kb')` not routed on integ (ai/messaging), `/openai` KQL tables (AppDependencies), WAF types, MCP API, Container App ingress (no lane), Key Vault `kid` vault host (no lane), model steps.
