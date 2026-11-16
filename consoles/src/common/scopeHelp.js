/* "Scope and limits" content for the right-hand help pane of the v4 consoles (AWS, GCP, Azure).
 *
 * Plain data, no UI: each entry is { id, title, intro, real[], metadata[], limits[], nano[], mesh[] } and the cloud shells
 * render it with <ScopeSection/> (common/ScopeSection.jsx). Wording comes from docs/architecture/v4.0/branches/ai-*.md;
 * if those docs do not say something, it is not here. Numbers are only the ones the docs state (caps) or measured.
 *
 *   scopeFor("aws", "/bedrock/custom-models")  ->  entry | null     (matched on the hash-route path)
 */
import { match } from "./router.js";

// Shared fragments (kept in one place so the three clouds say the same thing about training).
const HEAD_REAL = "Fine-tuning on a trainable base really trains a small head on frozen embeddings: all-MiniLM-L6-v2 (Nano), nomic-embed-text (Mesh) or any vyomi.head.* id. Task types: classifier, router, reranker. It is not a language model and cannot generate text; every answer carries vyomiTrained: true.";
const HEAD_CAPS = "Training data is JSONL in the simulated object store. Caps on every cloud: 2000 rows, 5 MB, 20 labels, at least 10 rows and 2 labels, 1 to 50 epochs. Over a cap is rejected with the cloud's validation error and no job is created. 20 percent of rows are held out and compared with a baseline (majority class, or zero-shot cosine for rerankers).";
const LORA_REAL = "On Mesh, a base from the open-model pool (smollm2-135m-instruct, smollm2-360m-instruct, qwen2.5-0.5b, qwen2.5-1.5b, qwen3-4b) runs a real LoRA job (PEFT on CPU) and writes an f16 GGUF adapter to the object store. A tuned chat model is a small open model plus an adapter, not a vendor model.";
const LORA_CAPS = "Chat rows are {messages} or {prompt, completion}: 2000 rows, 5 MB, at least 10 rows, sequence length 32 to 1024, rank 1 to 64, 1 to 10 epochs. 7B and larger bases are rejected as too large for 16 GB CPU. Tool-calling training data is not supported.";
const LORA_NOT_MEASURED = "Measured only for SmolLM2-135M. Training Qwen3-4B (the commercial base) or any 1.5B+ model, Codespace timing and 2000-row runs were not measured.";
const NANO_TRAIN = "Heads train inside the tab (typed-array JS in a Web Worker, embedding about 12 ms per text). Keep the tab open while a job runs; jobs started from the SDK/CLI through the relay worker fail fast with a clear message instead.";
const NANO_LORA = "No chat training in a browser tab. Train the LoRA on Mesh or your own machine, then import the GGUF adapter; Nano serves it with wllama on a SmolLM2 135M or 360M base.";
const VENDOR_META = "Vendor base models (Nova, Titan, Gemini, GPT and similar) keep the metadata-only behaviour on purpose: the job completes without training and says so.";

const E = {};
const def = (id, patterns, e) => { E[id] = { id, patterns, ...e }; };

