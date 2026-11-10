# Nightly needs-decision (owner/other-cloud items; the agents append, never delete)

## Azure, 2026-11-11 baseline on a bare simulator (v4-preview, no sibling backends)
ENV, not product (need sibling containers, the Docker socket, azure SDK / playwright installed): offline-sdk-python-azure-ops, offline-sdk-python-azure-vm-runcommand
(no `azure` python module), offline-ui-azure-* (playwright not resolvable from the checkout), offline-cli-azure (SQL connectionInfo needs real Postgres),
offline-cli-azure-app job executions (needs Docker to run the job), offline-post-create-azure-event-delivery (webhook delivery to the test receiver).
To verify on the runner stack (nightly-v4.yml), not here.
UNCLEAR: offline-sdk-go-azure-operationalinsights prints PASS lines but is scored 0 passed / 400 failed: check how the Go runner output is counted (harness bug?).
