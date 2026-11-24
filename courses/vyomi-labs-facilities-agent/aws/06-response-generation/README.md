# Layer 6: Response Generation

_Grounded answers with citations and sensitive data masked_

**What you build:** Answer in plain language from the retrieved documents, with citations, and filter sensitive data out before the user sees it.

## Code, in order

### 1. Create the guardrail

One guardrail guards both directions: it blocks prompt attacks and a denied word on the way in (chapter 2 tests the input side), and anonymises e-mail addresses and blocks US social security numbers on the way out. The script is safe to re-run: it reuses an existing guardrail with the same name.

- File: [`guardrail.py`](./guardrail.py)
- Run: `python guardrail.py` (or `./run_all.sh 6` from the project root)
- You should see: `guardrail `

### 2. Filter an answer on the way out

ApplyGuardrail with source OUTPUT runs the same policies on text you already have. An answer that leaks a person's e-mail address comes back anonymised.

- File: [`output_guardrail.py`](./output_guardrail.py)
- Run: `python output_guardrail.py` (or `./run_all.sh 6` from the project root)
- You should see: `email removed: True`

### 3. Ask the agent for a grounded, cited answer

Calls the hosted agent (chapter 3) with the boiler question. Because the knowledge-search tool is deployed (chapter 6) the facilities sub-agent now retrieves the SOP and the answer cites it. The script then runs the agent's answer through the output guardrail. Needs chapters 3, 6, 7 and the helper from chapter 3.

- File: [`grounded_answer.py`](./grounded_answer.py)
- Run: `python grounded_answer.py` (or `./run_all.sh 6` from the project root)
- You should see: `grounded in the boiler SOP: True`

### 4. Let the knowledge base generate the answer

RetrieveAndGenerate is the managed alternative: one call retrieves from the knowledge base, generates with the model and returns citation blocks, with the guardrail applied to the generation.

- File: [`retrieve_and_generate.py`](./retrieve_and_generate.py)
- Run: `python retrieve_and_generate.py` (or `./run_all.sh 6` from the project root)
- You should see: `citation blocks:`

## It works when

- answer cites a retrieved document
- personal data is masked
- RetrieveAndGenerate returns citations
