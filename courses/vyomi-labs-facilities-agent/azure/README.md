# Facilities agent on Microsoft Azure

The finished project from the Vyomi Labs course **Build the Enterprise Facilities agent on Microsoft Azure (Mesh, enterprise)**: an enterprise agentic AI application, built in 14 layers and run against the Vyomi Microsoft Azure simulator at no cloud cost.

Each layer has its own folder with the exact code the course shows and deploys, and a README that explains it.

## Run it

1. Start your Vyomi simulator (Nano with the tunnel, a Mesh, or the appliance) and copy its endpoint settings into `.env` (see `.env.example`).
2. `pip install -r requirements.txt`
3. `./run_all.sh` for every layer, or `./run_all.sh 7` for one layer.

| Layer | Folder | Steps |
|---|---|---|
| 1. Models | [01-models/](01-models) | 6 |
| 2. Agent Runtime | [02-agent-runtime/](02-agent-runtime) | 7 |
| 3. Tools | [03-tools/](03-tools) | 11 |
| 4. Design the RAG | [04-design-the-rag/](04-design-the-rag) | 3 |
| 5. Knowledge Pipeline | [05-knowledge-pipeline/](05-knowledge-pipeline) | 12 |
| 6. Knowledge Search (RAG) | [06-knowledge-search-rag/](06-knowledge-search-rag) | 6 |
| 7. Response Generation | [07-response-generation/](07-response-generation) | 6 |
| 8. Agent Memory | [08-agent-memory/](08-agent-memory) | 5 |
| 9. Agent Gateway | [09-agent-gateway/](09-agent-gateway) | 6 |
| 10. Actions and Approval | [10-actions-and-approval/](10-actions-and-approval) | 7 |
| 11. Access and Perimeter | [11-access-and-perimeter/](11-access-and-perimeter) | 5 |
| 12. Channels and Input Guardrails | [12-channels-and-input-guardrails/](12-channels-and-input-guardrails) | 4 |
| 13. AgentOps and Observability | [13-agentops-and-observability/](13-agentops-and-observability) | 9 |
| 14. Governance and Security | [14-governance-and-security/](14-governance-and-security) | 8 |