/* ---------------------------------------------------------------- AWS Bedrock */
def("aws.bedrock.overview", ["/bedrock"], {
  title: "Amazon Bedrock: scope and limits",
  intro: "This console is backed by the Bedrock APIs of the simulator. Models are local open models, not the vendor models.",
  real: ["Model listing, Converse, InvokeModel and token counting go through the real Bedrock wire shapes.", "Standard ids (anthropic.claude-*, amazon.titan-*, amazon.nova-*, meta.llama3-*, cohere.*) are listed as aliases and answered by the local open model. Each model reports vyomiBackedBy and says so."],
  limits: ["Images (Converse, Claude InvokeModel) need the Mesh vision model and are rejected without it; documents (PDF, DOCX, XLSX, CSV, HTML, Markdown, text) are parsed and read as text. Reasoning (thinking / reasoning_config) needs the Mesh reasoning model and is rejected without it.", "Not in scope: Automated Reasoning (explained on its page). Data Automation is built on the small vision model; see its page for limits. Flows, Guardrails, Prompt Management, Evaluations, Settings, Model access and Prompt optimization are built; see each page for its limits.", "No real model quality is implied by an alias."],
  nano: ["Chat is answered by WebLLM and needs WebGPU; small models only."],
  mesh: ["Chat is answered by llama.cpp with Qwen3-4B-Instruct-2507 Q4 (Apache-2.0, about 2.4 GB on disk). Tool selection with a 4B model is the open quality risk.", "Optional role models, listed only while running: SmolVLM-500M for images (Apache-2.0) and DeepSeek-R1-Distill-Qwen-1.5B for reasoning (MIT). The 8 GB Codespace has about 2.8 GB for AI, so starting a role model stops the default chat model unless the budget is raised."],
});
def("aws.bedrock.quickstart", ["/bedrock/quickstart"], {
  title: "Quickstart: scope and limits",
  intro: "Code samples for Converse and InvokeModel against this endpoint.",
  limits: ["The OpenAI-compatible Responses endpoint is not simulated; the page says so."],
});
def("aws.bedrock.api-keys", ["/bedrock/api-keys"], {
  title: "API keys: scope and limits",
  intro: "Long-term keys are IAM service-specific credentials for bedrock.amazonaws.com (create, list, update, reset, delete) with an optional age that becomes the expiry.",
  limits: ["A short-term key is a client-generated bedrock-api-key- token. The simulator does not verify bearer tokens."],
});
def("aws.bedrock.models", ["/bedrock/models"], {
  title: "Model catalog: scope and limits",
  intro: "ListFoundationModels: 19 standard Bedrock ids as aliases plus the ten native vyomi.* models.",
  real: ["Provider and display name are the real ones; modality is TEXT only; lifecycle ACTIVE.", "vyomiBackedBy names the local model that actually answers. boto3 drops this extra field; the console and raw HTTP show it."],
  limits: ["The catalog is the simulator's, not Amazon's full list. The page layout is approximate."],
});
def("aws.bedrock.playground", ["/bedrock/playground"], {
  title: "Playground: scope and limits",
  intro: "Chat sends Converse to the selected model id.",
  real: ["Answers come from the local open model behind the alias (response header x-vyomi-local-model)."],
  limits: ["Chat and configuration panel are simplified compared with AWS.", "Without a running local model the call fails; there is no fallback to a canned answer."],
  nano: ["WebLLM, WebGPU required."],
  mesh: ["llama.cpp with the AI pack (Qwen3-4B-Instruct-2507 Q4)."],
});
def("aws.bedrock.quotas", ["/bedrock/quotas"], {
  title: "Quotas: scope and limits",
  intro: "Model rows come from ListFoundationModels.",
  limits: ["TPM and RPM are shown as 'Not enforced'. There is no Service Quotas engine and no increase workflow."],
});
def("aws.bedrock.compare", ["/bedrock/compare-models"], {
  title: "Compare models: scope and limits",
  intro: "Side-by-side cards for models of the simulator's pool.",
  limits: ["Compares the pool's local models, not Anthropic or other vendor models. Card layout is approximate."],
});
def("aws.bedrock.tokenizer", ["/bedrock/tokenizer"], {
  title: "Tokenizer: scope and limits",
  intro: "CountTokens through the Bedrock API.",
  limits: ["The count is a heuristic of about 4 characters per token, the same estimate the local model seam uses, not the vendor tokenizer."],
});
def("aws.bedrock.inference-profiles", ["/bedrock/inference-profiles"], {
  title: "Inference profiles: scope and limits",
  intro: "System-defined and application inference profiles.",
  real: ["System-defined profiles are aliases of the model catalog (us. prefix; region-specific model ARNs). Application profiles can be created and deleted and resolve to their source model in Converse and InvokeModel."],
  metadata: ["Profiles carry no routing, capacity or cost behaviour."],
  limits: ["The list has 33 profiles, fewer than the real EU view (58). eu. and apac. ids resolve for invoke but are not all listed. Columns overflow horizontally; no per-column filter toggles."],
});
def("aws.bedrock.batch-inference", ["/bedrock/batch-inference"], {
  title: "Batch inference: scope and limits",
  intro: "CreateModelInvocationJob reads JSONL from simulated S3 and runs each record through the local model.",
  real: ["Jobs run for real against the local model and write output back to S3."],
  limits: ["Synchronous, at most 25 records per job. With no local model the job ends Failed with a message.", "Job state is process-local."],
  nano: ["Local model is WebLLM."],
  mesh: ["Local model is llama.cpp."],
});
def("aws.bedrock.provisioned-throughput", ["/bedrock/provisioned-throughput"], {
  title: "Provisioned Throughput: scope and limits",
  intro: "Provisioned model throughput records.",
  metadata: ["Create, list, update and delete work, but no capacity is reserved and nothing is billed. Custom-model ARNs are accepted."],
  limits: ["State is process-local."],
});
def("aws.bedrock.custom-models", ["/bedrock/custom-models"], {
  title: "Custom models: scope and limits",
  intro: "Models and Jobs tabs over CreateModelCustomizationJob and the custom-model records.",
  real: [HEAD_REAL, "The trained model is invocable with InvokeModel or Converse on the custom-model ARN: {task: classify, text} returns {label, scores}; {task: score, query, document} returns {score}.", LORA_REAL],
  metadata: [VENDOR_META],
  limits: [HEAD_CAPS, LORA_CAPS, "Hyperparameters accepted for heads: epochCount, taskType, learningRate, learningRateMultiplier, batchSize.", "Importing a model (CreateModelImportJob) is API only; this console has no import page yet. The import extension takes an S3 prefix holding adapter.gguf and adapter_meta.json instead of Hugging Face weights.", "Job records are process-local; trained heads persist in the object store and are rebuilt on reload.", "boto3 drops the vyomiTraining field; REST callers and this console see it."],
  nano: [NANO_TRAIN, NANO_LORA],
  mesh: ["Heads train on a background thread in pure Python (not timed on a full 2000-row MLP).", "Chat LoRA runs for real (PEFT on CPU). Not exercised on a real Codespace; llama-server --lora serving was verified only against a fake server."],
});
def("aws.bedrock.training-job", ["/bedrock/custom-models/jobs/:id"], {
  title: "Customization job: scope and limits",
  intro: "Status, progress, per-epoch loss and accuracy, held-out result, Stop, artifact and Try it.",
  real: ["The page polls the job while it is Queued, Embedding, Training or Evaluating. Held-out accuracy is shown next to the baseline; your own rows decide the number.", "Stop cancels within one mini-batch. Artifact is models/<id>/head.json (embedder id recorded) in the object store.", "Try it calls InvokeModel on the custom-model ARN."],
  limits: ["A head separates only what the frozen embedder separates. The training data in tests is synthetic and easy; do not read the accuracy as general quality.", "An invocation is refused if the head's embedder differs from the running one.", "Non-trainable bases show 'not trainable here' and stay metadata-only."],
  nano: [NANO_TRAIN],
  mesh: ["Chat-LoRA jobs report per-step loss, held-out exact match and perplexity against an adapter-off baseline (n is small: 10 percent of rows). " + LORA_NOT_MEASURED],
});
def("aws.bedrock.prompt-routers", ["/bedrock/prompt-routers"], {
  title: "Prompt routers: scope and limits",
  intro: "Two default routers plus custom router CRUD.",
  metadata: ["No quality routing: Converse on a router ARN answers with the second (larger) model of the router."],
  limits: ["Default router models show model ids rather than friendly names."],
});
def("aws.bedrock.marketplace-deployments", ["/bedrock/marketplace-deployments"], {
  title: "Marketplace deployments: scope and limits",
  intro: "Marketplace model endpoints with Register and Deregister.",
  metadata: ["Records only. No SageMaker endpoint is created."],
});
def("aws.bedrock.knowledge-bases", ["/bedrock/knowledge-bases", "/bedrock/knowledge-bases/:id"], {
  title: "Knowledge bases: scope and limits",
  intro: "Bedrock Agent knowledge bases over the simulated S3, with ingestion, Retrieve and RetrieveAndGenerate.",
  real: ["Ingestion chunks documents (fixed size, semantic or hierarchical, or none), reads .metadata.json sidecars and mirrors chunks into the configured OpenSearch index, so opensearch-py searches the same data.", "Retrieve is hybrid by default (SQLite FTS5 BM25 plus vector cosine, fused by reciprocal rank); overrideSearchType SEMANTIC is vector only with cosine scores. The full metadata filter set is validated like Bedrock (one operator per filter, andAll/orAll of 2-5), implicitFilterConfiguration derives a filter with the local model, and reranking works on Retrieve and the Rerank API."],
  metadata: ["OpenSearch domains and Serverless collections are metadata records; there is no cluster process."],
  limits: ["Exact vector scan, fine to about 10k chunks; no HNSW.", "Rerank is embedding similarity plus term coverage (the trace says so), not a cross-encoder, unless the Mesh operator points VYOMI_RERANK_ENDPOINT at a reranker server such as llama-server --reranking with a bge-reranker GGUF; none is shipped and Nano always uses the blend. Implicit filters come from the small local model. Chunking is a splitter, not model-driven semantic chunking.", "PDF needs the optional pypdf; .docx and text work natively.", "RetrieveAndGenerate needs the local LLM to be running.", "OpenSearch has no aggregations, highlighting, scroll or search pipelines."],
  nano: ["Embeddings are all-MiniLM-L6-v2 (384-d, about 23 MB downloaded on first use). If the download is blocked a labelled hash embedding is used and ranking is keyword grade. Vectors are 384-d, so a KB is not portable to the appliance (768-d); re-ingest after moving."],
  mesh: ["Embeddings are nomic-embed-text through llama.cpp."],
});
def("aws.bedrock.agents", ["/bedrock/agents", "/bedrock/agents/:id"], {
  title: "Agents: scope and limits",
  intro: "Bedrock Agents (classic): build an agent, add action groups and knowledge bases, enable multi-agent collaboration, then test it with the trace.",
  real: ["Action groups call your Lambda with the real Bedrock Agents event (function schema, OpenAPI inline or from S3), can return control to the caller, or ask for confirmation first (requireConfirmation: the Lambda runs only after you confirm). The built-in AMAZON.UserInput group asks the user back; AMAZON.CodeInterpreter runs the model's Python in a sandbox and returns its output and files.", "A SUPERVISOR agent delegates to collaborator agents (SUPERVISOR_ROUTER can route a whole request to one); the test panel shows the collaborator traces. Advanced prompts override the orchestration, pre/post-processing, routing and memory prompts and can use a parser Lambda. InvokeInlineAgent runs an agent defined in the request; SESSION_SUMMARY memory also summarises sessions that time out.", "The test panel streams the real InvokeAgent response and renders the trace (pre-processing, orchestration, collaborators, code interpreter, guardrails)."],
  limits: ["The model is one small local model, so tool and collaborator choices are far less reliable than a production model. The code interpreter is a restricted sandbox, not a VM: no network, no image outputs, and on Nano only the Python standard library.", "Collaborators run one after another (no parallel calls), to depth 3. The knowledge-base response-generation prompt is stored but not applied. Non-text chat inputs (images) are rejected. Session summaries on timeout are produced on the next request that touches the agent, not by a background timer."],
  nano: ["The model is WebLLM in the browser (WebGPU); without it InvokeAgent answers DependencyFailedException."],
  mesh: ["llama.cpp answers; the code interpreter runs in a restricted subprocess."],
});
def("aws.bedrock.rag-studio", ["/bedrock/knowledge-bases/studio"], {
  title: "RAG Studio: scope and limits",
  intro: "Design, validate, test and visualise the RAG pipeline of facilities-kb.",
  real: ["Design edits chunking (persisted in the KB through UpdateDataSource and StartIngestionJob). Validate runs a 16-rule linter and a golden-set evaluation with 7 deterministic metrics, run history and A/B compare. Test shows per-stage scores, latency per stage, a cited answer and the guardrail result."],
  limits: ["Retrieval and rerank settings are kept in the browser (localStorage per KB); only chunking is stored in the KB.", "Faithfulness and answer relevance are token-overlap proxies, not LLM-judged. Citation match is by URI substring.", "The embedding map runs UMAP on the main thread: fine to about 1500 chunks, above that a deterministic sample is shown.", "With no live facilities-kb, Studio shows a clearly bannered demo corpus (hashed n-gram vectors, extractive answers); it shows mechanics, not retrieval quality.", "A KB without the Vyomi inspect API is 'live-limited': apply, ingest and test work; corpus and stage views are limited."],
  nano: ["A live facilities-kb can be created in the browser with the MiniLM embedder, but the real browser model was not run in a test; without a KB Studio shows the demo corpus."],
  mesh: ["Verified live against the knowledge engine: 28 chunks ingested, 12 candidates with stage scores."],
});
def("aws.bedrock.agentcore", ["/bedrock/agentcore", "/bedrock/agentcore/gateways/:id"], {
  title: "AgentCore: scope and limits",
  intro: "Runtime, Gateway with Cedar policy, Memory, and evaluation/observability over the AgentCore control and data planes.",
  real: ["Memory has control and data planes: events, sessions, actors and memory records with retrieval. Gateway serves MCP over JSON-RPC (tools/list filtered by policy, tools/call checked against Cedar; ENFORCE is default deny, LOG_ONLY allows). Policy engines validate Cedar and reject invalid policies.", "Runtime runs your handler as an OS process per runtime, version and session (idle TTL 15 minutes, up to 16 sessions); the agent calls the simulator with unmodified boto3.", "Traces and metrics flow through OpenTelemetry into the X-Ray and CloudWatch views."],
  limits: ["Runtimes do not host real containers or Strands/LangGraph frameworks: the agent is the Vyomi JSON spec over the local model, or your handler in a local process. Docker backend is not verified.", "Dependencies are not installed per runtime; the host Python must already have them.", "A runtime created with a customJWTAuthorizer verifies inbound JWTs; one without an authorizer is not authenticated. Memory extraction is inline and conversational only; memory is in-process and persists only with account state.", "Evaluators need a reachable model for judge-style scoring and otherwise fall back to the deterministic metric (the explanation says so). Batch and online evaluation configs and code-based evaluators are not implemented.", "InvokeAgentRuntimeCommand runs a documented subset of sh (; && ||, > >>, echo pwd ls cat env python3 -c/script) on the code sandbox in a per-session workspace, streaming stdout/stderr per command; no pipes, pip, npm, git or real shell. Streaming (InvokeAgentRuntime SSE, A2A message/stream) emits per model token as produced on Mesh; the Nano wire delivers the body whole. USER_FEDERATION OAuth works (authorization code + PKCE, callback + CompleteResourceTokenAuth); workload access tokens are not signature-verified."],
  nano: ["Memory, gateway and runtime spec run in pure Python. Runtime is a subset: handler functions only, same thread, no per-session isolation, and boto3 is not available. Cedar is enforced in the browser by the Cedar Rust core compiled to WebAssembly (4.4 MB, loaded at boot); if it fails to load an ENFORCE engine fails closed. Gateway openApi / mcpServer targets, OAuth token exchange, non-local JWKS discovery and agent-spec webhook tools reach the network through the allow-listed egress relay (hosted relay: public https origins on its allow-list; local tunnel: origins mapped with vyomi-tunnel gateway-backend) and report the reason when none is reachable. smithyModel targets run against the in-browser services."],
  mesh: ["Cedar is enforced with cedarpy (the same decisions as the in-browser cedar-wasm). Process isolation only, not microVMs. The simulator's Cognito pools also serve the hosted-UI authorization-code + PKCE endpoints used by USER_FEDERATION.", "Gateway targets of kind smithyModel (restJson1 / awsJson1_x Smithy JSON AST) are callable against the simulator's own AWS APIs. AWS_IAM gateways always verify the SigV4 signature of IAM access keys held by the simulator; ambient dev credentials are admitted as unverified unless VYOMI_AGENTCORE_SIGV4_STRICT=1."],
});

