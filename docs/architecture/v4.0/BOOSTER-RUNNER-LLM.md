# Booster remote LLM on GitHub-hosted runners (SPIKE, off by default)

Branch `v4/ngrunnerllm`. Everything is gated by `VYOMI_BOOSTER_REMOTE_LLM=1`; with it unset nothing changes (the in-Codespace AI pack,
3B Qwen + bge-small, ~2.8 GB AI bucket, stays exactly as in AI-PACK-AUDIT.md).

> **OPEN RISK (owner has accepted it):** GitHub Actions terms restrict use unrelated to building/testing/deploying the repo's
> software. Not verified with GitHub. Also: the runner repo must be **public** - private repos would exhaust the 2000 free
> minutes/month almost immediately (N runners x up to 40 h).

## 1. Shape

```
 Nano console / SDK / agents          Codespace booster (2 cores, 8 GB, LLM-free)          relay hub (wasm/relay)         GitHub-hosted runners (user's public repo)
  boto3 / google-genai / AzureOpenAI -> llm_core -> loopback gateway ---HTTPS /llm/*---->   runner-llm-hub.mjs   <--WSS /llm-runner---   runner-llm-dial.mjs -> ollama serve (127.0.0.1)
                                         (booster_runner_pool)  (outbound only)                                    (runner dials OUT)       one runner per catalogue entry
```

Neither the booster nor a runner accepts an inbound connection from the internet. Both only make outbound calls to the relay.

* Booster: `core/booster_remote_llm.py` (attach/detach/info), `core/booster_runner_pool.py` (pool, window, rotation, idle, mapping),
  gateway pool mode in `core/booster_llm_gateway.py`, capacity in `core/booster.py` (`_memory_split`: AI bucket = 0 and the whole cap goes
  to compute while attached), `core/booster_ai.py` (admit refuses, plan starts no model servers, status = remote).
* Relay: `wasm/relay/runner-llm-hub.mjs` (planes `/llm-runner` upgrade and `/llm/*` HTTP, wired in `local-relay.mjs`).
* Runner: `docker/booster-runner-llm/` (`entrypoint-ollama.sh` + `runner-llm-dial.mjs` + `models.json`; `entrypoint.sh` is the raw
  llama-server variant with actions/cache + sha256), workflow templates `.github/booster/llm-runner-ollama.yml` / `llm-runner.yml`.

## 2. Model catalogue (`docker/booster-runner-llm/models.json`)

EAGER: when the booster starts, **every non-optional runner is dispatched at once**. One 4 vCPU / 16 GB runner each.

| runner | role | models (Ollama tag) | RAM est. |
|---|---|---|---|
| fast | fast chat + embeddings | `qwen2.5:3b-instruct-q4_K_M` + `nomic-embed-text` | 2.8 + 0.6 GB |
| general | general instruct | `qwen2.5:7b-instruct-q4_K_M` | 6.2 GB |
| coder | code | `qwen2.5-coder:7b-instruct-q4_K_M` | 6.2 GB |
| agents | tool use / agents | `llama3.1:8b-instruct-q4_K_M` | 6.8 GB |
| xl (optional, `VYOMI_RUNNER_INCLUDE_OPTIONAL=1`) | higher quality, slow | `qwen2.5:14b-instruct-q4_K_M` | 11.5 GB |

RAM figures are estimates; the Ollama tags were **not** verified against registry.ollama.ai (no network calls to it in the spike).
Sanity max 20 runners (GitHub Free concurrent-job limit); there is no per-user cap any more.

**Cache implication (actions/cache: 10 GB per repo, 7-day idle eviction, LRU).** Key = the runner's tag list. 3B+nomic is ~2.2 GB, each
7-8B is ~4.7-4.9 GB, 14B is ~9 GB: the four core runners need ~14 GB of weights, so the cache can never hold all of them; LRU evicts
the least recently restored one and that runner cold-pulls (several minutes on a hosted runner) at its next start/rotation. 14B can't share
the cache with anything. Mitigation: keep `fast` + two 7-8B models cached, accept cold pulls for the rest; the 503 + Retry-After
"starting" state covers it. (Not measured here.)

## 3. Cloud API model ids -> catalogue (native SDK agents pick a model by the id they already use)

`aliases` in `models.json` (exact match, then longest fnmatch pattern; extra mappings via `VYOMI_RUNNER_MODEL_ALIASES` JSON). `llm_core`'s
existing `VYOMI_LLM_MODEL_MAP` is generated from it at attach; the gateway re-resolves patterns it cannot express.

