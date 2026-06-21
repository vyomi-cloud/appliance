# cloud-probe — VM conformance checklist (v2.0.9)

Turns the **static-validated** v2.0.9 work (compiles green) into **verified-green**
by running the native cloud SDKs against a live appliance. Endpoints are kept
**separate per service per cloud** so each surface passes/fails independently.

## Endpoints (all separate — by design)
| Endpoint | Services | Native SDK → backend |
|---|---|---|
| `GET /probe/{cloud}`  | object store + NoSQL | S3/GCS/Blob, DynamoDB/Firestore/Cosmos |
| `GET /queue/{cloud}`  | messaging | SQS→ElasticMQ · Pub/Sub→emulator · Storage Queue→Azurite |
| `GET /secret/{cloud}` | secrets | Secrets Manager / Secret Manager / Key Vault Secrets → Vault |
| `GET /kms/{cloud}`    | KMS | KMS / Cloud KMS / Key Vault Keys → Vault transit (Azure = real RSA) |

`{cloud}` ∈ `aws | gcp | azure`.

## 1. Bring up the appliance
`vyomi up` (or the compose stack). Wait for the readiness banner — Wave 2 backends
(ElasticMQ, Vault, Azurite **blob+queue :10000/:10001**, Pub/Sub :8085, Firestore :8080)
must be up. Confirm `azure-storage-queue` is in `requirements.txt` and the Azurite
container runs the full `azurite` (not `azurite-blob`).

## 2. Start the probe (points at the appliance)
```sh
export CLOUDPROBE_ENDPOINT=http://<appliance>:9000     # sim (HTTP, SigV4 + S3 + Azure blob/queue)
export CLOUDPROBE_CADDY_HOST=<appliance>:9443          # HTTPS: Cosmos, GCP HttpJson (Secret/KMS), Key Vault
export FIRESTORE_EMULATOR_HOST=<appliance>:8080
export PUBSUB_EMULATOR_HOST=<appliance>:8085
mvn -q -DskipTests package
java -jar target/cloud-probe.jar                       # serves :8080
```
The **caddy cert must be trusted by the JVM** (same requirement the Cosmos probe
documents) — import it into the JVM truststore or run the probe where the cert is trusted.

## 3. Run the harness
```sh
./run-conformance.sh                  # or: ./run-conformance.sh http://<probe-host>:8080
```
Green = every endpoint returns `ok:true`. The script prints the exact failing
`steps` for any red surface.

## Runtime risks to watch (compile-clean, only a live run confirms)
- **GCP Secret/KMS (HttpJson):** gax builds HTTPS → must hit caddy :9443 with a trusted cert; the appliance's REST handlers must match **protojson** request/response shapes.
- **Azure Key Vault Keys:** native `CryptographyClient` does **RSA client-side**; verify create returns a usable public JWK and service-side decrypt round-trips. Watch challenge-auth (we pass a fake token; if the appliance emits a real challenge, `disableChallengeResourceVerification` may be needed).
- **Azure Storage Queue:** native-XML round-trip against Azurite (the AMQP→HTTP substitution for Service Bus — this is **not** Service Bus).
- **`kid` / Host header:** Key Vault decrypt + the secret/key `id`s are built from the request `Host`; confirm caddy preserves it so the SDK comes back to the appliance, not real `*.vault.azure.net`.

## Console parity (optional, same backends)
Each console CRUD writes to the **same backend** its SDK reads, so a console-created
queue/secret/key should be visible to the probe and vice-versa — spot-check by
creating one in the console, then re-running the relevant endpoint.
