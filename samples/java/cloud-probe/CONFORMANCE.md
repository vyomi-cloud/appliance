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
| `GET /compute/aws`    | compute (EC2) | EC2 RunInstances → DescribeInstances → TerminateInstances (the compute backend: Multipass/LXD on CloudMax, Docker on CloudLite+) |
| `GET /rds/aws`        | managed DB (RDS) | RDS CreateDBInstance → DescribeDBInstances → DeleteDBInstance (managed Postgres) |

`{cloud}` ∈ `aws | gcp | azure`. **Compute/RDS are AWS-only for now** (GCE/CloudSQL +
Azure VM/SQL equivalents aren't wired into the probe yet — the harness runs them via
`AWS_ONLY_SERVICES`). EC2 + RDS are **not** tier-gated (they run on Free); **NoSQL
(DynamoDB/Cosmos) requires Max tier**, so those two go red on a Free-tier appliance with
`X-Vyomi-Tier-Denied: tier_service_locked` — that's the gate working, not a probe bug.

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

## Live-run setup (verified 2026-06-24 — 12/14 green vs a Multipass appliance)
The HTTPS surfaces (Azure Key Vault/Cosmos, GCP HttpJson) need the appliance's
**mkcert/Caddy cert trusted by the JVM** and a **cert-matched hostname**. Exact steps
that took the run from 8/14 → 12/14 (the remaining 2 are the Max-tier NoSQL gate):

1. **Trust the appliance cert in a JVM truststore** — the launcher's mkcert CA is trusted
   by the OS but not the JVM:
   ```sh
   cp "$(/usr/libexec/java_home)/lib/security/cacerts" /tmp/probe-truststore.jks
   keytool -importcert -noprompt -trustcacerts -alias mkcert-ca \
     -file "$(mkcert -CAROOT)/rootCA.pem" -keystore /tmp/probe-truststore.jks -storepass changeit
   java -Djavax.net.ssl.trustStore=/tmp/probe-truststore.jks \
        -Djavax.net.ssl.trustStorePassword=changeit -jar target/cloud-probe.jar
   ```
2. **Reach the appliance via a name in the cert SAN.** The mkcert cert covers
   `vyomi.local`, `localhost`, `127.0.0.1`, `*.vault.localtest.me` — **not** the VM's LAN
   IP. If the probe host isn't the appliance host, bridge a cert-covered name to it
   (e.g. `socat TCP-LISTEN:9443,fork,reuseaddr TCP:<vm-ip>:9443`) and point Cosmos at it:
   `export CLOUDPROBE_COSMOS_ENDPOINT=https://localhost:9443/azure-data/cosmos/<account>`.
   (Key Vault already rides `*.vault.localtest.me → 127.0.0.1`.)
3. **Caddy must forward the port in `Host`** (the `kid`/Host risk above). The key-id is
   built from the request `Host`; if Caddy uses `header_up Host {host}` it **strips the
   port**, so the kid becomes `…vault.localtest.me/keys/…` (→ `:443`, refused). The source
   Caddyfile is correct (`{http.request.hostport}`); ensure the **running** appliance
   matches, then restart Caddy (admin API is off, so `caddy reload` won't work — restart
   the container).

**Tier note:** EC2 (`/compute/aws`) + RDS (`/rds/aws`) pass on **Free**. NoSQL
(`/probe/aws` DynamoDB, `/probe/azure` Cosmos) returns `403 tier_service_locked` until a
**Max-tier** license is active — transport/cert/endpoint are all proven, so those two flip
green the moment the tier is unlocked.