* **Bedrock** (`converse`, `invoke_model`): `meta.llama*` -> llama3.1-8b, `mistral.*` -> qwen2.5-7b, `amazon.nova-micro/lite*` -> 3b, `amazon.nova-pro*` / `anthropic.claude*` -> 7b, `amazon.titan-embed*` / `cohere.embed*` -> nomic.
* **Vertex / Gemini Developer alias lane** (google-genai): `gemini-*-flash*` -> 3b, `gemini-*-pro*` -> 7b, `codestral*` -> coder-7b, `text-embedding-*` / `gemini-embedding*` -> nomic.
* **Azure OpenAI** (`AzureOpenAI`, the SDK sends the *deployment name*): `gpt-4o-mini*`/`gpt-35*` -> 3b, `gpt-4o*`/`gpt-4*` -> 7b, `o1*` -> 14b, `text-embedding-*` -> nomic; any custom deployment name -> `VYOMI_RUNNER_MODEL_ALIASES={"my-coder":"qwen2.5-coder-7b"}`. Unknown ids fall to the default chat / embed model.
* Direct catalogue ids (`llama3.1-8b`) and the OpenAI/Ollama lanes `/v1/*`, `/api/*` work unmodified.

## 4. Lifecycle

* **Window (wall clock, not metered):** from booster start, Pro 30 h, Max 40 h (`WINDOW_HOURS` in `booster_runner_pool.py`, one place).
  Runner minutes are not counted against the booster-hours ledger. At the end the whole pool is destroyed.
  Console countdown: `Models: 12h 40m left of 30h`; `window.warning` is `60m` / `10m` / `2m` for the toasts.
* **Idle:** no inference request to any model, no VM activity (`POST /booster/ai/activity`, loopback) and no console/API request for 60 min ->
  the whole pool is destroyed and the `on_destroy` hook fires (the booster registers "stop the booster" in `booster_remote_llm._destroy_hooks`).
* **Rotation (jobs die at 6 h; Codespace launch at 8 h):** a runner exits itself at 5h50m (`RUNNER_TTL_S`). At 5h30m (`ROTATE_S`) the booster tells
  the portal to dispatch a successor (`start` with `rotation:true`, **fresh token** carrying `role=llm-runner`, `model=<runner id>`, `session_end` = window end).
  The relay holds the second dial as `next`; the old runner keeps serving until `next` reports `ready`, then requests switch, the old runner gets
  `{type:"drain"}`, finishes in-flight requests and exits 0 (relay force-closes after 60 s). Result: **no gap** when the successor is ready first
  (tested: continuous traffic, 0 failures). If the old runner dies first, requests get `503` + `Retry-After` until the successor is ready (tested).
  The workflow's concurrency group is per run so a rotation dispatch does not cancel its predecessor. Rotation is skipped in the last 10 min of the window.
* **Self-heal:** a runner that was ready and vanishes from the relay is re-dispatched; a dispatch that never becomes ready is retried after 15 min.
* **Per-model state** for the console: `starting | ready | rotating | draining | stopped`. Not-ready model -> `503` + `Retry-After: 15`, body
  `{error:{code:"RunnerStarting", status:"starting"}}`; never blocks, never falls back to a local model.

## 5. Console data (D)

`GET /booster/ai/models` (also `/api/booster/models`, on the booster app and the loopback gateway): `{pool, window:{phase,deadline,left_s,label,warning,idle_in_s,...}, models:[{id,runner,role,kind,ollama,state,optional,ram_mb,size_mb,endpoints:{aws:[...],gcp:[...],azure:[...]},tokens_per_s,requests}], events}`.
`tokens_per_s` = last non-streaming reply (`usage.completion_tokens`/elapsed, or Ollama `eval_count/eval_duration`). `/v1/models` and `/api/tags` list the same states.
**UI not built** (left as notes): add a "Models" panel to the Nano Connect booster card (wasm/nano-connect.js polls `booster-link.js` status; poll this endpoint every 5 s
only while a pool is attached): row per model = name, role, state dot (starting/ready/rotating/draining/stopped), per-cloud id chips with copy buttons,
tok/s, a small test-chat box that POSTs `/v1/chat/completions` through the booster gateway with `model=<id>`; header = window label with 60/10/2-min warnings.

## 6. Portal-side design (portal repo not in this worktree; NOT implemented)

* **GitHub App** on the user's runner repo (public): `actions:write` (dispatch/cancel), `workflows:write` + `contents:write` (install the templates and
  `docker/booster-runner-llm/`), `actions:read`.
