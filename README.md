# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-11-23T23:18:15+00:00

Tracking 4299 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**3 change(s), 0 actionable.**
- · `announcement` API security with WAF ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/api-security-with-waf/))
- · `announcement` AWS WAF announces automated discovery and protection for LLM, MCP, and A2A endpoints using Amazon Bedrock Guardrails ([link](https://aws.amazon.com/about-aws/whats-new/2026/11/waf-ai-endpoint-discovery-protection/))
- · `spec-commit` Azure cognitiveservices: removing api version pin (#48447) ([link](https://github.com/Azure/azure-rest-api-specs/commit/c24ede05d3b9a52107bd12907d29f1f6d9fd1098))

Sources that failed this run (6): maven/com.google.cloud:google-cloud-storage: The read operation timed out; maven/com.google.cloud:google-cloud-pubsub: The read operation timed out; maven/com.azure:azure-security-keyvault-secrets: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-appconfiguration: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-cognitiveservices: The read operation timed out; maven/com.azure.resourcemanager:azure-resourcemanager-loganalytics: The read operation timed out

Filed 0 backlog issue(s) labelled `upstream-drift`; 0 pending.
