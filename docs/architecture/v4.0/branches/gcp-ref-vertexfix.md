# v4/gcp-ref-vertexfix: Vertex simulator gaps found by the GCP reference app

Lane 6 of round 2 of the GCP 13/13 build. Base: `origin/v4/gcp-ref-integ` 77b2a7fa6.

## Changes
- Model Armor: templates accept proto integer enums (the SDK sends `alt=json;enum-encoding=int`) as well as strings, and answer in ints when asked.

## Design decisions
- Enum normalisation is a table keyed by JSON field name (core/gcp_agentgov_core.py `_ENUMS`); UNSPECIFIED (0) means "field not set".

## Open issues
- (filled in as the other three gaps land)
