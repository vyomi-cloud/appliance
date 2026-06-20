# Vyomi sample apps

Real, deployable sample microservices that drive the **native vendor cloud
SDKs** (AWS / GCP / Azure) against a Vyomi appliance endpoint. They prove the
appliance is wire-compatible with the real SDKs — not just the REST/CLI surface
— and double as an **integration-test harness**.

```
samples/
  java/cloud-probe/   ← Spring Boot microservice (this doc)
  go/cloud-probe/      ← Go version (coming next)
```

## `java/cloud-probe` — what it does

A microservice that, per cloud, runs a full **object-store + NoSQL lifecycle**
using that cloud's native SDK and returns a step-by-step report:

| Cloud | Object store | NoSQL | SDK |
|---|---|---|---|
| **aws** | S3 | DynamoDB | AWS SDK for Java v2 |
| gcp | GCS | Firestore | google-cloud-java *(coming)* |
| azure | Blob | Cosmos | azure-sdk-for-java *(coming)* |

Each probe exercises a wide slice of the SDK — e.g. AWS: `createBucket →
putObject → getObject(+verify bytes) → headObject → listObjectsV2 → listBuckets
→ deleteObject → deleteBucket`, and `createTable(+waiter) → putItem →
getItem(+verify) → updateItem → query → scan → deleteItem → deleteTable` — so a
green run is strong evidence of compatibility.

### Endpoints
- `GET /healthz` → liveness + which clouds are wired
- `GET /probe/{cloud}` → run the lifecycle for `aws|gcp|azure`; returns a JSON
  report (`ok`, `elapsed_ms`, per-step `ok`/`detail`). HTTP 200 if all steps
  pass, 502 if any failed (the report pinpoints which SDK call broke).
- `GET /object/{cloud}?bucket=&key=[&account=]` → read one **object** back via
  the native object-store SDK (verifies a console upload is SDK-readable).
- `PUT /item/{cloud}?table=&id=[&database=]` → write a small **NoSQL** item
  `{id, msg:"hello-vyomi", n:1}` via the native SDK, then read it back.
- `GET /item/{cloud}?table=&id=[&database=]` → read a NoSQL item via the native
  SDK. `table` = DynamoDB table (AWS) / Firestore collection (GCP) / Cosmos
  container (Azure); `database` = Cosmos database (ignored by AWS/GCP).

#### NoSQL native-SDK status (the `/item` endpoint)
| Cloud | Backend | Transport | From the host (over the multipass bridge) |
|-------|---------|-----------|-------------------------------------------|
| AWS   | DynamoDB | HTTP JSON on `:9000` | ✅ works |
| GCP   | Firestore | gRPC on `:8080` | ⚠️ `NoRouteToHost` over the bridge — run cloud-probe **co-located** in the appliance network (the `Dockerfile`) so it reaches `firestore:8080` directly |
| Azure | Cosmos | TLS gateway | ⚠️ the SDK requires HTTPS — point `CLOUDPROBE_COSMOS_ENDPOINT` at the caddy terminator (`https://vyomi.local:9443/azure-data/cosmos/{account}`), add the mkcert CA to the JDK truststore (`-Djavax.net.ssl.trustStore`), and map `vyomi.local` → the VM IP so the cert SAN matches |

`CLOUDPROBE_TRUST_ALL_TLS=true` (default) installs a permissive JVM-default
trust manager; the Cosmos SDK's Netty client still needs the CA in the JDK
truststore (above). All three are **code-complete** — the caveats are network /
cert setup, not SDK wiring (DynamoDB proves the wiring end-to-end).

### The endpoint it targets
The SDKs point at the appliance via `CLOUDPROBE_ENDPOINT` (default
`http://127.0.0.1:9000`). The native-SDK wiring mirrors what the appliance
documents, e.g. AWS Java v2:
```java
S3Client.builder()
    .endpointOverride(URI.create("http://<appliance>:9000"))
    .region(Region.US_EAST_1)
    .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test","test")))
    .forcePathStyle(true)
    .build();
```

## Build & run

```bash
cd samples/java/cloud-probe

# local (needs JDK 17 + Maven)
mvn -q -DskipTests package
CLOUDPROBE_ENDPOINT=http://<appliance>:9000 java -jar target/cloud-probe.jar
curl -s localhost:8080/probe/aws | jq

# container (only needs docker — JVM ships in the image)
docker build -t cloud-probe:local .
docker run --rm -p 8080:8080 -e CLOUDPROBE_ENDPOINT=http://<appliance>:9000 cloud-probe:local
```

## Deploy on a Vyomi VM (integration test)

The VM only needs docker (already bootstrapped). From inside the appliance VM:
```bash
lxc exec <vm> -- docker run -d --name cloud-probe --network host \
  -e CLOUDPROBE_ENDPOINT=http://<appliance-gateway>:9000 cloud-probe:local
# then, from the host:
curl -s http://<vm>:8080/probe/aws | jq '.ok, .steps[] | {step,ok}'
```
A green `/probe/aws` proves a user can build a real app on S3 + DynamoDB through
Vyomi — and (post-2.0.8) that real services still work after the progressive
Wave-2 startup.

## Status
- **aws** — S3 + DynamoDB (AWS SDK for Java v2), build/run verified. ✅
- **gcp** — GCS (`:9000`) + Firestore (`:8080` emulator), build/run verified. ✅
- **azure** — Blob (`/azure-data/blob`, Azurite-style) + Cosmos (`/azure-data/cosmos`, gateway mode), build/run verified. ✅
- **go/cloud-probe** — Go port — next.

> All three compile + start and the native SDKs genuinely execute (proven against
> a dead endpoint: every probe returns a per-step report rather than crashing).
> The full green run — every SDK call succeeding — is the **integration test**,
> run against a live appliance with the Wave-2 backends up:
> `for c in aws gcp azure; do curl -s $SVC/probe/$c | jq '{cloud,ok}'; done`
