# v4/mesh-fetch-session-diagnostics

Owner: Mesh session (Sudhir) - Started: 2026-11-15 - Base: origin/v4-on-main (d7340c080) - Status: ready for review, not merged

## Purpose
Join Mesh failed with `Mesh reachable through the tunnel: HTTP 401 (MeshSessionRequired)`. Evidence (2026-11-15, two user attempts and one clean admin reproduction): the simulator container started with an EMPTY `VYOMI_MESH_SESSION_TOKEN`, `boot-mesh.sh` logged `could not fetch a session token`, and the portal received NO `/api/mesh/session/token` request at all during the ~60 s the script spent retrying. So `fetch_session` failed before reaching the portal and its `curl ... 2>/dev/null` threw the reason away.

## Change
`codespace/.devcontainer/mesh/boot-mesh.sh` `fetch_session` only: logs the codespace id and portal; retries up to 40 times (~4 min, `VYOMI_MESH_TOKEN_TRIES`) instead of 10; forces IPv4 (`vyomi.cloud` resolves AAAA first and the Codespace has no IPv6 route); logs every failed try with the HTTP status or the curl error text; the answer parser tolerates whitespace. Behaviour on success is unchanged, and it still fails closed.

## Not a root-cause fix
This makes the failure diagnosable and gives the network more time. If a boot still fails, the Codespace creation log now names the reason. Ship path: sandbox repo `vyomi-cloud/sandbox` main (Codespaces read the script from there); no image rebuild, no release/tag.

## Tests
Function run against a local stub portal: 404, 404, dropped connection, then 200 -> token, key and session_end exported on try 4; unreachable portal -> 3 logged tries then fails closed (rc=1).
