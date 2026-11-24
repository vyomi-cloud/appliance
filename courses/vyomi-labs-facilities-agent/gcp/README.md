# Facilities agent on Google Cloud

The finished project from the Vyomi Labs course **Build the Enterprise Facilities agent on Google Cloud**: an enterprise agentic AI application, built in 13 layers and run against the Vyomi Google Cloud simulator at no cloud cost.

Every file in [`app/`](app) is the exact code the course shows and deploys, in the same order.

## Run it

1. Start your Vyomi simulator (Nano with the tunnel, a Mesh, or the appliance) and copy its endpoint settings into `.env` (see `.env.example`).
2. `pip install -r requirements.txt`
3. `./run_all.sh` for every chapter, or follow one chapter at a time:

| Chapter | Layer | Steps |
|---|---|---|
| 1 | [Models](chapters/01-models.md) | 4 |
| 2 | [Agent Runtime](chapters/02-agent-runtime.md) | 7 |
| 3 | [Tools](chapters/03-tools.md) | 9 |
| 4 | [Knowledge Pipeline](chapters/04-knowledge-pipeline.md) | 10 |
| 5 | [Knowledge Search (RAG)](chapters/05-knowledge-search-rag.md) | 5 |
| 6 | [Response Generation](chapters/06-response-generation.md) | 7 |
| 7 | [Agent Memory](chapters/07-agent-memory.md) | 5 |
| 8 | [Agent Gateway](chapters/08-agent-gateway.md) | 7 |
| 9 | [Actions and Approval](chapters/09-actions-and-approval.md) | 6 |
| 10 | [Access and Perimeter](chapters/10-access-and-perimeter.md) | 6 |
| 11 | [Channels and Input Guardrails](chapters/11-channels-and-input-guardrails.md) | 3 |
| 12 | [AgentOps and Observability](chapters/12-agentops-and-observability.md) | 6 |
| 13 | [Governance and Security](chapters/13-governance-and-security.md) | 5 |
