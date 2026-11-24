# Facilities agent on Google Cloud

The finished project from the Vyomi Labs course **Build the Enterprise Facilities agent on Google Cloud**: an enterprise agentic AI application, built in 13 layers and run against the Vyomi Google Cloud simulator at no cloud cost.

Each layer has its own folder with the exact code the course shows and deploys, and a README that explains it.

## Run it

1. Start your Vyomi simulator (Nano with the tunnel, a Mesh, or the appliance) and copy its endpoint settings into `.env` (see `.env.example`).
2. `pip install -r requirements.txt`
3. `./run_all.sh` for every layer, or `./run_all.sh 7` for one layer.

| Layer | Folder | Steps |
|---|---|---|
| 1. Models | [01-models/](01-models) | 4 |
| 2. Agent Runtime | [02-agent-runtime/](02-agent-runtime) | 7 |
| 3. Tools | [03-tools/](03-tools) | 9 |
| 4. Knowledge Pipeline | [04-knowledge-pipeline/](04-knowledge-pipeline) | 10 |
| 5. Knowledge Search (RAG) | [05-knowledge-search-rag/](05-knowledge-search-rag) | 5 |
| 6. Response Generation | [06-response-generation/](06-response-generation) | 7 |
| 7. Agent Memory | [07-agent-memory/](07-agent-memory) | 5 |
| 8. Agent Gateway | [08-agent-gateway/](08-agent-gateway) | 7 |
| 9. Actions and Approval | [09-actions-and-approval/](09-actions-and-approval) | 6 |
| 10. Access and Perimeter | [10-access-and-perimeter/](10-access-and-perimeter) | 6 |
| 11. Channels and Input Guardrails | [11-channels-and-input-guardrails/](11-channels-and-input-guardrails) | 3 |
| 12. AgentOps and Observability | [12-agentops-and-observability/](12-agentops-and-observability) | 6 |
| 13. Governance and Security | [13-governance-and-security/](13-governance-and-security) | 5 |
