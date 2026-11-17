# v4/nano-llm-start-hint

**Why:** On Nano, the Bedrock Playground answered "No local LLM backend is available on this substrate. (the local model has not been started)" and gave no way to start a model. The only loader was the "Local model" card on Bedrock > Overview.

**Changes:** `core/llm_core.py` returns a Nano-specific message that says where to load the model; `core/ai_models_core.py` no longer appends the generic suffix to it. The Playground has a "Load in-browser model (WebLLM)" button (`consoles/src/aws/services/bedrock/WebLlmLoader.jsx`) that preselects the model picked in the Playground and clears the error once loaded.

**Design:** the button only renders where `window.vyomiEnableWebLLM` exists (Nano), so offline/Mesh consoles are unchanged. The model is not persisted across reloads (WebLLM engine lives in the page).

**Open:** same button for the GCP (Vertex) and Azure playgrounds; not verified with a real WebGPU browser in CI.
