# Vyomi Labs (AWS) Nano edition: verified end to end

FINAL RUN 2026-11-26 on `v4/labs-integration-final` (origin/v4/labs-integration merged with origin/v4-on-main, which adds chapter 14 "Design the RAG"). Headless Chrome with WebGPU, Nano preview on its own port, no Mesh anywhere. Raw logs in `docs/labs/nano-edition-evidence/final/` (`nomodel.jsonl`, `q15.jsonl` block level; `ui-nomodel.json`, `ui-q15.json` Deploy button; `labrun_*_rt.txt` in-process course runs). Drivers: `docs/labs/nano-edition-evidence/scripts/`.

## 0. Final numbers (14 chapters, chapter 14 included)
- Data: AWS Mesh 85 blocks / Nano 63 (49 runnable); GCP 89 / 83; Azure 95 / 89. Chapter 14's three blocks (loader, starting `rag-design.json`, `show_design.py`) are pure Python and carry both editions; no nano_note needed.
- Nano block level, AWS, 49 runnable blocks: no model 46/49 (ch1 `try_models`, `fail_models` and ch11 `retrieve_and_generate` need a model and say so); Qwen2.5 1.5B 49/49. Chapter 14 is 3/3 in both, and the later chapters that read the saved design (12, 6, 11) pass in both.
- Deploy button, all 14 chapters from the button: no model 12 "Deployed", ch10 and ch11 stop at the picker ("needs a model"); Qwen2.5 1.5B picked: all 14 "Deployed".
- `?edition=mesh` loads `aws.json` (banner "Mesh, enterprise"); default, `?edition=nano` and gcp load `<cloud>-nano.json`.
- Not re-run on the final code: SmolLM2 360M, Qwen2.5 0.5B, Llama 3.2 1B (section 2 keeps their earlier numbers for 13 chapters). The RAG Studio consoles themselves were checked only by their unit tests (`consoles/src/*/studio*.test.mjs`, `ragstudio.test.mjs`), not driven in the browser.
- Mesh edition in-process course runs (`python -m vyomilabs.labrun <cloud> 10 3 7 14 12 6 11 9 4 5 1 2 8 13`, `VYOMILABS_HAS_RUNTIME=1`, Python 3.13): AWS 62 pass / 1 fail (`cedar_enforce.py`: Cedar ENFORCE hides the tools from tools/list in this in-process server, a Mesh-only block that needs the full appliance); GCP 55 / 1 fail (`add_policy.py`, fails identically on the pre-merge branch); Azure 59 / 1 fail (`call_container_app.py`, known 503 from the sandbox). Remaining blocks are BLOCKED in-process (need `--endpoint`: AWS 6, others 0-1).

## Earlier measurement (13 chapters, before the merge)
Measured 2026-11-26 on `v4/labs-integration-verify` (from `origin/v4/labs-integration`), headless Chrome with WebGPU, Nano preview on its own port, no Mesh anywhere. Raw per-block logs and UI JSON: `docs/labs/nano-edition-evidence/verified/`. Drivers: `docs/labs/nano-edition-evidence/scripts/` (`plumb.mjs` block runner, `ui.mjs` Deploy-button driver, `sum.py`).

## 1. Edition selection
- `wasm/labs/data/aws-nano.json` (edition `nano`) has 13 chapters, 60 blocks, 48 runnable. Every Mesh-only block is absent. No block carries `needs_appliance`, and no Nano block imports a Mesh-only module (`iamkit`, `iam_models`, `iam_runtime`, `iam_tools`, ...). The one match for "Enforce" in `approve.py` is a code comment.
- The standalone Nano page (`/nano/labs/`, also `?cloud=aws`, `?edition=nano`) loads `aws-nano.json`. `?edition=mesh` loads `aws.json`. Checked by request interception.
- Cosmetic gap: with `?edition=mesh` on the standalone page the banner still reads "On the free Nano edition...".

## 2. Results, Nano edition (48 runnable blocks, block level, in order)
| Ch | No model | Qwen2.5 1.5B | SmolLM2 360M | Qwen2.5 0.5B |
|---|---|---|---|---|
| 1 | 0/2 | 2/2 | 1/2 | 1/2 |
| 2-5 | 16/16 | 16/16 | 16/16 | 16/16 |
| 6 | 3/4 | 4/4 | 4/4 | 4/4 |
| 7-13 | 26/26 | 26/26 | 26/26 | 26/26 |
| all | 45/48 | 48/48 | 47/48 | 47/48 |

Every cell for chapters 2-5 and 7-13 is the full count (3/3, 5/5, 5/5, 3/3 and 3/3, 5/5, 6/6, 5/5, 2/2, 2/2, 3/3).

Why each non-pass:
- No model: ch1 `try_models`, ch1 `fail_models` and ch6 `retrieve_and_generate` need a model and say so (ModelNotReady). Nothing else needs one.
- SmolLM2 360M: ch1 `try_models` fails. The assertion that the model asks for the tool is real, and this model answers in prose ("status is In Transit", invented). 0/8 tool calls in a repeat probe.
- Qwen2.5 0.5B: ch1 `try_models` fails. It cannot emit a valid tool call (2 invalid-call errors, the rest malformed like `asset_status:B-12`). 0/8.
- Qwen2.5 1.5B: 48/48. Repeat probe of the tool-call turn: 8/8 after the engine fixes (3 to 5 of 8 before them).
- Llama 3.2 1B: NOT re-run. Its weights could not be downloaded here (HF CDN shard requests fail with ERR_FAILED from headless Chrome although curl succeeds; retried 4 times, also through a Node-side route). The prior agent's ch1-6 result (19/20, no tool call) is not re-verified on this code. Honest gap.

