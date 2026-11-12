# Mesh runbook: the v4.0.0 gateway + event-bus backends on the real appliance

Branch `v4/mesh-gateway-eventbus-ready`. What it proves: the shared gateway engine (GCP API Gateway, AWS HTTP/REST API, Azure APIM) and the
shared event bus (Eventarc) work on the REAL appliance stack, not only on Nano / the dev server.

## What was wrong before this branch
Static finding, then confirmed by running the stack: the shared cores were only reachable through Nano's router. On the real FastAPI server
- `/gcpgw/<id>` and `Host: *.gateway.dev` fell through to the S3 catch-all (`NoSuchBucket`),
- GCP API Gateway control plane (`/v1/.../apis|apiConfigs|gateways`) was answered by the pre-v4 handlers in `providers/gcp_services.py`,
- Eventarc triggers were answered by a stub in `core/nats_routes.py` (no validation, no retry, no dead-letter),
- Azure APIM data plane was the legacy `azure_dataplane._apim_handle` (no policies/quotas),
- API Keys v2 was not served in the shape the gateway checks against; the router's GCP project defaulted to `nano-project`.

Now `routes/gateway_eventbus_unified.py` (registered first in `server.py`) sends those paths to the same `AwsWireRouter` Nano uses, over the
appliance's durable stores. The Dockerfile already copies `core/ providers/ routes/` wholesale and `requirements.txt` has `cryptography`
(verified: the shipped `vyomi/appliance:v4-test` has cryptography 50.0.0), so no image-recipe change is needed, only a rebuild.

## Is the Mesh image stale? (one-liner, run through the tunnel)
```sh
curl -s http://127.0.0.1:19000/gcpgw/ghost/x ; echo; curl -s http://127.0.0.1:19000/v2/projects/vyomi-project/locations/global/keys
```
Fresh image: the first prints JSON `{"code":404,"message":"No gateway serves this host."}`.
Stale image: `<Error><Code>NoSuchBucket</Code>...` (the S3 handler). The test script runs the same probe and exits 3 with `STALE IMAGE`.

## Refresh the image (owner steps; nothing here is done by the agent)
The Mesh compose (`codespace/.devcontainer/mesh/docker-compose.mesh.yml`) uses `${VYOMI_SIMULATOR_IMAGE:-vyomi/appliance:v4-preview}` with
`pull_policy: always`, so the Codespace pulls whatever tag is in the registry at boot. The image is published by the owner:
1. Land this branch on the trunk (`v4-on-main`) via the integrator.
2. Publish from CI (multi-arch, never push a local arm64-only build):
   `gh workflow run docker-publish.yml --ref v4-on-main -f tag=v4-test`   (or `-f tag=v4-preview` for the default tag)
   Check: `docker buildx imagetools inspect vyomi/appliance:v4-test` shows linux/amd64 and linux/arm64.
3. Mesh must pull it: set `VYOMI_SIMULATOR_IMAGE=vyomi/appliance:v4-test` for the Codespace (see the board request in
   `Collab-AWS-GCP-Azure.md`), then start a NEW Mesh session (stop/resume of an old Codespace keeps the container but `pull_policy: always`
   re-pulls on `compose up`; if in doubt `docker compose ... pull simulator && up -d --force-recreate simulator` inside the Codespace).
4. Re-run the stale probe above.

## Run the suite against Mesh
```sh
vyomi-tunnel forward vyomi-mesh-simulator-1 19000:9000        # keep running (the owner's forward is usually already up)
cd <appliance worktree>
SIM_URL=http://127.0.0.1:19000 PROJECT=vyomi-project OUT=/tmp/gw-mesh.json node tests/conformance/nightly/gcp-gateway-eventbus-real.mjs
```
Mesh cannot reach this laptop, so without `LOCAL=1` the checks that need a backend / JWKS / event receiver are printed as `SKIP` with the reason
(never PASS). Still proven on Mesh: control plane, Host + `/gcpgw/` routing, 401 / 400 / 429, refused JWTs (wrong audience, expired, wrong issuer,
tampered, unknown key), APIM 401s, API/REST invoke URLs answering 404 for unrouted paths, and the event bus's retry (>= 3 recorded attempts)
and dead-letter to a Pub/Sub topic against an unreachable receiver. To prove 2xx forwarding on Mesh too, edit the spec backend to a public
https URL the Codespace can reach (the script uses `https://backend.rt.test` + the override hook below, which only works locally).

Also on Mesh: `SIM_URL=... PROJECT=vyomi-project node tests/conformance/nightly/gcp-validation.mjs` (BASE=<SIM_URL>) and
`SIM_URL=... PROJECT=vyomi-project ONLY=eventarc,apigateway,apigateway-apis,apigateway-keys node tests/conformance/nightly/gcp-v4-roundtrip.mjs`
(Playwright env: `PLAYWRIGHT_BROWSERS_PATH`, `NODE_PATH` as in the nightly docs).

## Full proof on a local real stack (what was run for this branch)
```sh
docker run -d --name gw-real -p 127.0.0.1:9400:9000 -e CLOUDLEARN_TIER_ENFORCE=0 -e VYOMI_NO_TELEMETRY=1 \
  -e VYOMI_GATEWAY_BACKEND_OVERRIDES="https://backend.rt.test=http://host.docker.internal:9411,https://issuer.rt.test=http://host.docker.internal:9411" \
  -v $(mktemp -d):/data --memory 1500m vyomi/appliance:<your-fresh-tag>
SIM_URL=http://127.0.0.1:9400 LOCAL=1 node tests/conformance/nightly/gcp-gateway-eventbus-real.mjs
```
`VYOMI_GATEWAY_BACKEND_OVERRIDES` is an operator/test hook (core/gateway_common): it redirects only the exact https origins listed, for backend
calls and for JWKS/issuer fetches (the control plane only accepts https backends and https `x-google-jwks_uri`).
Not for production; do not set it on a customer/Mesh appliance.

To test unpublished code without building the image: bind-mount the worktree's `core/ providers/ routes/ server.py` read-only over `/app/...`
of an existing v4 image (used for the results in the branch document).

## Known limits
- Host-style `https://<id>.execute-api.localhost:9443` is rewritten to the path-style route by an ASGI middleware only when the request reaches the
  app with that Host; on Mesh the tunnel forwards the Host you send, so use curl `-H "Host: <id>.execute-api.x"` or the path-style URL.
- The first Eventarc attempt runs inline in the Pub/Sub publish request; retries run lazily on the next API call (any call to the trigger's
  `/deliveries` or the control plane advances them).
