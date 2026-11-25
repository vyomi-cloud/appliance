# Layer 5: Knowledge Pipeline

_Documents flowing into a searchable knowledge base, re-indexed on every upload_

**What you build:** Turn documents into searchable knowledge, and re-index automatically when a new document lands.

## Code, in order

### 1. Install the libraries

Chapter 12 turns documents into searchable knowledge. It uses Cloud Storage, Vertex AI RAG Engine, Pub/Sub (for the bucket notification), Eventarc and Cloud Functions. It relies on gcp.py (chapter 10) and functions.py (chapter 7).

- File: [`install_12.sh`](./install_12.sh)

### 2. Write the four documents

The corpus: three SOPs and one equipment manual, saved as docs.py so later steps and chapters can reuse them. Chapter 3 used the same text as an in-package stand-in.

- File: [`docs.py`](./docs.py)

### 3. Upload the documents to Cloud Storage

Creates the bucket facilities-docs and uploads each document under docs/.

- File: [`upload_docs.py`](./upload_docs.py)
- Run: `python upload_docs.py` (or `./run_all.sh 5` from the project root)
- You should see: `4 documents uploaded to gs://facilities-docs/docs/`

### 4. Write the RAG helper

Small helpers over the Vertex AI RAG Engine clients that chapters 12, 6, 11 and 13 reuse: find the corpus by its display name, import files from Cloud Storage and list what is in it.

- File: [`rag.py`](./rag.py)

### 5. Create the knowledge base and index the documents

Creates the RAG Engine corpus facilities-kb, imports everything under gs://facilities-docs/docs/ (the import chunks and embeds each file) and lists the indexed files.

- File: [`create_kb.py`](./create_kb.py)
- Run: `python create_kb.py` (or `./run_all.sh 5` from the project root)
- You should see: `indexed files: 4`

### 6. Add the bucket notification

Google Cloud Storage can publish an OBJECT_FINALIZE message to a Pub/Sub topic whenever an object lands. This block creates the topic facilities-doc-events with a subscription, attaches the notification to the bucket, uploads a probe object and shows the message, so you can see exactly what an upload event looks like.

- File: [`notify.py`](./notify.py)
- Run: `python notify.py` (or `./run_all.sh 5` from the project root)
- You should see: `notification: OBJECT_FINALIZE docs/notify-probe.md`

### 7. Write the ingestion function

The function Eventarc calls when a document lands: it imports just that one object into the corpus, so a new upload becomes searchable without re-indexing everything. It is a CloudEvent function (functions_framework.cloud_event).

- File: [`ingest_docs_fn.py`](./ingest_docs_fn.py)

### 8. Deploy the function and the Eventarc trigger

Deploys facilities-ingest-docs and creates the Eventarc trigger facilities-docs-finalized: when an object is finalized in facilities-docs, call the function.

- File: [`deploy_pipeline.py`](./deploy_pipeline.py)
- Run: `python deploy_pipeline.py` (or `./run_all.sh 5` from the project root)
- You should see: `trigger facilities-docs-finalized created`

### 9. Upload a new document and watch it get indexed

Uploads a safety bulletin. Nothing else is called: Cloud Storage emits the finalize event, Eventarc calls your function and the function imports the file, so the number of indexed files goes up by one.

- File: [`test_pipeline.py`](./test_pipeline.py)
- Run: `python test_pipeline.py` (or `./run_all.sh 5` from the project root)
- You should see: `indexed files: 4 -> 5`

### 10. Replace a document and check the old version is gone

A revised SOP must replace the old one, not sit beside it. Upload revision 2 of the boiler SOP, re-import it and search: only the new limit may come back. The script then restores the original so the rest of the course uses the real SOP.

- File: [`replace_doc.py`](./replace_doc.py)
- Run: `python replace_doc.py` (or `./run_all.sh 5` from the project root)
- You should see: `original restored serves 30 psi: True`

## It works when

- documents in the bucket
- corpus facilities-kb exists
- files imported
- a new upload is re-ingested