def("aws.bedrock.guardrails", ["/bedrock/guardrails", "/bedrock/guardrails/:id"], {
  title: "Guardrails: scope and limits",
  intro: "CreateGuardrail, versions and ApplyGuardrail over core/bedrock_guardrails_core.py; the Test panel calls ApplyGuardrail on the chosen version.",
  real: ["Content filters, denied topics, word filters (custom + profanity), PII and regex filters (block or mask), and contextual grounding/relevance scores are enforced on Converse, InvokeModel, streaming and ApplyGuardrail."],
  limits: ["Matching uses a lexicon, regex and local-model scoring, not the managed classifiers; strengths are ordinal, not calibrated. Image content, Automated Reasoning and cross-region configs are rejected."],
});
def("aws.bedrock.prompt-management", ["/bedrock/prompt-management", "/bedrock/prompt-management/:id"], {
  title: "Prompt management: scope and limits",
  intro: "CreatePrompt, UpdatePrompt, CreatePromptVersion, GetPrompt and ListPrompts with a test run through Converse.",
  real: ["Prompts keep a working draft and numbered immutable versions; {{variables}} are detected; Flow Prompt nodes can reference a prompt ARN."],
  limits: ["TEXT variants only (no chat variants, tool configuration or A/B comparison view). Customer-managed encryption keys are not applied."],
});
def("aws.bedrock.flows", ["/bedrock/flows", "/bedrock/flows/:id"], {
  title: "Flows: scope and limits",
  intro: "CreateFlow, PrepareFlow, versions, aliases and InvokeFlow (with execution tracing), run by a graph runner and edited on a drag-and-drop canvas.",
  real: ["Input, Output, InlineCode, Prompt (inline or a managed prompt), Condition, Iterator + Collector, Agent, KnowledgeBase, LambdaFunction, Retrieval (S3 get), Storage (S3 put) and Loop nodes with Data and Conditional connections. A node fires when all its inputs have arrived. The Test panel runs the prepared draft (TSTALIASID) with enableTrace and shows per-node input/output events."],
  limits: ["InlineCode nodes run Python_3 on the code sandbox; Lex nodes are rejected (no NLU runtime), and graphs may not contain cycles outside a Loop body. The Loop node is Vyomi's reading of the LoopInput / LoopController shape. Prompt, Agent and KnowledgeBase nodes use the single small local model. Canvas positions live in this browser, not in the flow definition. 1000 node executions per invoke."],
});
def("aws.bedrock.evaluations", ["/bedrock/evaluations", "/bedrock/evaluations/:id"], {
  title: "Evaluations: scope and limits",
  intro: "CreateEvaluationJob for automatic model evaluation, LLM-as-a-judge, RAG evaluation over a knowledge base, and human-workflow jobs.",
  real: ["Jobs read a JSONL dataset (up to 1000 records) from S3, generate answers with the model or the knowledge base, score them and write per-record rows plus report.json to S3. Long jobs run in batches and report progress. Scorers: token F1, ROUGE-L, exact match, embedding cosine, robustness, toxicity lexicon, and judge metrics (correctness, completeness, helpfulness, coherence, relevance, instruction following, tone, harmfulness, stereotyping, refusal, faithfulness, citation precision/coverage, context relevance/coverage, custom rating scales)."],
  limits: ["The judge is the single small local model, so judged scores are far less reliable than the managed judge models; unparsable verdicts are counted as unscored. Not BERTScore or the real-world-knowledge scorer. The human-workflow job type writes the model responses but the Ground Truth work team and rating UI are not simulated, so it stays InProgress awaiting reviewers."],
});
def("aws.bedrock.model-access", ["/bedrock/model-access"], {
  title: "Model access: scope and limits",
  intro: "GetFoundationModelAvailability for every listed model.",
  limits: ["Every served model is AVAILABLE and AUTHORIZED: there is no agreement or entitlement request workflow, because the models are local open models."],
});
def("aws.bedrock.settings", ["/bedrock/settings"], {
  title: "Settings: scope and limits",
  intro: "Put/Get/DeleteModelInvocationLoggingConfiguration.",
  real: ["Each successful InvokeModel and Converse delivers a record to S3 (gzip JSON, AWSLogs layout) and/or a CloudWatch Logs group."],
  limits: ["Image, video and embedding delivery flags are stored but those payloads are not produced. Large-data S3 overflow is not used."],
});
def("aws.bedrock.prompt-optimization", ["/bedrock/prompt-optimization"], {
  title: "Prompt optimization: scope and limits",
  intro: "OptimizePrompt, answered by a meta-prompt on the local model.",
  limits: ["Not the managed optimizer: quality is that of the local model. Dataset-driven optimization jobs are not simulated."],
});
def("aws.bedrock.automated-reasoning", ["/bedrock/automated-reasoning"], {
  title: "Automated Reasoning: not in scope",
  intro: "Needs an SMT-solver pipeline that formalises natural-language policies. Use Guardrails content, topic and grounding checks instead.",
});
def("aws.bedrock.data-automation", ["/bedrock/data-automation"], {
  title: "Data Automation: scope and limits",
  intro: "Projects, blueprints and InvokeDataAutomationAsync / InvokeDataAutomation on the real wire, with S3 in and out (job_metadata.json, standard_output and custom_output result.json).",
  real: ["Text-layer documents (PDF, DOCX, XLSX, PPTX, CSV, HTML, Markdown, text) are parsed without a model.", "Images (png, jpeg, gif, webp) are read by a small open vision model (SmolVLM-500M) for OCR text and a one-line summary.", "Blueprint (custom) output is one JSON-schema-constrained model call per blueprint: typed values, or null when a field is absent."],
  limits: ["Quality is that of a small open model: no confidence scores, bounding boxes, layout elements or tables; dense layouts and handwriting are unreliable, so check the values.", "Scanned PDFs have no OCR (no page rasteriser) and fail with a ClientError. Audio and video are not supported.", "Libraries, blueprint optimization, CopyBlueprintStage, EventBridge notifications, KMS and PII settings are accepted or rejected but not executed."],
  nano: ["Images need the Mesh vision model, so Nano runs text documents only; custom (blueprint) output on Nano is not supported because the in-browser model cannot run in a background job."],
  mesh: ["Needs the vision pack for images; custom output on text documents uses the default chat model."],
});

