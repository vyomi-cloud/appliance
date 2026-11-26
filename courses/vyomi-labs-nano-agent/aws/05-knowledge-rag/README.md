# Chapter 5: Knowledge (RAG)

_An index in S3, a hybrid search and a measured threshold that decides when the handbook cannot answer_

**What you build:** Replace the keyword search with retrieval that blends keywords and embeddings, and measure it, including when it must find nothing.

## Code, in order

### 1. Write retrieval

Chunking, embedding, the index in S3 and three search modes: keyword, dense and hybrid. The hybrid score doubles as the evidence test.

- File: [`rag.py`](./rag.py)

### 2. Build the index

Embed every passage and save the index next to the documents.

- File: [`build_index.py`](./build_index.py)
- Run: `python build_index.py`
- You should see: `index built`

### 3. Measure retrieval

Thirteen questions the handbook answers and six it does not. For each mode: how often the right document comes first, and the highest score any unsupported question reaches.

- File: [`measure_retrieval.py`](./measure_retrieval.py)
- Run: `python measure_retrieval.py`
- You should see: `retrieval ok`

### 4. Use it in the tools

search_docs now calls the hybrid search and returns nothing when the best score is under the threshold.

- File: [`tools.py`](./tools.py)

## It works when

- the index is built and stored in S3
- hybrid search finds the right document for thirteen questions
- no unsupported question scores above the threshold
- the tools use the new search
