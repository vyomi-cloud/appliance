# Layer 5: Knowledge Pipeline

_Documents flowing into a searchable knowledge base, re-indexed on every upload_

**What you build:** Turn documents into searchable knowledge, and re-index automatically when a new document lands.

## Code, in order

### 1. Upload the documents

The four source documents (boiler, elevator and fire-safety SOPs and the AHU maintenance manual) go to the docs bucket under `docs/`. Run this after chapter 10; the bucket is shared with the agent code zip from chapter 3.

- File: [`upload_docs.py`](./upload_docs.py)
- Run: `python upload_docs.py` (or `./run_all.sh 5` from the project root)
- You should see: `uploaded 4 documents`

### 2. Create the vector store

The knowledge base needs a vector database: an OpenSearch Serverless collection of type VECTORSEARCH. Real AWS requires an encryption policy first, so you create that too.

- File: [`vector_store.py`](./vector_store.py)
- Run: `python vector_store.py` (or `./run_all.sh 5` from the project root)
- You should see: `collection facilities-kb`

### 3. Create the knowledge base and its data source

The knowledge base turns text into vectors with the embedding model this simulator hosts and stores them in the collection. The data source points at `docs/` in the bucket and cuts documents into 200-token chunks with 10% overlap.

- File: [`knowledge_base.py`](./knowledge_base.py)
- Run: `python knowledge_base.py` (or `./run_all.sh 5` from the project root)
- You should see: `data source`

### 4. Ingest the documents

StartIngestionJob reads every document, chunks it, embeds each chunk and writes the vectors. The script polls GetIngestionJob until the job finishes.

- File: [`ingest.py`](./ingest.py)
- Run: `python ingest.py` (or `./run_all.sh 5` from the project root)
- You should see: `ingestion COMPLETE`

### 5. Write the re-index function

When a new document lands in the bucket, this function starts another ingestion job so the knowledge base never goes stale.

- File: [`ingest_docs.py`](./ingest_docs.py)

### 6. Wire the S3 event to the function

Deploys the function, lets S3 invoke it, and subscribes the bucket's `docs/` prefix to ObjectCreated events. Then it uploads a new bulletin and waits for a second ingestion job to appear without you starting it.

- File: [`event_driven.py`](./event_driven.py)
- Run: `python event_driven.py` (or `./run_all.sh 5` from the project root)
- You should see: `started ingestion job #2`

## It works when

- documents are in the bucket
- facilities-kb exists
- an ingestion job is COMPLETE
- a new upload starts a new job
