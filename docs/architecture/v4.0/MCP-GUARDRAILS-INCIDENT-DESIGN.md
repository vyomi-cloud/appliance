# MCP guardrails: block, incident, TTL suspension (design draft, not implemented)

Status: draft from the owner's requirements on 2026-11-17/18. No code exists for this. Owner of implementation: whoever owns the MCP server, Mesh image and portal.

## Premise (guardrails for the MCP server inside Mesh and Nano)
The MCP server must never be able to:
1. access the Vyomi core containers inside Nano/Mesh;
2. tamper with the license fingerprint;
3. make the core simulator reach outside the tunnel;
4. change the behavior of a core container, or inject new code/instructions into it through MCP;
5. change behavior after limits are enforced upstream;
6. instrument agents or agentic behavior at runtime to compromise the system;
7. enable/disable internal controls that give unauthorised access into core containers;
8. intercept call flows in or out of the core containers.

## Required behavior
- The core containers block every incoming request at the MCP boundary that matches 1-8.
- Each block creates an incident in the Vyomi GitHub.
- Incidents can lead to TTL-driven suspension of that simulator's account.
- Every release must run these checks, go all green, and notify when any test fails.

## Proposed design
1. **Enforcement point**: a deny-by-default MCP gateway inside the core container, with an allow-list of MCP tools/methods. Anything not allow-listed, or matching a rule for 1-8, is rejected before reaching a handler. It must live where the MCP client cannot disable or reconfigure it (item 7).
2. **Incident reporter**: on a block, emit a signed event (simulator id, account, rule id, timestamp, request digest, no payloads/secrets) to the portal. The portal creates the GitHub issue. The core container holds no GitHub token; the reporter is write-only to the portal, which holds the credential.
3. **Suspension**: the portal owns a per-account violation counter. Policy (to decide): severity-weighted threshold, then a TTL countdown (e.g. 72 h) after which the simulator account is suspended, with a manual clear/appeal path that cancels the countdown.
4. **Tamper resistance**: signed gateway config tied to the license fingerprint; any config change, gateway bypass or reporter outage is itself an incident. Egress only via the tunnel (item 3), enforced by network policy, not by the MCP process.
5. **Release gate**: CI job per release runs the guardrail suite (below) plus the endurance estate cycles; red blocks the tag/image publish and posts a notification (channel to be chosen).

## Guardrail tests (one per premise item, each asserts block AND incident)
| # | Attempt through MCP | Expected |
|---|---|---|
| 1 | list/exec/inspect a core container | rejected, incident |
| 2 | read/modify license fingerprint | rejected, incident |
| 3 | make the core open a connection outside the tunnel | blocked, incident |
| 4 | push code/instructions/config into a core container | rejected, incident |
| 5 | alter behavior/limits after upstream enforcement | rejected, incident |
| 6 | attach instrumentation/hooks to agents | rejected, incident |
| 7 | toggle an internal control | rejected, incident |
| 8 | tap/proxy call flows in or out of a core container | blocked, incident |

## Open decisions
- Violation vs probe vs bug: one strike or threshold; false-positive handling.
- TTL length, appeal/clear path, who can clear.
- Incident repo, labels, and dedupe (one issue per simulator per rule per window).
- Notification channel for release-gate failures.
- Relationship to the pending v4.0.1 Mesh-only release pipeline change.
