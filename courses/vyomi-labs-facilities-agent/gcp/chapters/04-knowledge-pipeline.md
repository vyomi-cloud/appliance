# Chapter 4: Knowledge Pipeline

_Documents flowing into a searchable knowledge base, re-indexed on every upload_

**What you build:** Turn documents into searchable knowledge, and re-index automatically when a new document lands.

## Code, in order

### 1. Install the libraries

Chapter 12 turns documents into searchable knowledge. It uses Cloud Storage, Vertex AI RAG Engine, Pub/Sub (for the bucket notification), Eventarc and Cloud Functions. It relies on gcp.py (chapter 10) and functions.py (chapter 7).

- File: [`app/install_12.sh`](../app/install_12.sh)

### 2. Write the four documents

The corpus: three SOPs and one equipment manual, saved as docs.py so later steps and chapters can reuse them. Chapter 3 used the same text as an in-package stand-in.

- File: [`app/docs.py`](../app/docs.py)

### 3. Upload the documents to Cloud Storage

Creates the bucket facilities-docs and uploads each document under docs/.

- File: [`app/upload_docs.py`](../app/upload_docs.py)
- Run: `cd app && python upload_docs.py`
- You should see: `4 documents uploaded to gs://facilities-docs/docs/`

### 4. Write the RAG helper

Small helpers over the Vertex AI RAG Engine clients that chapters 12, 6, 11 and 13 reuse: find the corpus by its display name, import files from Cloud Storage and list what is in it.

- File: [`app/rag.py`](../app/rag.py)

### 5. Create the knowledge base and index the documents

Creates the RAG Engine corpus facilities-kb, imports everything under gs://facilities-docs/docs/ (the import chunks and embeds each file) and lists the indexed files.

- File: [`app/create_kb.py`](../app/create_kb.py)
- Run: `cd app && python create_kb.py`
- You should see: `indexed files: 4`

### 6. Add the bucket notification

Google Cloud Storage can publish an OBJECT_FINALIZE message to a Pub/Sub topic whenever an object lands. This block creates the topic facilities-doc-events with a subscription, attaches the notification to the bucket, uploads a probe object and shows the message, so you can see exactly what an upload event looks like.

- File: [`app/notify.py`](../app/notify.py)
- Run: `cd app && python notify.py`
- You should see: `notification: OBJECT_FINALIZE docs/notify-probe.md`

### 7. Write the ingestion function

The function Eventarc calls when a document lands: it imports just that one object into the corpus, so a new upload becomes searchable without re-indexing everything. It is a CloudEvent function (functions_framework.cloud_event).

- File: [`app/ingest_docs_fn.py`](../app/ingest_docs_fn.py)

### 8. Deploy the function and the Eventarc trigger

Deploys facilities-ingest-docs and creates the Eventarc trigger facilities-docs-finalized: when an object is finalized in facilities-docs, call the function.

- File: [`app/deploy_pipeline.py`](../app/deploy_pipeline.py)
- Run: `cd app && python deploy_pipeline.py`
- You should see: `trigger facilities-docs-finalized created`

### 9. Upload a new document and watch it get indexed

Uploads a safety bulletin. Nothing else is called: Cloud Storage emits the finalize event, Eventarc calls your function and the function imports the file, so the number of indexed files goes up by one.

- File: [`app/test_pipeline.py`](../app/test_pipeline.py)
- Run: `cd app && python test_pipeline.py`
- You should see: `indexed files: 4 -> 5`

### 10. Replace a document and check the old version is gone

A revised SOP must replace the old one, not sit beside it. Upload revision 2 of the boiler SOP, re-import it and search: only the new limit may come back. The script then restores the original so the rest of the course uses the real SOP.

- File: [`app/replace_doc.py`](../app/replace_doc.py)
- Run: `cd app && python replace_doc.py`
- You should see: `original restored serves 30 psi: True`

## It works when

- documents in the bucket
- corpus facilities-kb exists
- files imported
- a new upload is re-ingested