/* ---------------------------------------------------------------- GCP Agent Platform */
def("gcp.vertex.overview", ["/vertex-ai"], {
  title: "Agent Platform: scope and limits",
  intro: "The Vertex AI product, renamed Agent Platform. Resource counts and the legacy pages read the real aiplatform REST wire.",
  real: ["Prompts go through generateContent on the local model seam. Publisher models come from /v1/publishers/-/models. Deployments are Agent Engine reasoningEngines."],
  limits: ["Lower Overview cards are approximate. There is no 'Enable billing' banner: account state is not simulated.", "Declared not in scope (each page says why and what to use instead): Claude models, Ray, Training clusters. Gateways, MCP Servers, Policies, Security and Provisioned Throughput are real pages (see their own scope panels)."],
  nano: ["Chat is answered by WebLLM (WebGPU)."],
  mesh: ["Chat is answered by llama.cpp (Qwen3-4B-Instruct-2507 Q4)."],
});
def("gcp.vertex.studio", ["/vertex-ai/studio", "/vertex-ai/studio/prompt"], {
  title: "Studio: scope and limits",
  intro: "The landing prompt box and the freeform, chat and embeddings tool at /studio/prompt.",
  real: ["Prompts are answered through generateContent by the local open model, not by Gemini."],
  limits: ["The Models/Agents toggle and rail match the console layout; no capture exists for the deeper tool, so it is kept as is."],
});
def("gcp.vertex.model-garden", ["/vertex-ai/model-garden"], {
  title: "Model Garden: scope and limits",
  intro: "Collections, tasks, providers and search over the simulator's model catalogue.",
  real: ["Cards come from the publisher-model catalogue (the ten native models), with Serverless and Self-deployed chips."],
  limits: ["The catalogue has about ten models, not Google's 128. The 'What's new' strip is omitted.", "There is no deploy action from a model card."],
});
def("gcp.vertex.model-detail", ["/vertex-ai/model-garden/:publisher/:id"], {
  title: "Model detail: scope and limits",
  intro: "Latest, Overview and Documentation tabs with Model ID, version and tags.",
  limits: ["The layout is matched to a Gemini capture; content is the simulator's catalogue entry. Models answer from local open models, not the named vendor model."],
});
def("gcp.vertex.tuning", ["/vertex-ai/tuning", "/vertex-ai/tuning/:location/:id"], {
  title: "Tuning: scope and limits",
  intro: "tuningJobs create, get, list and cancel over the real aiplatform REST wire.",
  real: [HEAD_REAL, "On success a tuned Model and an Endpoint exist and endpoints/{id}:predict answers from the head with instances [{text}] (or {query, document} for a reranker).", LORA_REAL + " The tuned endpoint also answers :generateContent and :predict with {prompt} or {messages}."],
  metadata: [VENDOR_META],
  limits: [HEAD_CAPS, LORA_CAPS, "The training dataset is read from fake-gcs when it is configured, otherwise from the shared simulated object store (same bucket name).", "Vertex job and tuned-model records are not rebuilt after a reload for chat LoRA; trained heads are.", "The older Training > Model tuning tab is a metadata list."],
  nano: [NANO_TRAIN, NANO_LORA + " Import uses models:upload with an artifactUri holding the adapter and deployModel to an endpoint; tuned chat answers come from the tab, which must stay open."],
  mesh: ["Heads train in a background Python thread. Chat LoRA runs for real; serving through llama-server --lora was verified only against a fake server."],
});
def("gcp.vertex.agent-garden", ["/vertex-ai/agent-garden"], {
  title: "Agent Garden: scope and limits",
  intro: "Eleven agent blueprints with use-case, tool and capability filters.",
  limits: ["The catalogue and filters follow the real console; the docs record no deployment behaviour beyond the Deployments list."],
});
def("gcp.vertex.deployments", ["/vertex-ai/deployments"], {
  title: "Deployments: scope and limits",
  intro: "Agent Engine reasoningEngines listed over the real aiplatform REST wire.",
  limits: ["A thin list over gcp_agentengine_core; no capture exists to compare deeper behaviour."],
});
def("gcp.vertex.sessions", ["/vertex-ai/sessions"], {
  title: "Sessions: scope and limits",
  intro: "Sessions of an Agent Engine deployment: list, create, delete and read events over reasoningEngines/ID/sessions.",
  real: ["The same sessions the agent's :query / create_session calls keep, so a conversation held through the SDK shows here."],
  limits: ["Events carry the text and tool-call parts the Vyomi agent runtime produces; there is no ADK state delta editor."],
});
def("gcp.vertex.memory-bank", ["/vertex-ai/memory-bank"], {
  title: "Memory Bank: scope and limits",
  intro: "Long-term facts per scope for an Agent Engine deployment: create, list, delete, retrieve by similarity, generate from a conversation.",
  real: ["Retrieval ranks by cosine over the local embedding seam; generation asks the local chat model for facts."],
  limits: ["With no embedding model the labelled vyomi-hash-embed fallback is used (stable, not semantic). Generation answers 503 when no chat model runs. Quality is the small model's."],
});
def("gcp.vertex.rag-engine", ["/vertex-ai/rag-engine"], {
  title: "RAG Engine: scope and limits",
  intro: "RAG corpora and files with chunking, and retrieveContexts.",
  real: ["Files arrive by upload (text, base64, or the multipart bodies the SDK sends) or by import from the simulated Cloud Storage (gs:// object or prefix). Chunks are embedded with the local embedding model and retrieved by cosine kNN, or hybrid with BM25 (hybridSearch.alpha), with distance / similarity thresholds and an optional rerank. File and chunk counts are live."],
  limits: ["Exact scan, no HNSW or external vector database. The reranker is an embedding + lexical blend, not Google's rank service. No Drive, Slack, Jira or SharePoint import, and no metadata filters. Text-layer PDFs and Office files are parsed in pure Python (no OCR or layout parsing)."],
});
def("gcp.vertex.search", ["/vertex-ai/search", "/vertex-ai/app-builder"], {
  title: "Search and App Builder: scope and limits",
  intro: "Vertex AI Search data stores, documents and apps over the discoveryengine REST shapes.",
  real: ["Documents come in inline or from the simulated Cloud Storage (content, custom or document schema). Search ranks by hybrid BM25 plus embedding similarity and returns snippets; ticking Generate summary asks the local chat model for a cited summary."],
  limits: ["The summary is written by the small local model, not Gemini, and says so; with no model running the response lists summarySkippedReasons. No semantic ranker, filters, facets, connectors, website crawling or BigQuery import."],
});
def("gcp.vertex.agent-retrieval", ["/vertex-ai/agent-retrieval"], {
  title: "Agent Retrieval: scope and limits",
  intro: "One query across every RAG corpus and Search data store in the project.",
  limits: ["Results are listed per source, not fused or reranked across sources."],
});
def("gcp.vertex.evaluation", ["/vertex-ai/evaluation"], {
  title: "Evaluation: scope and limits",
  intro: "Evaluation runs and evaluateInstances for exact match, BLEU and ROUGE.",
  real: ["A run generates with the local model (or uses responses you supply) and scores each row; the scores are computed, not simulated."],
  limits: ["No Gemini autorater or pointwise/pairwise model-based metrics. Up to 100 rows per run."],
});
def("gcp.vertex.metadata", ["/vertex-ai/metadata"], {
  title: "Metadata: scope and limits",
  intro: "ML Metadata artifacts, executions and contexts in the default metadata store.",
  limits: ["Records are stored and listed; lineage graph queries and schema validation are not implemented."],
});
def("gcp.vertex.monitoring", ["/vertex-ai/monitoring"], {
  title: "Monitoring: scope and limits",
  intro: "Model deployment monitoring jobs on an endpoint, with pause and resume.",
  limits: ["The job record and lifecycle are real. No drift or skew statistics are computed, so there are no anomaly results."],
});
def("gcp.vertex.registry", ["/vertex-ai/agent-registry", "/vertex-ai/adk", "/vertex-ai/topology"], {
  title: "Agent Registry, ADK and Topology: scope and limits",
  intro: "Views over the Agent Engine deployments: a catalogue, a deploy form and a graph of agent, model and tools.",
  limits: ["Agents are declarative Vyomi agent specs run by the local model; Google ADK Python code and pickled classes are not executed."],
});
def("gcp.vertex.out-of-scope", ["/vertex-ai/training-clusters", "/vertex-ai/ray"], {
  title: "Not in scope for Vyomi",
  intro: "These pages need vendor-hosted capacity the simulator does not host. Each page names the reason and what to use instead.",
});
def("gcp.vertex.gateways", ["/vertex-ai/gateways", "/vertex-ai/gateways/:location/:id"], {
  title: "Gateways: scope and limits",
  intro: "One MCP endpoint in front of your tool servers, with its own authorization and an optional Cedar policy.",
  real: ["A gateway is a real MCP endpoint (POST /gateways/{id}/mcp: initialize, tools/list, tools/call) on the AgentCore gateway engine. Attaching an MCP server creates a real target; its tools are listed live and called through the gateway. JWT authorization verifies the token against the issuer's keys.", "The detail page lists the live tool catalog, calls a tool (policy applies) and attaches or detaches a policy."],
  limits: ["Google publishes no API for Agent Gateway: the agentGateways resource is Vyomi's own (vyomiExtension). The backing AgentCore gateway also shows in the AWS console of the same account, prefixed gcp-.", "Authorization is None or JWT (OIDC); Google IAM and Google-managed identities are not modelled. Registries, traffic splitting and quotas are not implemented."],
  nano: ["Tool calls to external MCP servers go through the allow-listed egress relay (a tool error with the reason when none is reachable). JWKS of non-local issuers use the same relay."],
  mesh: ["Calls to MCP servers and JWKS discovery go straight out from the appliance."],
});
def("gcp.vertex.mcp-servers", ["/vertex-ai/mcp-servers"], {
  title: "MCP Servers: scope and limits",
  intro: "A registry of the MCP servers your agents may use, each with an optional auth header.",
  real: ["Register any streamable-HTTP MCP server; List tools performs a live initialize and tools/list against it. Attach a server to a Gateway to serve its tools behind that gateway."],
  limits: ["This is your own registry. Google's catalogue of managed MCP servers is a vendor-hosted service and is not simulated. Servers are called from the simulator, so they must be reachable from it.", "The auth header value is stored in the account state and never shown again; there is no OAuth flow for registry entries."],
  nano: ["Reaching a server needs the allow-listed egress relay (hosted: public https origins on its allow-list; local tunnel: origins you map)."],
});
def("gcp.vertex.policies", ["/vertex-ai/policies"], {
  title: "Policies: scope and limits",
  intro: "Cedar policies that decide which callers may use which gateway tools.",
  real: ["Each policy is a real Cedar policy evaluated by cedarpy (Mesh) or cedar-wasm (Nano) on every gateway tools/call and on tools/list (principal = JWT subject, action = server___tool, context.input = arguments). ENFORCE denies by default; LOG_ONLY allows and records. Test runs the engine without a call."],
  limits: ["Google's org-level agent policies have no public API: agentPolicies is Vyomi's own resource (vyomiExtension). One policy per gateway."],
  nano: ["cedarpy is not in the browser: the same Cedar core runs as WebAssembly (cedar-wasm), so decisions match Mesh; if it fails to load, an ENFORCE gateway denies every call (fail closed)."],
  mesh: ["Cedar is enforced with cedarpy (Rust)."],
});
def("gcp.vertex.security", ["/vertex-ai/security"], {
  title: "Security: scope and limits",
  intro: "Model Armor templates and a tester for sanitizeUserPrompt / sanitizeModelResponse.",
  real: ["Templates with Responsible AI filters, prompt-injection and jailbreak detection and basic sensitive-data protection are evaluated for real by the Bedrock Guardrails engine; findings carry byte ranges for sensitive data."],
  limits: ["Detection is keyword, local-embedding and regex scoring: toy-grade next to Google's models, never a security control. Malicious-URI detection (Safe Browsing) and advanced sensitive-data templates (Cloud DLP) are reported EXECUTION_SKIPPED. Prompt injection applies to user prompts only.", "There are no floor settings and no Security Command Center or Cloud Logging findings: the page keeps the last 200 results of this simulator."],
});
def("gcp.vertex.provisioned-throughput", ["/vertex-ai/provisioned-throughput"], {
  title: "Provisioned Throughput: scope and limits",
  intro: "Orders for generative model units with a commitment term.",
  real: ["Create, list and delete orders with a model, units, a term and an end date."],
  limits: ["Bookkeeping only: nothing is reserved, enforced or billed, because a local model has no shared capacity to commit. Google publishes no create API for it, so the path is a Vyomi extension."],
});
def("gcp.vertex.endpoints", ["/vertex-ai/endpoints", "/vertex-ai/endpoints/:location/:id"], {
  title: "Endpoints: scope and limits",
  intro: "Endpoints from the existing aiplatform REST pages.",
  real: ["Tuned and imported models appear as endpoints; :predict answers from the trained head, :generateContent from an imported chat adapter."],
  limits: ["No capture exists to verify the page against, so it is kept as it was."],
  nano: ["An imported chat model is served only while the Nano tab is open and owns the engine; otherwise the call fails with 503 (unavailable). The default model is never a fallback."],
});

