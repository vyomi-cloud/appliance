# Branch: v4/ai-capkbruntime

Owner: AI session (round 6). Base: `v4/ai-integration` @ 20c01eaa3. Not merged.

## Purpose
Close the Dev Simplified limitations of `bedrock.knowledge-bases` and `bedrock.runtime` (core/capabilities/aws/bedrock.json) instead
of hiding the badges: multi-format KB ingestion with real parsing/chunking/metadata, and Converse/InvokeModel `document`, `image`,
prompt-cache and reasoning handling.

## OSS choices (thumb rule)
| Piece | Choice | License / size | Substrate | Why |
|---|---|---|---|---|
| PDF text | `pypdf` | BSD-3, ~4 MB pure Python | Mesh: bundled in the appliance image; Nano: must be loaded into Pyodide (micropip/wheel), otherwise PDFs fail with an explicit per-file reason | pure Python, no native deps; pdfminer is larger |
| DOCX / XLSX / PPTX | stdlib `zipfile` + `xml.etree` | stdlib | both | Office Open XML is zip+XML; openpyxl/python-docx/python-pptx would add dependencies for text-only needs |
| CSV / HTML / MD | stdlib `csv`, `html`, regex | stdlib | both | |
| BM25 / hybrid search | unchanged (SQLite FTS5) | | both | |
| Semantic chunking | local embedding seam (`llm_core.embed`) with Bedrock's own algorithm (sentence groups + percentile breakpoint) | | both | no library needed; same embedder as retrieval |
| Prompt cache | in-process SHA-256 prefix table | | both | accounting layer only; real KV reuse comes from llama.cpp `cache_prompt` (now sent on every request) |

Hand-written code is the wire adapter: block translation, cache accounting, sidecar parsing. No OSS exists for Bedrock's request shapes.

## Behaviour
Knowledge bases (`core/knowledge_core.py`, `core/bedrock_agents_core.py`)
- Formats: txt, md, csv/tsv, json, html, xml, yaml, rst, PDF, DOCX (headings, tables), XLSX (all sheets), PPTX (slides + speaker notes).
- Failures are per document, in `ingestionJob.failureReasons` and `numberOfDocumentsFailed`: corrupt/encrypted/scanned PDF, legacy
  .doc/.xls/.ppt, empty file, non-UTF-8, >50 MB, guardrail block, invalid `.metadata.json`.
- `parsingConfiguration`: BEDROCK_FOUNDATION_MODEL (needs modelArn) keeps tables as markdown tables; default parsing flattens rows to
  `header: value`. It does NOT call a model. BEDROCK_DATA_AUTOMATION is rejected with ValidationException.
- Chunking: FIXED_SIZE (window + overlap), NONE, HIERARCHICAL (parent/child; child matched, parent returned once, as Bedrock),
  SEMANTIC (embedding breakpoints, bufferSize, breakpointPercentileThreshold, maxTokens cap). Invalid configs -> ValidationException at CreateDataSource.
- Metadata: `<object>.metadata.json` with plain values or typed `{value:{type,..},includeForEmbedding}`; max 10 attributes / 10 KB;
  attributes returned on results and usable in Retrieve filters; `includeForEmbedding` appends the attribute to the embedded text.

Runtime (`core/ai_models_core.py`, `core/llm_core.py`)
- `document` blocks (Converse and Claude InvokeModel): bytes parsed with the same parsers, sent as `<document name=..>` text.
  Unparseable -> ValidationException naming the file. s3Location source unsupported.
- `image` blocks: ValidationException unless `llm.vision_available()` (env `VYOMI_LLM_VISION=1` or `llm.set_vision(True)`), then passed
  as OpenAI `image_url` parts to the HTTP backend. No vision model is shipped; that path is verified only against a stub backend.
- Prompt caching: Converse `cachePoint` (tools/system/messages) and Claude `cache_control` -> `cacheReadInputTokens`/`cacheWriteInputTokens`
  (Converse, ConverseStream metadata) and `cache_read_input_tokens`/`cache_creation_input_tokens` (InvokeModel, non-stream). Prefix
  hash keyed, 300 s TTL refreshed on hit, 1024-token minimum, tokens apportioned from the model's own `input_tokens`. Not done:
  InvokeModelWithResponseStream cache usage.
- Reasoning: `reasoningContent`, `thinking` blocks/params and `additionalModelRequestFields.thinking` are rejected (no served model emits reasoning).

## Tests
`tests/conformance/test_bedrock_kb_runtime_caps.py` (real boto3 bedrock-agent, bedrock-agent-runtime, bedrock-runtime over HTTP):
46 checks, 46 pass. Run with pypdf on the path: `PYTHONPATH=.:<pypdf dir> python tests/conformance/test_bedrock_kb_runtime_caps.py`
(skips when boto3 or pypdf is missing). Existing suites re-run: see the report.

## Declared limits / open issues
- Scanned PDFs: no OCR. Legacy binary Office: unsupported. PDF on Nano depends on pypdf being loadable in Pyodide (not verified in a browser here).
- Nano chunk embeddings come from the in-browser embedder (or hash fallback), so SEMANTIC breakpoints on Nano are only as good as that embedder.
- Prompt cache is process-local and lost on restart; it reports honest accounting, the latency benefit depends on llama.cpp `cache_prompt`.
- Vision path untested against a real multimodal model.
