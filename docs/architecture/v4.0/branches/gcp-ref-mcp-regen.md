# v4/gcp-ref-mcp-regen

Regenerates the generated MCP knowledge (`cmd/vyomi/mcp_matrix.json`, `mcp_caps.json.gz`) after the GCP reference-architecture merge (PR #659) changed capability JSONs. CI check "MCP knowledge is up to date" was failing on trunk.

## Changes
- `python3 scripts/gen_mcp_matrix.py` output only; `--check` passes.

## Design decisions
- Generated files only; no hand edits.

## Open issues
- None.
