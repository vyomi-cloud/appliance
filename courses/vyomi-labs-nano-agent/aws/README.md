# Build Your First Agent (AWS, Nano)

The finished project from the Vyomi Labs course **Vyomi Labs: Build Your First Agent (Nano)**: a help-desk agent that runs a small language model in your browser, uses three tools (search a handbook in S3, look up a record in DynamoDB, file a ticket to SQS), remembers, refuses what the documents do not support, and deploys as a Lambda function with a graded evaluation.

Each chapter has its own folder with the exact code the course shows and deploys. Where a file changes in a later chapter (`tools.py`, `agent.py`), each chapter keeps its own version.

## Run it

1. Start Vyomi Nano and load a model (the course tells you when). Copy the endpoint settings into `.env`.
2. `pip install -r requirements.txt`
3. `./run_all.sh`, or `./run_all.sh 3` for one chapter.

| Chapter | Folder | Steps |
|---|---|---|
| 1. The agent loop | [01-the-agent-loop/](01-the-agent-loop) | 2 |
| 2. A model in your browser | [02-a-model-in-your-browser/](02-a-model-in-your-browser) | 4 |
| 3. Tools | [03-tools/](03-tools) | 7 |
| 4. Memory | [04-memory/](04-memory) | 3 |
| 5. Knowledge (RAG) | [05-knowledge-rag/](05-knowledge-rag) | 4 |
| 6. Guardrails | [06-guardrails/](06-guardrails) | 4 |
| 7. Deploy and evaluate | [07-deploy-and-evaluate/](07-deploy-and-evaluate) | 4 |

## Next

This course is the free, in-browser path. For hardening an agent for an enterprise (identity, approvals, audit, managed runtimes) continue with the Vyomi Labs Enterprise Facilities agent course.
