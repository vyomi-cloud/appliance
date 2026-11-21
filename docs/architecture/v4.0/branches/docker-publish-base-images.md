# v4/docker-publish-base-images

Owner: Rohith (prepared by Claude, 2026-11-21) - Base: origin/v4-on-main (8c8ae09) - Status: ready for review

## Purpose
A manual or pre-release run of `docker-publish.yml` from any branch also pushed the base images under their STABLE tags
(`vyomi/instance:latest`, `vyomi/instance:ubuntu-24.04`, `vyomi/postgres:16-alpine-pgvector`, both registries). Every install
pulls those tags, so testing a branch image could silently replace what every user gets.

## Architecture
`.github/workflows/docker-publish.yml`: the "Resolve version + tags" step outputs `base_images=true` only for a stable release tag
(`vX.Y.Z`, no pre-release suffix) or a manual run with the new `base_images` input set. The instance and postgres build steps run
only then. The job summary says whether base images are published. The appliance and cloudsim images are unchanged.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Skip the base-image steps on manual and RC runs | Push them under the run's own tag | Compose files pin the stable tags, so a branch-tagged base image would never be pulled; building it only costs time |
| Opt-in input for a deliberate base-image hotfix | No manual path at all | A broken base image must be fixable without cutting an appliance release |
| RC tags no longer move the base images | Keep RCs as before | An RC is for testing; users on stable must not get RC base images |

## Open issues
- [ ] Base images are rebuilt on every stable release even when `packaging/instance` and `packaging/postgres` did not change (unchanged behaviour).

## Testing
- The real "Resolve version + tags" step run under five triggers: stable tag -> base images published; RC tag, manual with a tag,
  manual without a tag -> not published; manual with `base_images=true` -> published. Appliance tags unchanged in every case.
- actionlint: clean.
- Not run: a real workflow run (the next manual run shows the new summary line).
