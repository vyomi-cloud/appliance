# Chapter 6: Response Generation

_Grounded answers with citations and sensitive data masked_

**What you build:** Answer in plain language from the retrieved documents, with citations, and filter sensitive data out before the user sees it.

## Code, in order

### 1. Install the libraries

Chapter 11 generates answers that are grounded in what chapter 6 retrieved and checks them before the user sees them. It uses the `openai` library (chat, Assistants file search, and Azure OpenAI On Your Data), `azure-ai-contentsafety` for the output filter and the retrieval helper `kb.py` from chapter 6. Scope note: Azure AI Content Safety flags harmful text (hate, sexual, violence, self-harm). Masking personal data is a different Azure service (Azure AI Language PII detection) that the simulator does not offer, so this chapter does not claim to do it.

- File: [`app/install11.sh`](../app/install11.sh)

### 2. Write the grounded answer function

Retrieve, number the passages, and instruct the model to answer only from them and cite like [1]. The function returns the answer together with the numbered citations (source file plus the passage), so a user interface can show where each claim came from. The reply here is the repo's deterministic test stub, which simply quotes the first passage; a larger model writes a fuller answer.

- File: [`app/respond.py`](../app/respond.py)

### 3. Try it: a cited answer

Ask the boiler question. The answer must carry a citation marker, and the first citation must be the boiler SOP.

- File: [`app/try_respond.py`](../app/try_respond.py)
- Run: `cd app && python try_respond.py`
- You should see: `grounded: True`

### 4. Filter the output with Azure AI Content Safety

`ContentSafetyClient.analyze_text` returns a severity (0 to 7) for each harm category. `check_output` blocks an answer if any category reaches the threshold. The clean agent answer passes; an invented harmful completion is flagged. The simulator's Content Safety is a deterministic filter set, not Microsoft's trained classifiers.

- File: [`app/guard.py`](../app/guard.py)
- Run: `cd app && python guard.py`
- You should see: `harmful completion allowed: False`

### 5. Ground with Assistants file search

The managed alternative to doing retrieval yourself: upload a file to a *vector store*, give an assistant the `file_search` tool, run it on a thread, and read the `file_citation` annotations on its reply. Same `openai` library, same calls as on Azure OpenAI.

- File: [`app/file_search.py`](../app/file_search.py)
- Run: `cd app && python file_search.py`
- You should see: `annotation types: ['file_citation']`

### 6. Ground with Azure OpenAI On Your Data

The one-call version: add a `data_sources` entry of type `azure_search` to a normal chat request and the service retrieves from your AI Search index itself and returns the citations in the message `context`. It reuses the index and key from chapter 7 and 12.

- File: [`app/on_your_data.py`](../app/on_your_data.py)
- Run: `cd app && python on_your_data.py`
- You should see: `On Your Data citations:`

## It works when

- answer cites its sources
- harmful output flagged
- citations present
