# Azure lab gaps and honest limits

Nothing here is a hidden failure: every published block passed `python -m vyomilabs.labrun azure 10 3 7 12 6 11 9 4 5 1 2 8 13`, except the one marked BLOCKED.

## BLOCKED locally (needs a container runtime)
- Chapter 3, `call_container_app.py`: the app and environment are created through ARM (passes), but the simulator answers `503 NoRunningReplica` on the ingress unless the appliance's Docker runtime hook runs the `vyomi/python-app` image. Marked `needs_runtime=True`. The app logic itself was checked separately in-process (turn counters 1, 2 for one session and 1 for another).

## Left out (not a simulator bug; the service or course scope does not cover it)
- Chapter 11, masking personal data on output: Azure AI Content Safety only flags harmful text. PII redaction is Azure AI Language PII detection, which the simulator does not provide. The chapter says so and does not claim masking.

## Workarounds the blocks state plainly
- Chapter 1, user sign-in: `azure-identity` `UsernamePasswordCredential` (MSAL) drops the port from the user-realm discovery URL on a local address, so the block calls the tenant `/oauth2/v2.0/token` password grant directly. Application sign-in uses the real `ClientSecretCredential`.
- Chapter 13, Key Vault: the vault URI ARM reports is the simulator's console path form; `KeyClient` is given the simulator https host with `verify_challenge_resource=False` (documented SDK option for non `*.vault.azure.net` hosts).
- Chapter 7 / 12, AI Search: ARM advertises `https://<name>.search.windows.net`, which the simulator does not serve; `azdata.search_endpoint()` falls back to the simulator's path form. Functions reach the simulator over its plain-http address.
- Chapter 4, APIM policy expression: the `Claims["azp"].FirstOrDefault()` form is used (real APIM claims are string arrays).

## Not enforced / simplified in the simulator (stated in the chapter text)
- WAF policies are stored and read back; there is no layer-7 firewall engine (chapter 1).
- Content Safety and the RAI content filter are deterministic rules, not Microsoft classifiers (chapters 2, 11).
- The model is the repo's deterministic test stub (`tools/llm_stub`): chat replies are fixed/echoed, the semantic ranker and embeddings are simplified. Chapter 9 therefore proves thread mechanics, not model recall.
- Key Vault access policies / RBAC are not evaluated (chapter 13).
- No managed Azure long-term memory API exists (chapter 9 builds it on Table storage and probes that the routes 404). Hosted agent (chapter 3) and approval (chapter 5) are assembled from real services, not a single managed one; Cedar does not exist on Azure, so APIM policy expressions are used (chapter 4).
