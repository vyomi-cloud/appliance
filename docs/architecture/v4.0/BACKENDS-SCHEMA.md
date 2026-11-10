# Backends data schema ("How Vyomi runs this service")

One file per cloud: `core/capabilities/backends/<aws|gcp|azure>.json`. Keys are service ids,
equal to the registry file names in `core/capabilities/<cloud>/*.json` (every registry file must
have a key). Bundled into each console at build time (`vyomi-backends:<cloud>` in
`consoles/build.mjs`); shown in the console's info/help side panel.

```json
{
  "s3": {
    "title": "Amazon S3",
    "summary": "One or two sentences: what runs the service and how a call reaches it.",
    "wire": ["AWS SDKs (S3 REST)", "aws s3 / s3api CLI"],
    "offline": { "kind": "opensource|inhouse|hybrid", "tech": ["MinIO"], "notes": "..." },
    "nano":    { "kind": "opensource|inhouse|hybrid|unavailable", "tech": ["..."], "notes": "..." },
    "differs": ["What behaves differently from the real cloud"],
    "notInScope": ["What is deliberately not simulated"],
    "sources": ["https://upstream-project.example"]
  }
}
```

Rules (checked by `tests/conformance/test_backends_registry.py`):

- `title`, `summary`: non-empty strings. `wire`, `differs`, `notInScope`, `sources`: lists of
  non-empty strings (`wire` must not be empty; the others may be `[]`).
- `offline.kind` is `opensource` (an upstream engine), `inhouse` (built by Vyomi) or `hybrid`.
  `nano.kind` additionally allows `unavailable` (not possible in the browser), which requires
  non-empty `notes`. `tech` is a list of strings.
- Fidelity numbers are NOT stored here: the console derives them from the capability registry
  (levels `full` / `limited` = Dev Simplified / `config_only` / `not_simulated` per substrate).
- A service with no entry shows "Backend details for this service are not documented yet";
  the UI never invents text.
- A cloud whose file does not exist yet is skipped by the test and bundled as `{}`.
