# CloudLearn — Cloud Simulator Platform
## Full Design & Implementation Context

---

## 1. Vision

**"Flight simulator for cloud learners."**

A platform that mimics AWS, GCP, Azure, and other SaaS cloud services (Redis, Confluent, IBM, etc.) running entirely on a laptop — accessible via `localhost`. Learners get the full console experience and can practice every workflow without a real cloud account or credits.

Key principle: **All the controls, not actually in the air.**
- The UI must be pixel-close to the real AWS/GCP/Azure console (muscle memory for learners)
- Operations work (create bucket, upload, replicate, failover)
- Deep infrastructure concerns don't matter (no real durability, no actual IAM enforcement)
- Focus is learning experience and workflow familiarity

### Why this matters for enterprises
- Onboarding new engineers without cloud spend
- Safe environment to practice destructive operations (delete regions, break IAM, cause outages)
- Compliance training without touching production
- Cost: zero cloud credits consumed during training

### Market fit
- Offered as a **subscription service**
- Target: enterprises onboarding cloud engineers, bootcamps, universities
- Default simulator platform for all SaaS services (AWS, GCP, Azure, IBM, Redis, Confluent, etc.)
- Community-driven: open bundle ecosystem where contributors add new service simulators

---

## 2. Architecture Vision — OSGi Multi-Region Simulator

### Why OSGi

The platform should run on the JVM inside an **OSGi container** (Apache Karaf recommended).
Each cloud service module is a **bundle** — independently installable, startable, stoppable.

```
OSGi Container (JVM)
├── s3-bundle-us-east-1
├── s3-bundle-eu-west-1
├── s3-bundle-ap-southeast-1
├── ec2-bundle-us-east-1
├── rds-bundle-us-east-1
├── iam-bundle              (global, one instance)
├── route53-bundle          (global)
└── simulator-ui-bundle     (React frontend)
```

### AWS → OSGi Concept Mapping

| AWS Concept | OSGi Concept |
|---|---|
| Region (us-east-1) | Bundle + its classloader namespace |
| Region isolation | Bundle classloader isolation |
| AWS global backbone | OSGi Service Registry |
| Cross-region replication | ServiceReference lookup across bundles |
| Region outage | `bundle.stop()` |
| Region recovery | `bundle.start()` |
| Service health event | `ServiceEvent` (REGISTERED / UNREGISTERED) |
| Endpoint URL | Service property (`region=us-east-1`) |
| AWS SDK client | `ServiceTracker` |

### Multi-Region S3 Example

```java
// Each region bundle registers its S3 service
context.registerService(S3Service.class, new S3ServiceImpl("us-east-1"),
    Map.of("region", "us-east-1"));

// Cross-region replication lookup via the registry
ServiceReference<S3Service> ref = context.getServiceReferences(
    S3Service.class, "(region=eu-west-1)").iterator().next();
S3Service target = context.getService(ref);
target.putObject(bucket, key, data);  // replication call
```

### What this unlocks for learners

- **Region outage simulation**: `bundle.stop("eu-west-1")` → ServiceReferences become null → learner's failover logic is tested
- **Eventual consistency**: inject `Thread.sleep(200)` on cross-region calls → learner observes replication lag
- **Realistic latency profiles**: us-east-1 → eu-west-1 ~85ms, us-east-1 → ap-southeast-1 ~230ms
- **Split-brain / partition**: registry selectively refuses to resolve a region → CAP theorem practice in real code
- **Chaos engineering knob**: built-in fault injection layer wrapping service proxies

### Why OSGi beats alternatives

| Approach | Region isolation | Hot deploy | Community bundles |
|---|---|---|---|
| OSGi (Karaf) | Structural (classloader) | Yes | Yes |
| Spring Boot modules | Weak (same classloader) | No | Hard |
| Multiple processes | OS-level | Manual | Hard |
| Docker containers | Full | Overhead | Hard |
| Quarkus / Micronaut | Weak | No | Hard |