Deploy button (`ui-no-model.json`, `ui-qwen2.5-1.5b.json`), all 13 chapters started from the button, no Mesh:
- No model: 11 chapters report "Deployed", ch1 and ch6 stop at the model picker (0 failed steps, "needs a model"). Skip works on every picker.
- Qwen2.5 1.5B picked from the picker: all 13 report "Deployed".

## 3. Bugs found and fixed (all engine or runtime; the course expectations were right)
| Symptom | Cause | Fix |
|---|---|---|
| ch4 `event_driven` "#3 vs #2" | Nano S3 invoked the Lambda with `s3:TestEvent` on PutBucketNotificationConfiguration (real S3 sends it to SQS/SNS only), so an extra ingestion job started | `core/s3_object_core.py`: no Lambda delivery for the test event |
| ch7 `memory_events` "4 vs 2" | `CreateEvent` appended the event, then called the model/embedder, which on Nano raises NeedAsync and replays the whole request, storing the event 2-3 times | `core/agentcore_ext_core.py`: do model/embedding calls before the first mutation |
| ch3 `tool_contract` KeyError | Lambda sandbox boto3 client had no `.exceptions` (`except ddb.exceptions.ConditionalCheckFailedException` raised AttributeError) | `core/lambda_sdk.py`: typed `ClientError` subclasses, `client.exceptions.<Code>`; test added |
| ch2 `invoke_agent`, `stop_session` | In-process Nano sessions all reported the interpreter's pid, so "other process / one process per session" could not hold | `core/agentcore_runtime_host.py`: virtual pid per in-process session; test updated |
| ch1 tool call flaky on small models | Tool turns sampled at 0.7; replies like `{'asset_id':'B-12'}` or a call wrapped in `{content: ...}` were treated as prose | `core/llm_core.py`: cold sampling for the envelope turn, Python-literal parsing, arguments-only and wrapped replies accepted for the one available tool |
| ch7 `memory_recall` on Qwen 0.5B | An empty fact list from the model suppressed extraction | `core/agentcore_ext_core.py`: empty list falls back to the first-person heuristic |

No course content change was needed, so nothing in `vyomilabs/content` or the generated data was edited. `wasm/core/` regenerated with `python3 wasm/build_cores.py` (`--check` clean).

Also fixed in the drivers: `ui.mjs` handled only the first model picker (it hung on chapters with two model steps), and now skips every picker; `plumb.mjs` reads the Nano edition data, takes `PORT`, and can reuse one profile for the model cache while clearing the Nano store (`CLEAR=1`).

Python tests, all green: `tests/vyomilabs`, `tests/test_identity_native.py`, `tests/test_tf*.py` (76 passed); `tests/conformance/test_lambda_sandbox_sdk.py`; also `test_agentcore_runtime_host`, `test_agentcore_facilities` (25), `test_llm_seam_v2`, `test_llm_async_bridge`, `test_local_llm_seam`, `test_ai_sdk_tools`, `test_s3_notifications`. `test_agentcore_auth_limits` fails with `KeyError: 'location'` in an OAuth redirect step unrelated to these files; not investigated.

## 4. Mesh-only, and why
The 12 chapters each drop 1 to 4 blocks from Nano (22 of the 82 Mesh-edition blocks are Mesh-only; Nano keeps 60): enterprise IAM Enforce and least-privilege-from-audit-log blocks (`iamkit`, `iam_models`, `iam_runtime`, `iam_tools`, `iam_approval`, `cedar_enforce`, `memory_guard`), failure labs that rely on real process and clock behaviour (`runaway`, `token_attacks`, `guardrail_bypass`, `poisoned_doc`, `dlq_ingest`, `expiry`), `risk_levels`, `screen`, `refusal`, `reingest`, `cost_meter`, `key_rotation`, `audit_chain`, `audit_who`, `ship_it`. They need the enforcing IAM engine, real queues and timers, or Terraform export that exist on the appliance or a Mesh, not in the browser.

## 5. Remaining gaps
- Llama 3.2 1B not re-verified (download blocked here).
- Tool calling with 360M and 0.5B models is not possible; ch1 `try_models` fails honestly for them. Qwen 1.5B is stochastic in principle (8/8 in the final probe, not a guarantee).
- Needs WebGPU and about 2 GB free disk for any model step; hosted agents fetch langgraph from PyPI once.
- Lambda `Timeout` not enforced; langgraph checkpointers unsupported (from the earlier status doc).
- The standalone `?edition=mesh` banner text (above).

## 6. Recommended default model
Qwen2.5 1.5B: the only model that passes ch1 and runs every chapter (48/48 block level, 13/13 via Deploy). The other three are plumbing-only, as the picker already labels them.
