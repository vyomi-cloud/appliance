# v4/gcp-console-refresh

Owner: appliance session - Started: 2026-11-14 - Base: origin/v4-on-main (3da4a6dc1) - Status: ready to merge

## Purpose
GCP Cloud Storage bucket detail: the header Refresh reloaded bucket metadata and IAM but not the object list, so a file uploaded from the CLI never appeared after clicking Refresh.

## Architecture
`consoles/src/gcp/services/storage/BucketDetail.jsx`: `tick` state bumped by `reloadAll`, passed to `Objects`, included in the `useAsync` deps of `api.listLevel`. `wasm/v4/gcp` rebuilt with `node build.mjs --cloud gcp`.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| tick counter in deps | lifting the list fetch into the parent | smallest change, same pattern as the other panes |

## Open issues
- [ ] Verify on Nano (:8099, service worker) before the portal vendor step (owner: integrator)