OSGi's `ServiceTracker` already behaves like an AWS SDK client — watches for a service to appear, holds a reference while available, releases on bundle stop. This IS the real SDK's endpoint failover behavior, structurally.

---

## 3. Current Implementation (Python POC)

**Status: Working POC. Not OSGi. Python only.**

The Python POC validates the UI/UX and S3 API surface. It is the reference implementation for porting to Java/OSGi.

### Stack

```
Language    Python 3
Server      FastAPI + uvicorn
State       In-memory dicts (no persistence)
UI          Single-file React (React 18, Babel CDN, no build step)
Port        localhost:9000
```

### File Structure

```
s3_simulator/
├── server.py           # FastAPI backend (S3 REST API + JSON API for UI)
├── requirements.txt    # fastapi, uvicorn[standard], python-multipart
└── static/
    └── index.html      # Single-file React UI (AWS Console look-alike)
```

### Running

```bash
cd s3_simulator
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m uvicorn server:app --host 0.0.0.0 --port 9000
```

- **React UI**: http://localhost:9000/ui
- **S3 REST API** (for AWS CLI/boto3): http://localhost:9000
- **JSON API** (for UI): http://localhost:9000/api/s3/*

### Testing with AWS CLI

```bash
# No real credentials needed
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
ENDPOINT=--endpoint-url http://localhost:9000

aws s3 mb s3://my-bucket $ENDPOINT
aws s3 cp file.txt s3://my-bucket/ $ENDPOINT
aws s3 ls s3://my-bucket $ENDPOINT
aws s3 cp s3://my-bucket/file.txt ./downloaded.txt $ENDPOINT
aws s3api put-bucket-versioning --bucket my-bucket \
    --versioning-configuration Status=Enabled $ENDPOINT
aws s3api get-bucket-location --bucket my-bucket $ENDPOINT
aws s3 rm s3://my-bucket/file.txt $ENDPOINT
aws s3 rb s3://my-bucket $ENDPOINT
```

### API Surface (server.py)

#### JSON API (React UI)
| Method | Path | Operation |
|---|---|---|
| GET | /api/s3/buckets | List buckets |
| POST | /api/s3/buckets/{name} | Create bucket |
| GET | /api/s3/buckets/{name} | Get bucket info |
| DELETE | /api/s3/buckets/{name} | Delete bucket |
| GET | /api/s3/buckets/{bucket}/objects | List objects |
| POST | /api/s3/buckets/{bucket}/objects | Upload object (multipart form) |
| GET | /api/s3/buckets/{bucket}/objects/{key}/meta | Object metadata |
| GET | /api/s3/buckets/{bucket}/objects/{key}/download | Download object |
| DELETE | /api/s3/buckets/{bucket}/objects/{key} | Delete object |

#### S3 REST API (AWS CLI / boto3 compatible)
| Method | Path | Operation |
|---|---|---|
| GET | / | ListBuckets |
| PUT | /{bucket} | CreateBucket |
| HEAD | /{bucket} | HeadBucket |
| GET | /{bucket} | ListObjects v1 / v2, GetBucketVersioning, GetBucketLocation, GetBucketTagging, GetBucketAcl, ListMultipartUploads |
| DELETE | /{bucket} | DeleteBucket |
| POST | /{bucket}?delete | DeleteObjects (batch) |
| PUT | /{bucket}/{key} | PutObject, UploadPart, CopyObject, PutObjectTagging, PutObjectAcl |
| GET | /{bucket}/{key} | GetObject (with Range), GetObjectTagging, ListParts |
| HEAD | /{bucket}/{key} | HeadObject |
| DELETE | /{bucket}/{key} | DeleteObject, AbortMultipartUpload, DeleteObjectTagging |
| POST | /{bucket}/{key}?uploads | CreateMultipartUpload |
| POST | /{bucket}/{key}?uploadId=... | CompleteMultipartUpload |

