# Layer 5: Knowledge Search (RAG)

_Ranked retrieval that keeps the source of every passage_

**What you build:** Retrieve the right passages for a question, rank them, and keep the source so answers can cite it.

## Code, in order

### 1. Install the libraries

Chapter 6 retrieves passages from the knowledge base built in chapter 12 (the corpus facilities-kb) and exposes search as a read-only tool using the functions.py deploy helper from chapter 7.

- File: [`install_6.sh`](./install_6.sh)

### 2. Rank passages for a question

retrieveContexts on the RAG Engine returns the top-k passages with a score and the gs:// source of each. Ask about the boiler, then about the AHU: the right document must come first each time. Retrieval here uses the simulator's lexical vectors without a real embedding model, so scores are indicative, not production-quality.

- File: [`search.py`](./search.py)
- Run: `python search.py` (or `./run_all.sh 5` from the project root)
- You should see: `every passage carries text and a gs:// source`

### 3. Check the ranking

A retrieval test you can keep: the boiler question must put the boiler SOP first and the AHU question must put the HVAC manual first.

- File: [`check_ranking.py`](./check_ranking.py)
- Run: `python check_ranking.py` (or `./run_all.sh 5` from the project root)
- You should see: `AHU question -> first hit is hvac-maintenance-manual.md`

### 4. Write the kb-search tool

The same search packaged as a read-only Cloud Run function, so an agent can call it. API Gateway (chapter 1) forwards the caller's verified identity in the X-Apigateway-Api-Userinfo header and the function echoes it as caller.

- File: [`kb_search_fn.py`](./kb_search_fn.py)

### 5. Deploy and call the kb-search tool

Deploys facilities-kb-search with the corpus name in its environment and calls it over HTTPS.

- File: [`deploy_kb_search.py`](./deploy_kb_search.py)
- Run: `python deploy_kb_search.py` (or `./run_all.sh 5` from the project root)
- You should see: `kb-search returned 3 cited results`

## It works when

- boiler SOP ranks first
- HVAC manual ranks first
- contexts carry source URIs