/* ---------------------------------------------------------------- Azure Foundry */
def("azure.foundry.overview", ["/foundry"], {
  title: "Foundry: scope and limits",
  intro: "The Microsoft Foundry hub blade over real ARM lists of Azure AI resources.",
  real: ["Overview and Dashboard follow the real chrome, title, chips and left menu. Resource lists are real ARM reads (Microsoft.CognitiveServices accounts by kind, Microsoft.Search services). Model tiles show only models this simulator serves."],
  real: ["Agents (Assistants API), Content filters (enforced on deployments), Fine-tuning and the AI Search blade are real. Evaluations (Azure OpenAI Evals API) and Prompt flow (flow.dag.yaml DAGs on the shared flow runner) are real over the Azure OpenAI engine. Machine Learning says plainly that it is not in scope, with what to use instead."],
  limits: ["Evaluations: string_check, text_similarity (rouge/bleu/fuzzy/cosine), label_model and score_model graders, up to 1000 rows; the judge is the small local model so judged scores are indicative; python graders and logs sources are rejected. Prompt flow: llm and prompt nodes only (python tool nodes rejected), management endpoints are a Vyomi extension, state is in memory.", "Foundry project pages (model catalog, project deployments, playground) are not built.", "Hero and capability-card illustrations are plain blocks. The group membership of the sub-menu was inferred; the capture never expanded it."],
});
def("azure.foundry.finetuning", ["/foundry/finetuning", "/foundry/finetuning/:jobId"], {
  title: "Fine-tuning: scope and limits",
  intro: "Azure OpenAI files and fine_tuning/jobs (create, list, get, cancel, events), also under /openai/v1.",
  real: [HEAD_REAL, "The fine-tuned model ft:<base>:<suffix>:<id> can be deployed through ARM; chat/completions on that deployment returns the label as the assistant message with vyomiTrained and vyomiScores. This is a Vyomi extension: real Azure has no classification endpoint.", LORA_REAL + " Events are per optimiser step (train_loss)."],
  metadata: [VENDOR_META],
  limits: [HEAD_CAPS, LORA_CAPS, "Hyperparameter is n_epochs for heads. The openai SDK keeps vyomiTraining through model_extra.", "Registering an externally trained LoRA uses a Vyomi extension (POST /openai/vyomi/custom-models, deployed with model format Vyomi); no real Azure API does this."],
  nano: [NANO_TRAIN, NANO_LORA],
  mesh: ["Heads train in a background Python thread. Chat LoRA runs for real; serving through llama-server --lora was verified only against a fake server."],
});
def("azure.foundry.openai", ["/foundry/openai"], {
  title: "Azure OpenAI: scope and limits",
  intro: "ARM list of Azure OpenAI accounts, opening the existing account blade.",
  real: ["Fine-tuned ft: models can be deployed to an account through ARM."],
  limits: ["Chat is answered by the local open model, not by an OpenAI model. Responses on a fine-tuned head or imported adapter carry vyomiTrained: true."],
  nano: ["WebLLM answers chat (WebGPU)."],
  mesh: ["llama.cpp answers chat."],
});
def("azure.foundry.search", ["/foundry/search"], {
  title: "AI Search: scope and limits",
  intro: "ARM list of Microsoft.Search/searchServices, backed by the azure_search_core engine.",
  real: ["Names open the AI Search blade: create a service, indexes (JSON definition), a search explorer with document upload, indexers (run + status), data sources and admin/query keys. All are real ARM calls into the azure_search_core engine."],
  limits: ["Blob, Cosmos DB and Azure SQL data sources are read by indexers (Cosmos and SQL from the simulated stores). The semantic ranker is an approximation (embedding similarity + term coverage), not Microsoft's. Vector profile designer, scaling and networking panels are not built."],
});
def("azure.aisearch", ["/aisearch", "/aisearch/:rg/:name", "/aisearch/:rg/:name/:panel"], {
  title: "AI Search: scope and limits",
  intro: "Microsoft.Search/searchServices over core/azure_search_core.py (pure Python, runs on Nano and the Mesh).",
  real: ["Create, delete and list services; admin and query keys; indexes, documents (index, merge, delete) and queries with filters, facets and counts; BM25 keyword, vector, hybrid (RRF) and semantic queries; data sources for Blob, Cosmos DB and Azure SQL; indexers with run, status, field mappings and incremental high-water-mark runs; skillsets (split, merge, embedding) with index projections."],
  limits: ["Vectors are scanned exactly (no HNSW). The semantic ranker is an approximation, so reranker scores and order differ from Azure. Skills other than split, merge and embedding fail the indexer by name (no OCR, entity or image skills); no knowledge store, scoring profiles or Lucene parser."],
});
def("azure.foundry.agents", ["/foundry/agents"], {
  title: "Agents: scope and limits",
  intro: "Create agents and chat with them through the Assistants API (assistants, threads, messages, runs) on a deployment of an Azure OpenAI or Foundry resource.",
  real: ["The page makes the same calls as the openai SDK; a run executes the model over the thread. Tools: function, code_interpreter (the model's Python really runs in a restricted sandbox; stdout in run steps, written files saved to /files) and file_search (vector stores chunk and embed your files, the top passages go to the model and come back as file_citation annotations)."],
  limits: ["The code interpreter is a restricted sandbox, not a VM: no network, no image outputs, and on Nano only the Python standard library. file_search ranks by embedding similarity (no ranking_options, no expiry policies, default chunking). The model is the local open model, not an OpenAI model."],
  nano: ["The chat model is WebLLM in the browser (WebGPU)."],
  mesh: ["llama.cpp answers."],
});
def("azure.foundry.filters", ["/foundry/filters"], {
  title: "Content filters: scope and limits",
  intro: "Custom content filters (Microsoft.CognitiveServices raiPolicies) with per-category thresholds, assigned to a deployment.",
  real: ["A deployment that names a custom filter returns HTTP 400 content_filter for a blocked prompt and finish_reason content_filter for a blocked completion. Matching runs on the guardrails engine."],
  limits: ["Hate, Sexual, Violence and the Jailbreak prompt shield only; Self-harm, protected material, blocklists and annotate-only mode are not modelled. Detection is keyword lists plus the local embedding model: a development stand-in, not a safety guarantee. The Microsoft default policies do not block."],
});
def("azure.foundry.notinscope", ["/foundry/evaluations", "/foundry/promptflow"], {
  title: "Not in scope for Vyomi",
  intro: "These Foundry products need an evaluation job runner or a flow runtime Vyomi does not have.",
  limits: ["The page states the reason and what to use instead."],
});
def("azure.foundry.ml", ["/foundry/ml"], {
  title: "Machine Learning: scope and limits",
  intro: "Machine Learning workspaces.",
  limits: ["Not in scope: managed compute clusters, registries and pipeline services cannot run in a browser tab or a small Codespace. The page says so and points to Fine-tuning."],
});
def("azure.foundry.other", ["/foundry/all", "/foundry/foundry", "/foundry/speech", "/foundry/language", "/foundry/translator", "/foundry/safety", "/foundry/vision", "/foundry/anomaly", "/foundry/docs"], {
  title: "Foundry lists: scope and limits",
  intro: "Real ARM lists (Microsoft.CognitiveServices/accounts filtered by kind); names open the existing account blade.",
  limits: ["Only the list and the account blade are Foundry-hub work; the captured tenant had no subscription, so list pages have no capture to compare with."],
});

const ALL = Object.values(E);

/** Entry for a cloud ("aws" | "gcp" | "azure") and a hash-route path, or null. More specific patterns win. */
export function scopeFor(cloud, path) {
  const hit = ALL.filter((e) => e.id.startsWith(cloud + ".") && e.patterns.some((p) => match(p, path)));
  if (hit.length <= 1) return hit[0] || null;
  const score = (e) => Math.max(...e.patterns.filter((p) => match(p, path)).map((p) => p.split("/").filter((s) => !s.startsWith(":")).length));
  return hit.sort((a, b) => score(b) - score(a))[0];
}

export const SCOPE_ENTRIES = ALL;