#### Features implemented
- SigV4 signature headers accepted (not validated — flight simulator principle)
- XML responses in exact S3 format
- Bucket versioning (state tracked, toggle works)
- Object/bucket tagging (full get/put/delete)
- User metadata (`x-amz-meta-*` headers)
- Storage class (`x-amz-storage-class`)
- Range requests (HTTP 206 partial content)
- Multipart upload (3-step: create → upload parts → complete)
- CopyObject
- Batch delete
- Proper response headers: `x-amz-request-id`, `x-amz-id-2`, `ETag`, `Last-Modified`

### In-Memory State

```python
buckets: Dict[str, dict] = {}
# { name → { region, created, access, versioning, arn, tags:{} } }

objects: Dict[str, dict] = {}
# { bucket → { key → { data:bytes, size, content_type, last_modified,
#                       etag, storage_class, metadata:{}, tags:{} } } }

multiparts: Dict[str, dict] = {}
# { upload_id → { bucket, key, parts:{part_number → {data,etag}},
#                 content_type, metadata, initiated } }
```

### React UI (static/index.html)

Single self-contained file. No build step. All assets from CDN.

**UI features:**
- Dark header `#232f3e`, orange `#ff9900` accents — AWS Console palette
- Buckets list: Create / Delete / Search
- Objects view: Upload (drag & drop) / Download / Delete / Search
- Tabs: Objects, Properties, Permissions, Metrics
- Modals: CreateBucket, Upload, ConfirmDelete, ObjectDetail
- Toast notifications (auto-dismiss)
- Stats bar: object count + total size
- ARN display, storage class tags, file type icons
- All API calls go to `/api/s3/*`

---

## 4. Full Platform Roadmap

### Phase 1 — Python POC (DONE)
- [x] S3 simulator (Python/FastAPI)
- [x] AWS Console look-alike UI
- [x] AWS CLI / boto3 compatible REST API
- [x] Multipart upload, tagging, versioning, CopyObject, batch delete

### Phase 2 — OSGi Foundation (JVM)
- [ ] Set up Apache Karaf container
- [ ] Define `CloudService` OSGi interface (base for all service simulators)
- [ ] Port S3 logic to Java bundle (`s3-simulator-bundle`)
- [ ] Register with `region` service property
- [ ] Bundle lifecycle = region lifecycle
- [ ] Single React UI consuming services from any region bundle

### Phase 3 — Multi-Region
- [ ] Spin up N S3 bundle instances (one per region)
- [ ] Cross-region replication via ServiceRegistry
- [ ] Latency simulation layer (configurable per region pair)
- [ ] Fault injection (bundle stop = region outage)
- [ ] UI: region selector dropdown (like AWS top-right region picker)

### Phase 4 — More Services
- [ ] IAM bundle (global, one instance, non-enforcing but UI-complete)
- [ ] EC2 bundle (instances in-memory, start/stop/terminate)
- [ ] VPC bundle (subnets, security groups — UI only)
- [ ] RDS bundle (PostgreSQL in-memory via H2)
- [ ] Lambda bundle (execute actual JS/Python code in sandbox)
- [ ] SQS / SNS bundle

### Phase 5 — Guided Learning
- [ ] Lab panel (side drawer with step-by-step exercises)
- [ ] "Lab 1: Create your first S3 bucket and upload a file"
- [ ] Simulated IAM personas (read-only user grays out buttons)
- [ ] "Break It" mode (instructor pre-configures failure scenarios)
- [ ] Progress tracking

### Phase 6 — Community & Subscription
- [ ] Bundle marketplace (community-contributed simulators)
- [ ] Subscription tiers (free: S3+EC2, pro: all services + labs)
- [ ] Org management (instructor creates student environments)

---

## 5. OSGi Implementation Starting Point (Java)

