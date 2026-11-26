# Layer 6: Knowledge Search (RAG)

_Ranked retrieval that keeps the source of every passage_

**What you build:** Retrieve the right passages for a question, rank them, and keep the source so answers can cite it.

## Code, in order

### 1. Install the libraries

Chapter 6 queries the `facilities-kb` index that chapter 12 filled: full-text (BM25), vector, hybrid and semantic queries with `azure-search-documents`, and embeddings from your `embed` deployment (chapter 10). It uses `azlab.py`, `azdata.py` and `kb_index.py`.

- File: [`install6.sh`](./install6.sh)

### 2. Look at the index you built

Read the index back: the fields, the vector field dimensions and the semantic configuration. This is what decides which kinds of query the index can answer.

- File: [`inspect_index.py`](./inspect_index.py)
- Run: `python inspect_index.py` (or `./run_all.sh 6` from the project root)
- You should see: `vector dimensions:`

### 3. Embed the documents and store the vectors

Chapter 12's indexer loaded the text (the four SOPs plus the water-leak SOP you uploaded in its last block, five documents in all). Vector search needs one embedding per document: ask your `embed` deployment for the vectors, then `merge_documents` writes them into `content_vector` without touching the rest of the document. Embeddings come from the repo's deterministic test stub, so similarity is crude: real `text-embedding-3` vectors rank far better.

- File: [`embed_docs.py`](./embed_docs.py)
- Run: `python embed_docs.py` (or `./run_all.sh 6` from the project root)
- You should see: `embedded and merged 5 documents`

### 4. Write the retrieval helper

One function every later layer imports: `kb_search(query, mode)` returns ranked passages, each with its `source` so an answer can cite it. `mode` is `text`, `vector`, `hybrid` or `semantic`. A vector query sends the embedding of the question; a hybrid query sends both text and vector and the service fuses the two rankings (reciprocal rank fusion); a semantic query asks the semantic ranker to re-rank and returns a reranker score.

- File: [`kb.py`](./kb.py)

### 5. Run the four kinds of query

BM25 text search ranks the boiler SOP first for a boiler question and the HVAC manual first for an air-handler question. A vector query finds the boiler SOP from a differently worded question. Hybrid combines both. The semantic ranker adds a reranker score. Every hit carries its `source`, which is what makes citations possible.

- File: [`try_search.py`](./try_search.py)
- Run: `python try_search.py` (or `./run_all.sh 6` from the project root)
- You should see: `vector   what to do when boiler pressure is too high  -> boiler-sop.md
hybrid   fire alarm evacuation procedure              -> fire-safety-sop.md`

## It works when

- BM25 ranks correctly
- vector and hybrid queries work
- results carry source names
