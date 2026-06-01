# azure-tickets — Azure reference app for CloudLearn

Go + chi web app that exercises **7 Azure services** through the real
`azure-sdk-for-go` SDK, all pointed at the CloudLearn simulator endpoint.
Symmetric to `tests/e2e/java-orders` (AWS) and `tests/e2e/go-inventory` (GCP).

## Services exercised

| # | Service | SDK / call |
|---|---|---|
| 1 | **Azure Database for PostgreSQL Flexible** | `pgx` direct connection — `tickets` table CRUD |
| 2 | **Azure Blob Storage** | `azblob.Client.UploadBuffer` — ticket attachments |
| 3 | **Azure Service Bus** | `azservicebus.Client` — `TicketCreated` queue + background worker |
| 4 | **Azure Event Grid** | REST POST — `TicketCreated` event publish |
| 5 | **Azure Key Vault (secrets)** | `azsecrets.Client.GetSecret` — DB password at startup |
| 6 | **Azure Key Vault (keys)** | `azkeys.Client.Encrypt` — PII column encryption |
| 7 | **Azure RBAC** | REST GET `…/Microsoft.Authorization/roleAssignments` — boot-time probe (Cedar-backed in simulator) |

## Quick start

```bash
# Against the appliance VM
export CLOUDLEARN_ENDPOINT=http://192.168.252.7:9000
export AZURE_SUBSCRIPTION_ID=cl-sub

go run .
# listens on :8082

# Create a ticket
curl -X POST http://localhost:8082/tickets \
  -H "Content-Type: application/json" \
  -d '{"title":"first","body":"hello","pii":"secret","attachment_b64":"aGVsbG8="}'

# List
curl http://localhost:8082/tickets
```

## API-pass test

```bash
go test -v -run TestApiPass
```

The test suite includes 5 checks:

1. `TestApiPass_Health` — `/health` returns ok + per-service status
2. `TestApiPass_CreateTicket` — full ticket-create round-trip exercising Postgres + Blob + Service Bus + Event Grid + Key Vault encrypt
3. `TestApiPass_ListTickets` — read-back via Postgres
4. `TestApiPass_DirectAzureServices` — verifies every Azure SDK client initialized
5. `TestApiPass_EventGridPublish` — direct Event Grid REST surface check

All tests skip cleanly when the simulator is unreachable.

## Tier interaction

Free tier locks Service Bus + Event Grid (eventing category). When running
against Free, the app emits warnings ("eventing publish failed; non-fatal")
but POST /tickets still returns 201 — the design is resilient to tier-locked
optional features (same pattern as java-orders / go-inventory).

## Docker

```bash
docker build -t azure-tickets .
docker run --rm -p 8082:8082 \
  -e CLOUDLEARN_ENDPOINT=http://host.docker.internal:9000 \
  azure-tickets
```

## Notes

- The Azure SDK Go clients use a custom `cloud.Configuration` so every
  Azure service URL is rewritten to the simulator endpoint. This is the
  same trick `boto3 --endpoint-url=…` uses for AWS.
- DB password is fetched from Key Vault if reachable; falls back to
  `cloudlearn:cloudlearn` baked into `defaultPgURL`.
- PII encryption uses Key Vault keys' `A256GCM` algorithm; ciphertext is
  stored as `BYTEA`. If Key Vault is unreachable, plaintext is stored
  with a warning log (graceful degradation).
