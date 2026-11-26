# Layer 7: Response Generation

_Grounded answers with citations and sensitive data masked_

**What you build:** Answer in plain language from the retrieved documents, with citations, and filter sensitive data out before the user sees it.

## Code, in order

### 1. Install the libraries

Chapter 11 answers from retrieved documents and filters the answer before the user sees it. It relies on gcp.py and vymodels.py (chapter 10), search.py (chapter 6) and the knowledge base (chapter 12). The output filter is a Model Armor template: chapter 2 reuses the same template for the input side, and whichever chapter you run first creates it.

- File: [`install_11.sh`](./install_11.sh)

### 2. Write the Model Armor helper

Model Armor screens text with filters: prompt-injection and jailbreak, harmful content and sensitive data. This helper creates the template facilities-guardrail (or reuses it) and tells you whether a screening result matched a filter.

- File: [`guardrail.py`](./guardrail.py)

### 3. Write the grounded answer function

Retrieve passages, number them, and ask the model to answer only from them, so every claim can be traced to a source. In this verification the model is the deterministic test stub: it answers with the first retrieved passage and a [1] marker, which is enough to prove the grounding and citation plumbing; a larger model would write a fluent sentence.

- File: [`respond.py`](./respond.py)

### 4. Try the grounded answer

Ask the boiler question and print the answer with its citations. The check: the answer carries a [n] marker and the boiler SOP is among the cited sources.

- File: [`try_response.py`](./try_response.py)
- Run: `python try_response.py` (or `./run_all.sh 7` from the project root)
- You should see: `grounded: the answer cites the boiler SOP`

### 5. Create the output guardrail and screen two answers

Calls sanitizeModelResponse with the template. An answer containing a US social security number and an email address must be flagged (MATCH_FOUND); a clean operational answer must pass (NO_MATCH_FOUND).

- File: [`screen_output.py`](./screen_output.py)
- Run: `python screen_output.py` (or `./run_all.sh 7` from the project root)
- You should see: `clean answer passes: True`

### 6. Put the pieces together

The full response path: grounded answer, then the output filter. If the filter matches, the answer is withheld and the user gets a safe message instead; the withheld text is never returned.

- File: [`safe_response.py`](./safe_response.py)
- Run: `python safe_response.py` (or `./run_all.sh 7` from the project root)
- You should see: `safe response delivered with its citations`

### 7. Ask the model to ground itself on the corpus

Vertex AI can also ground generateContent directly on the RAG corpus, with no retrieval code of your own: add a Retrieval tool pointing at the corpus. The response carries groundingMetadata listing the chunks it used.

- File: [`grounded_generate.py`](./grounded_generate.py)
- Run: `python grounded_generate.py` (or `./run_all.sh 7` from the project root)
- You should see: `generateContent grounded on the RAG corpus`

## It works when

- answer cites retrieved documents
- sensitive data flagged in output
- groundingMetadata present
