# Upstream watch — AWS / GCP / Azure changes

Hourly diff of the real clouds for the services Vyomi simulates. Actionable changes are filed as [`upstream-drift` issues](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) and worked by the conformance agent. Every run: [log.md](log.md).

### Upstream watch — 2026-10-30T21:47:55+00:00

Tracking 4252 AWS + GCP operations, 18 Azure spec areas, 53 SDK/CLI packages and 3 lifecycle feeds.

**4 change(s), 1 actionable.**
- 🔧 `spec-commit` Azure compute: WorkloadManager: correct 2026-11-01-preview resource contract (#47558) ([link](https://github.com/Azure/azure-rest-api-specs/commit/411fb227a905864f972d26ab88b21ef69e1f67b2))
- · `announcement` Amazon Bedrock expands API support and introduces Cross Region Inferencing for OpenAI models in AWS GovCloud (US) ([link](https://aws.amazon.com/about-aws/whats-new/2026/10/bedrock-openai-runtime-govcloud/))
- · `spec-commit` Azure storage: STG105 add handwritten swaggers for new api version (#47761) ([link](https://github.com/Azure/azure-rest-api-specs/commit/418fc8bf77b536fe624f81f60212aa5a12569354))
- · `spec-commit` Azure storage: Storage STG105 (TypeSpec) (#47158) ([link](https://github.com/Azure/azure-rest-api-specs/commit/e92d56507558ffba90b5a9362d2ae4b64fdf4592))

Sources that failed this run (2): maven/com.azure:azure-cosmos: The read operation timed out; maven/com.azure:azure-data-appconfiguration: The read operation timed out

Filed 1 backlog issue(s) labelled `upstream-drift`; 0 pending.
