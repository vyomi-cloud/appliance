/* Vertex AI over the native publisher-model REST API (generateContent / countTokens / embedContent). */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

export const LOCATION = "us-central1";
// mirrors core/ai_models_core.py GEMINI_MODELS / GEMINI_EMBED
export const GEMINI = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"];
export const EMBED = ["text-embedding-005", "text-embedding-004", "gemini-embedding-001"];
const path = (model, op) => `/v1/projects/${encodeURIComponent(getProject())}/locations/${LOCATION}/publishers/google/models/${model}:${op}`;
const contents = (text) => [{ role: "user", parts: [{ text }] }];

export const generate = (model, text, system, maxOutputTokens = 256) => restJson("POST", path(model, "generateContent"), { body: { contents: contents(text), ...(system ? { systemInstruction: { parts: [{ text: system }] } } : {}), generationConfig: { maxOutputTokens, temperature: 0.7 } } });
export const countTokens = (model, text) => restJson("POST", path(model, "countTokens"), { body: { contents: contents(text) } });
export const embed = (model, text) => restJson("POST", path(model, "embedContent"), { body: { content: { parts: [{ text }] } } });
