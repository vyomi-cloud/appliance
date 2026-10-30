# Writing a reviewed UI spec (ui-spec/<cloud>/<service>.json)

The spec is the contract a v4 console page set is built and gated against: the UI-conformance
gate checks every element it lists, and agents cannot change it during their run (the gate
reads it from the base branch). An incomplete spec lets a weak console pass; an invented one
sends agents after things that don't exist. Accuracy matters more than size.

## Inputs
- Schema: `ui-spec/schema.json`. Reference-quality examples: `ui-spec/aws/s3.json`, `ui-spec/aws/dynamodb.json`
  (status "reviewed" — study them first).
- Drafts (AWS only): `ui-spec/aws/<service>.json` from `tools/ui_spec/extract.py` (status "draft").
- Real-console captures (PRIVATE, read/view only, never copy into the repo):
  `/Users/sudhirganti/Applications/simulator/appliance/console_captures/<cloud>-live/`
  - `manifest.jsonl` — one line per capture (url, svc, depth, label, tab, file)
  - `A-<svc>/NNN-L{1,2,3}-<slug>.png|.txt` (+ `--tab-NN-…`) — product pages; view the PNGs
  - `C-forms/` (GCP/Azure) or `C-<svc>/` (AWS) — create forms, `step-N` screenshots
  - Caveats: the GCP project had no billing (Compute/SQL/… create forms show "Enable billing");
    the Azure account had no subscription (create wizards show "No subscriptions"); some
    crawls only reached the landing page. Where the capture is missing or blocked, use your
    knowledge of the CURRENT console and mark those items `"provenance": "reference"`.

## What a reviewed spec contains
- `nav`: the product's left navigation tree (labels exactly as the console shows them).
- `pages`: every page a user reaches from that nav — list pages (exact column headers, header
  actions, filter placeholder, empty state), detail pages (title pattern `{resource-name}`, tabs,
  and `tab_panels` with each tab's sections and field labels), create/edit forms and wizards
  (steps, sections, every field with type / default / options / required).
- Focus on what Vyomi simulates. Out-of-scope products in the nav still get a page entry (a
  title is enough) so the console can declare them honestly.
- Set `"status": "reviewed"`, keep `captures` paths (relative, e.g. `A-sqs/003-L2-queues`), and
  `provenance` / `confidence` on items you could not see.

## Rules
- Text facts only: labels, column names, field names, option values, helper text ≤ 120 chars.
  No long paragraphs of vendor copy, no images, no account data (if anything looks like an
  account ID, email, ARN account number, access key ID, GUID or a user-created resource name,
  drop it or use `{resource-name}`).
- Validate every file against `ui-spec/schema.json` (python3 + jsonschema in a scratch venv
  under /private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/24162113-b0e5-411c-929c-4a1d13791861/scratchpad if needed).
- Write only your assigned `ui-spec/<cloud>/<service>.json` files. Do not git commit.
- Report per service: pages, fields, % from captures vs reference, notable gaps.
