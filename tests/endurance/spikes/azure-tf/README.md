# Spike: real `azurerm` against the simulator (PASSED 2026-11-15)

Result: OpenTofu 1.13 + `hashicorp/azurerm ~> 4.0` ran the full Endurance cycle against the simulator's ARM core:
init, plan, apply (resource group + virtual network), **no-change re-plan**, destroy, re-apply, destroy.

What `azurerm` needs that the simulator did not already serve (all provided by `front.py`, an HTTPS front in front of the ARM core):
1. TLS with a trusted cert: `SSL_CERT_FILE` in a Linux container (macOS Go ignores it, so run via `run.sh`, which is also what CI does).
2. `GET /metadata/endpoints` returning a full cloud-environment document (including `microsoftGraphResourceId`, storage suffix and the `*ResourceId` fields).
3. `POST /<tenant>/oauth2/v2.0/token` returning a structurally valid, unsigned JWT (the provider reads `tid`/`oid`/`appid`, never verifies the signature).
4. Provider setting `metadata_host`, and `resource_provider_registrations = "none"`.
5. The simulator's only subscription id is `00000000-0000-0000-0000-cloudlearn01`; azurerm accepted it.

Findings for the real estate:
- Resource group create AND delete each take ~20 s (consistent over three runs); everything else is instant. Likely LRO polling cadence: investigate before the full estate (hundreds of RGs would dominate the run).
- The front must move into the appliance/Mesh image (it is a spike script today) so the Terraform gate does not need a side process.

Run: `python3 consoles/dev_server.py --port 8740 &`, `python3 front.py --cert cert.pem --key key.pem --host host.docker.internal:8443 &`, `./run.sh init|plan|apply -auto-approve`.
(`cert.pem`/`key.pem` are generated locally: `openssl req -x509 -newkey rsa:2048 -nodes -days 30 -keyout key.pem -out cert.pem -subj /CN=vyomi-endurance -addext subjectAltName=DNS:host.docker.internal,DNS:localhost`.)
