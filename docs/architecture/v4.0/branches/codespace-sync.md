# v4/codespace-sync

Owner: integrator session - Started: 2026-11-10 - Base: origin/v4-on-main (51efd2b1) - Status: in progress

## Purpose
Makes the appliance `codespace/.devcontainer/` the single source of the Codespace image. The sandbox repo had gained the sshd feature (PR #1) that the appliance copy lacked, while the appliance copy had the AI pack, LLM mesh and Azurite flags the sandbox lacked. This branch merges both into the appliance copy.

## Architecture
`codespace/.devcontainer/mesh/devcontainer.json` gains the sshd feature; `docker-compose.mesh.yml` gains `VYOMI_HOST_SSH_ADDR` and `extra_hosts`. `codespace/publish.sh` copies the tree to a sandbox checkout, then a PR goes to `vyomi-cloud/sandbox`.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Appliance is the only edit place; sandbox is published output | Sandbox as source (delete `codespace/`) | Release flow already versions the appliance; one place to review |

## Open issues
- [ ] Publish PR to `vyomi-cloud/sandbox` main (owner: integrator, needs owner OK)
- [ ] CI job to open the publish PR automatically (needs a write token set by the owner)
- [ ] Stale fork `vyomi-admin/sandbox` (Sept 24) to reset or delete (owner: user)
- [ ] Portal must stop using the stale fork as a Mesh copy (separate `portal/<topic>` branch)

## Testing
JSON and YAML parse. A real Codespace was NOT created from the merged files; the sshd part is the same as sandbox main, which was validated on a real Codespace earlier.
