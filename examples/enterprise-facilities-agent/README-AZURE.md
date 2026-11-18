# Facilities agent on Azure (Azure SDKs against the Vyomi simulator)

Same 13 components as the AWS and GCP apps, written with the real, unmodified Azure client libraries (see `requirements-azure.txt`).

Run: `python run_e2e.py --cloud azure --out results/` (starts the real appliance `server.py` in-process on an https port with a local CA and a plain-http side port; exit 0 only if 13/13 PASS).
Optional: `--start-azurite` starts a real Azurite container (unique name, removed by exact name) and sets `VYOMI_AZURE_REAL_BACKENDS=1` so the Table ledger runs on a real engine.
Model steps need `VYOMI_LLM_ENDPOINT`; without a model they are BLOCKED(local model).

Honesty notes
- Approval (C5) is ASSEMBLED: Table ledger + Service Bus topic + Function, not a workflow orchestrator. C3 is assembled (Foundry Agents + LangGraph in a Container App).
- Service Bus and Cosmos are Vyomi cores (Service Bus has a real AMQP 1.0 wire); only Table can run on a real engine (Azurite).
- C9 long-term memory is an application pattern on Table storage; Azure has no managed memory API.
- No Cedar on Azure: APIM policy expressions are the substitute.
- Key Vault SDK is used with `verify_challenge_resource=False` because the vault host is not `*.vault.azure.net`.