* **Booster -> portal:** `POST /api/booster/runner/start {runner, ollama_tags, ttl_s, rotation}` and `/stop {runner}`, authenticated with the booster session token
  (`HttpDispatcher`, `VYOMI_RUNNER_DISPATCH_URL`). The portal mints the **runner token** itself (`mint(..., role="llm-runner", model=<runner id>, session_end=<window end>)`),
  and `workflow_dispatch`es `llm-runner-ollama.yml` with inputs `runner_token`, `relay_url`, `model`, `ollama_tags`, `ttl_s`. The token is masked in the first step
  (`::add-mask::`), passed to the job only through `env`, never argv, never echoed; `run-name` is constant. Inputs are visible to the repo owner (the user) only;
  the token is runner-role (cannot call the booster or the LLM plane), expires with the session, and a rotation always uses a fresh one.
* **Readiness** = the relay's view (`/llm/_status`), consistent with the existing session/ready webhook; no runner callbacks into the portal.
* **Identity of the compute:** all runners run in the *user's* account/quota ($0 to us, like the BYO-PAT Codespace model). Ledger: model-runner time is **not** metered
  against booster hours (wall-clock window only).
* **Failure modes:** dispatch API error (booster shows `starting`, retries); runner exceeds job cap (rotation covers it); GitHub outage / queue delay (503 starting);
  public-repo log exposure (mitigated: masks, no `set -x`, model server logs go to a file, constant `run-name`, no prompts anywhere); cache eviction (cold pull, minutes);
  relay down (booster: honest 503 "relay not reachable"); user cancels the run (hub sees disconnect -> self-heal re-dispatch unless the window is over).
* **Privacy:** prompts/completions transit booster -> relay -> runner over TLS and exist in runner RAM only; not logged by our code (the relay logs only link events; Ollama's
  log goes to an unprinted file). The runner is Microsoft-hosted infrastructure in the user's account; the relay operator (us) can in principle see traffic unless end-to-end encrypted
  (not done in the spike).

## 7. Tests and measurements

* `tests/conformance/test_booster_remote_llm.py` (41 checks): single remote runner, attach/detach, capacity not reserving the AI bucket, runner drop -> 503, no local fallback,
  role-scoped token auth on the dial-in, TTL / session_end expiry, no token in logs.
* `tests/conformance/test_booster_runner_pool.py` (44 checks): eager start, 503 starting, routing + cloud-id mapping, Models data, rotation (no gap; gap with Retry-After), window warnings + expiry, 60-min idle destroy (+ hook), sanity max.
  Both use the real relay + real runner dialer + a fake Ollama; time rules run on an injected clock.
* **Measured (relay hop, instant fake model, localhost):** direct vs booster-gateway -> relay -> runner dial: non-streaming 0.61 -> 2.01 ms median (+1.4 ms),
  streaming first chunk 0.34 -> 1.56 ms (+1.2 ms). Real overhead is dominated by the WAN legs (booster->relay, runner->relay), expect +tens to ~150 ms per request
  plus per-chunk jitter; negligible vs generation time.
* **NOT measured:** real tokens/s for the 3B in a 2-core/8 GB booster vs 3B/7B on a 4-core/16 GB runner, first-token latency, RAM saved. The Docker VM (7.75 GB) is exhausted by
  ~120 other containers, a 3B load was OOM-killed, and killing others' containers was out of scope. Harness is ready: image `vyomi-runllm-runner:spike`
  (`docker/booster-runner-llm/Dockerfile`), models in the session scratchpad, `bench.py` (prompt-eval / generation tok/s, streamed TTFT). Re-run on a free Docker VM
  (>= 10 GB) with `--cpus 2 --memory 8g` (booster) vs `--cpus 4 --memory 16g` (runner).
  Booster RAM saved is by construction: AI bucket 0 instead of 2.8 GB (test-asserted via `resource_budget`), i.e. +2.8 GB for VMs/services on an 8 GB Codespace.
  Expected from design notes (unmeasured): 3B Q4 ~4-6 tok/s on 2 cores, ~8-12 tok/s on 4 vCPU; 7B ~3-5 tok/s on 4 vCPU.

## 8. Not validated / what real validation needs

Everything GitHub-side (the workflow templates, Ollama install, actions/cache behaviour, hosted-runner outbound WSS, rotation overlap on real jobs, the portal dispatch API) is
untested: no GitHub calls were allowed. One real run, which only the owner can approve, should check: runner can dial the relay, cold pull time per model, cache hit time,
real tok/s, one full rotation at a shortened interval, and that no secret appears in the public run log.
