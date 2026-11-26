# v4/nano-agent-course

Owner: Rohith (prepared by Claude, 2026-11-26) - Started: 2026-11-26 - Base: origin/v4-on-main (ed15da1d0) - Status: built, measured on four in-browser models, not merged

## Purpose
A second AWS Vyomi Labs course, "Build Your First Agent (Nano)": a free Nano user, in the browser with no Mesh and no appliance, builds and deploys a
working Facilities help-desk agent driven by an in-browser model. It is separate from the Mesh enterprise course (own title, data file, progress key,
project folder); the existing course and its aws-nano edition are unchanged. Final page points to the Mesh course as the upgrade path.

## Architecture
| Change | Where |
|---|---|
| Course content (7 chapters, 28 blocks, 16 runnable) | `vyomilabs/content/nano_agent/chapters.py`, code in `files/` |
| Generator: course JSON, listing, editor project, `courses/<slug>/aws/` | `vyomilabs/content/nano_agent/build_agent_course.py` |
| Course data, listing, project | `wasm/labs/data/aws-agent-nano.json`, `wasm/labs/data/courses.json`, `wasm/labs/project/aws-agent-nano.json` |
| Project folder (generated, never hand-edited) | `courses/vyomi-labs-nano-agent/aws/` |
| Labs page lists both courses as separate cards; `?course=` selects; own progress and editor keys; no image/intro required | `wasm/labs/labs.js` (additive), `wasm/labs/index.html` (v91) |
| A later chapter may save a file again (tools.py, agent.py): refresh the module Python already imported | `wasm/labs/pyrun-worker.js` |
| Lambda invoke awaits an in-browser model (replay), so a deployed Lambda can call Bedrock Converse and embeddings on Nano | `core/aws_wire_router.py` ahandle(), mirrored to `wasm/core/` |
| Evidence: block runner, logs, prototype results | `docs/labs/nano-agent-evidence/` |

## Design decisions
| Decision | Why |
|---|---|
| Strict JSON "pick one action" protocol: parser (first balanced object), schema validation, one retry carrying the exact error | A small model chooses well from a short list and formats free-form tool calls badly. Measured in chapter 2. |
| Menu follows turn state; nudge with an answer template after each result; runtime composes ticket confirmations and fills sources from evidence | These made a 1.5B model reliable; each was added after a measured failure |
| Hybrid retrieval (0.5 keyword + 0.5 MiniLM cosine); SUPPORT_MIN 0.38 is also the "documents do not support an answer" test | Keywords alone and embeddings alone both measured worse on unsupported questions |
| Guardrails (step limit, allow-list, grounding, injection) are plain code | Testable with no model; cannot be argued with |
| Writes are idempotent (deterministic ticket id + conditional put before the SQS send); memory is written only at the end of the turn | A Nano Lambda that calls a model is replayed; replays must not duplicate side effects |
| Grading is plain code; the 15-question EVAL set was tuned on, a separate 8-question HOLDOUT was written after tuning and run once | Honest generalisation figure |

## Measured results
Headless Chrome (WebGPU, Apple Metal), every runnable block of the course in order, on the generated course data; logs in `docs/labs/nano-agent-evidence/logs/course-<model>.jsonl`, summary in `results.json`.
A model is supported only if all 16 runnable blocks pass. No caveats on unsupported models.

| Model | Ch1 | Ch2 | Ch3 | Ch4 | Ch5 | Ch6 | Ch7 | Verdict |
|---|---|---|---|---|---|---|---|---|
| Qwen2.5 1.5B | 2/2 | 3/3 | 3/3 | 1/1 | 2/2 | 2/2 | 3/3 | supported (16/16) |
| Qwen2.5 0.5B | 2/2 | 1/3 | 3/3 | 0/1 | 2/2 | 2/2 | 2/3 | unsupported (protocol, memory, evaluation gate) |
| Llama 3.2 1B | 2/2 | 1/3 | 2/3 | 1/1 | 2/2 | 1/2 | 2/3 | unsupported (protocol, first agent, guarded agent, safety questions) |
| SmolLM2 360M | 2/2 | 1/3 | 2/3 | 0/1 | 2/2 | 1/2 | 1/3 | unsupported (protocol, agent, memory, guarded agent, deploy, safety) |

Agent only, outside the Lambda (`step1-prototype/`): 15-question tuned set Qwen 1.5B 15/15, 0.5B 10/15, Llama 5/15, SmolLM2 2/15. Held-out 8 questions (written after tuning, run once) Qwen 1.5B 8/8, 0.5B 5/8, Llama 3/8, SmolLM2 3/8.
Deployed as a Nano Lambda and graded by the chapter 7 harness: Qwen 1.5B 15/15 across docs, record, ticket, multi-step, refuse, injection and memory.
Retrieval (chapter 5): keyword, dense and hybrid each put the right document first for 13/13 questions; highest score of an unsupported question: keyword 0.25, dense 0.40, hybrid 0.28 against the 0.38 threshold.
A first run of chapter 4 failed on a wrong assertion in `try_memory.py` (not the agent); kept as `course-qwen2.5-1.5b.run1-try_memory-assert-bug.jsonl`, fixed, and the full run repeated 16/16.

## Known limits
- The retrieval threshold was tuned on a small set. The holdout is 8 questions: a small sample.
- Model downloads (about 1 GB) and the embedding model (CDN) need the network once.
- Llama 3.2 1B shard downloads fail in headless Chrome without a Node-side fetch workaround; see the logs.
