# Layer 4: Knowledge Pipeline

_Documents flowing into a searchable knowledge base, re-indexed on every upload_

**What you build:** Turn documents into searchable knowledge, and re-index automatically when a new document lands.

## Code, in order

### 1. Install the libraries

Chapter 12 turns documents into searchable knowledge: Blob Storage holds the files, an Azure AI Search indexer reads them into the `facilities-kb` index, and an Event Grid subscription plus a Function re-runs the indexer whenever a new blob lands. It relies on the search service and `azdata.py` from chapter 7.

- File: [`install12.sh`](./install12.sh)

### 2. Save the four documents

The corpus: three SOPs and one maintenance manual, each a short Markdown file. Save each one exactly as shown, with the file name given (the file name becomes the citation source later). First, the boiler SOP.

- File: [`boiler-sop.md`](./boiler-sop.md)

### 3. Save the elevator SOP

Elevator faults.

- File: [`elevator-sop.md`](./elevator-sop.md)

### 4. Save the fire-safety SOP

Fire alarms and evacuation.

- File: [`fire-safety-sop.md`](./fire-safety-sop.md)

### 5. Save the HVAC manual

Air handling unit maintenance.

- File: [`hvac-maintenance-manual.md`](./hvac-maintenance-manual.md)

### 6. Create the storage account and upload the documents

A StorageV2 account `facilitiesdocs` through `azure-mgmt-storage`, then (with `azure-storage-blob`) a container `docs` and the four files. The blob data plane uses the same Azurite-style connection string as Table storage in chapter 7. The last line reads one blob back to prove the upload.

- File: [`upload_docs.py`](./upload_docs.py)
- Run: `python upload_docs.py` (or `./run_all.sh 4` from the project root)
- You should see: `read back: # SOP-101 Boiler plant operation`

### 7. Define and create the search index

The index `facilities-kb` is the schema of what is searchable: an `id` key, `source` (the blob name, for citations), `title` and `content` as full-text fields, and `content_vector`, a 1536-number vector field with an HNSW algorithm. A semantic configuration `sem` tells the semantic ranker which fields matter. Chapter 6 queries this index with text, vectors and the ranker. `kb_index()` is reused there.

- File: [`kb_index.py`](./kb_index.py)
- Run: `python kb_index.py` (or `./run_all.sh 4` from the project root)
- You should see: `index facilities-kb fields: ['id', 'source', 'title', 'content', 'content_vector']`

### 8. Create the blob data source and the indexer

An indexer is a scheduled job that reads a data source and writes documents into an index. The data source points at the `docs` container; field mappings turn the blob path into the key (`base64Encode`) and the blob name into `source` and `title`. Run it and wait for `success`. This is the initial load.

- File: [`indexer.py`](./indexer.py)
- Run: `python indexer.py` (or `./run_all.sh 4` from the project root)
- You should see: `indexer last run: success | documents: 4`

### 9. Check the documents are searchable

A first full-text query. The boiler SOP must rank first for a boiler question, and the index must hold exactly four documents.

- File: [`check_search.py`](./check_search.py)
- Run: `python check_search.py` (or `./run_all.sh 4` from the project root)
- You should see: `'boiler pressure' -> boiler-sop.md`

### 10. Write the ingest function

The pipeline's trigger. Event Grid posts `Microsoft.Storage.BlobCreated` events here. The function answers the subscription validation handshake (Event Grid sends a code and expects it echoed back), and for every new blob it runs the indexer so the document becomes searchable.

- File: [`fn_ingest_docs.py`](./fn_ingest_docs.py)

### 11. Deploy the function and subscribe it to blob events

Deploy it as its own Function App `facilities-ingest` (same four ARM steps as chapter 7), then wire the event path with `azure-mgmt-eventgrid`: a *system topic* on the storage account (Azure publishes storage events there) and an event subscription that delivers `BlobCreated` events to the function.

- File: [`deploy_ingest.py`](./deploy_ingest.py)
- Run: `python deploy_ingest.py` (or `./run_all.sh 4` from the project root)
- You should see: `event subscription blob-created: Succeeded`

### 12. Upload a new document and watch it become searchable

The whole pipeline end to end: upload a new SOP; Azure Storage raises `BlobCreated`; Event Grid calls the function; the function runs the indexer; the new text becomes searchable without you doing anything else. The script polls the search index for a random word that exists only in the new file.

- File: [`new_doc.py`](./new_doc.py)
- Run: `python new_doc.py` (or `./run_all.sh 4` from the project root)
- You should see: `new upload became searchable as: water-leak-sop.md`

## It works when

- documents uploaded
- index filled by the indexer
- a new blob becomes searchable
