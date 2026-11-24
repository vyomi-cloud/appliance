# Layer 5: Knowledge Search (RAG)

_Ranked retrieval that keeps the source of every passage_

**What you build:** Retrieve the right passages for a question, rank them, and keep the source so answers can cite it.

## Code, in order

### 1. Search the knowledge base

Retrieve is the vector-search call. Ask the question an engineer would ask and check the boiler SOP ranks first, then an HVAC question, and that every hit carries the S3 location the answer will cite. Needs the knowledge base from chapter 12.

- File: [`search.py`](./search.py)
- Run: `python search.py` (or `./run_all.sh 5` from the project root)
- You should see: `every hit has text and a source: True`

### 2. Rerank the hits

Vector similarity is a first pass. Rerank re-scores the candidates against the question with a reranking model and keeps the best two.

- File: [`rerank.py`](./rerank.py)
- Run: `python rerank.py` (or `./run_all.sh 5` from the project root)
- You should see: `rerank returned 2 results`

### 3. Write the knowledge-search tool

The agents never call Retrieve themselves; they call this read-only Lambda tool. It accepts a plain event or an API Gateway proxy event (chapter 1 puts it behind an API). The knowledge base id comes from the function's environment.

- File: [`kb_search.py`](./kb_search.py)

### 4. Deploy and call the tool

Deploys `facilities-kb-search` with the knowledge base id in its environment, then calls it the way an agent will.

- File: [`deploy_kb_search.py`](./deploy_kb_search.py)
- Run: `python deploy_kb_search.py` (or `./run_all.sh 5` from the project root)
- You should see: `first source: s3://facilities-docs/docs/boiler-sop.md`

## It works when

- boiler SOP ranks first
- HVAC manual ranks first for an AHU question
- results carry source locations