### Recommended Stack
- **Container**: Apache Karaf 4.x (OSGi R7, built-in shell, hot deploy)
- **Language**: Java 17+ or Kotlin
- **Build**: Maven with `maven-bundle-plugin` (BND)
- **HTTP**: Karaf's built-in Jetty + JAX-RS (CXF or Jersey)
- **UI**: Same React single-file app, served from a bundle's `/static`

### S3Service Interface (bundle API)

```java
package com.cloudlearn.simulator.s3.api;

public interface S3Service {
    // Bucket ops
    void createBucket(String name, String region);
    void deleteBucket(String name);
    List<BucketInfo> listBuckets();
    BucketInfo getBucket(String name);

    // Object ops
    void putObject(String bucket, String key, byte[] data, String contentType, Map<String, String> metadata);
    S3Object getObject(String bucket, String key);
    void deleteObject(String bucket, String key);
    List<ObjectInfo> listObjects(String bucket, String prefix, String delimiter);

    // Replication
    void replicateTo(String targetRegion, String bucket, String key);
}
```

### Bundle Activator (one per region)

```java
package com.cloudlearn.simulator.s3.useast1;

@Component(immediate = true, property = {
    "region=us-east-1",
    "endpoint=http://localhost:9001"
})
public class S3BundleActivator implements S3Service {
    // In-memory state scoped to this bundle (= this region)
    private final Map<String, Map<String, S3Object>> store = new ConcurrentHashMap<>();

    // OSGi DS: injected when eu-west-1 bundle is running, null when stopped
    @Reference(target = "(region=eu-west-1)", cardinality = OPTIONAL, policy = DYNAMIC)
    private volatile S3Service euWest1;

    @Override
    public void putObject(String bucket, String key, byte[] data, ...) {
        store.get(bucket).put(key, new S3Object(data, ...));
        // Cross-region replication if configured
        S3Service replica = euWest1;
        if (replica != null) {
            CompletableFuture.runAsync(() -> {
                simulateLatency(85);   // us-east-1 → eu-west-1 latency
                replica.putObject(bucket, key, data, ...);
            });
        }
    }
}
```

### Karaf Commands (region control)

```bash
# Karaf shell — instructor controls
karaf> bundle:stop com.cloudlearn.s3.eu-west-1    # simulate region outage
karaf> bundle:start com.cloudlearn.s3.eu-west-1   # restore region
karaf> service:list com.cloudlearn.simulator.s3.api.S3Service  # see live regions
```

---

## 6. Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Flight simulator principle | No real infrastructure | Learner experience over fidelity |
| State persistence | None (in-memory only) | Simplicity; restart = clean slate |
| Auth | Accept but don't validate SigV4 | SDK compatibility without security overhead |
| UI | Pixel-close to AWS Console | Learner muscle memory |
| Latency simulation | Injected at service proxy layer | Configurable, not hardcoded |
| Region isolation | OSGi bundle classloader | Structural, not simulated with if-statements |
| Community extension | OSGi bundle marketplace | Same model as Eclipse plugins |

---

## 7. Prompt for New Claude Session

Use the following prompt to continue design and implementation in a new session:

> I am building **CloudLearn** — a cloud simulator platform that runs entirely on a laptop (localhost). Think of it as a **flight simulator for cloud learners**: all the AWS/GCP/Azure console controls and workflows, but not actually connected to real infrastructure.
>
> **Current state**: A working Python/FastAPI POC for S3 exists with a React UI that looks like the AWS S3 Console and full AWS CLI/boto3 compatibility via S3 REST XML API. See the attached `CLOUDLEARN_DESIGN.md` for full context.
>
> **Goal**: Design and implement the OSGi-based JVM platform where:
> - Each simulated AWS region = one OSGi bundle
> - OSGi Service Registry = AWS global backbone
> - `bundle.stop()` = region outage simulation
> - Cross-region replication = ServiceReference calls with injected latency
> - Apache Karaf as the OSGi container
> - Same React UI reused, served from the bundle
>
> Start with: Apache Karaf project setup + S3 bundle (port the Python logic) + multi-region wiring.
