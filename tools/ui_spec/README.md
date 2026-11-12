# UI spec extractor

Turns private captures of a native cloud console into `ui-spec/<cloud>/<service>.json`:
a text-only contract listing the nav, list columns and actions, detail tabs and create-form
fields. Shape: `ui-spec/schema.json`. See `docs/architecture/v4.0/V4-NATIVE-FIDELITY-CONSOLES-PLAN.md` §3–4.

## Run

```sh
# draft every captured service (stdlib only, Python 3.11+, deterministic)
python3 tools/ui_spec/extract.py --captures <crawl-dir> --out ui-spec/aws

# one service; write next to a reviewed spec without touching it
python3 tools/ui_spec/extract.py --captures <crawl-dir> --out ui-spec/aws \
    --service ec2 --suffix .draft.json
```

`<crawl-dir>` holds `manifest.jsonl` and the `A-<svc>/`, `C-<svc>/` capture folders (private
repo). Console path names map to Vyomi keys (`dynamodbv2` → `dynamodb.json`).

A spec with `"status": "reviewed"` is never overwritten unless you pass `--force`.

## How specs are used

1. **Draft**: the extractor reads page text only (no DOM). It finds breadcrumbs, the side nav,
   `Resource (N)` tables (columns, header actions, empty state), clicked tabs, `Step N` wizards
   and form labels. Guesses carry `"confidence": "low"`.
2. **Review**: a person or agent compares the draft with the screenshots, fixes field types,
   defaults and options, and adds anything the crawl didn't reach. Those additions get
   `"provenance": "reference"`. Then set `"status": "reviewed"`. Pilots: `s3`, `dynamodb`.
3. **Build**: `consoles/<cloud>/services/<service>/` is implemented against the spec.
4. **Verify**: the Playwright UI-conformance suite loads each Vyomi page and checks that every
   nav item, column, header action, tab and field label in the spec is present. It reports a
   per-service %. Items marked `confidence: low` or `provenance: reference` are reported but
   don't fail the run.

## The rule

Specs are committed to a **public** repo, so they hold **text facts only**: labels, column
names, field names, option values and helper strings of 120 characters or less.

- Never paste long AWS/GCP/Azure copy. Never copy screenshots or `.txt` captures into this repo.
- No account data. The extractor drops unmasked account IDs, emails, GUIDs, ARNs, access-key
  IDs, resource IDs and every resource name it sees in table rows or detail pages. Instance
  pages use `{resource-name}`. Capture paths mask instance names with `*`.
- Check by hand anyway before committing.
