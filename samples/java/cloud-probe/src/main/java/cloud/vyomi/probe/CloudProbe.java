package cloud.vyomi.probe;

import java.util.Map;

/** One implementation per cloud. {@link #probe()} runs a full object-store +
 *  NoSQL lifecycle using that cloud's NATIVE SDK and returns a step report. */
public interface CloudProbe {
    /** "aws" | "gcp" | "azure" */
    String cloud();

    /** Run the lifecycle; never throws — failures are captured in the report. */
    Map<String, Object> probe();

    /** Read one object back via the native object-store SDK — used to verify a
     *  file written from the appliance console (UI) is readable by the SDK.
     *  For Azure, {@code bucket} is the container. Never throws. */
    Map<String, Object> getObject(String bucket, String key);

    /** Same, but with an explicit object-store namespace. For Azure this is the
     *  storage account (so a console upload to any account is readable); AWS/GCP
     *  ignore it (the bucket is globally addressed). Blank → cloud default. */
    default Map<String, Object> getObject(String bucket, String key, String account) {
        return getObject(bucket, key);
    }

    // ── NoSQL ────────────────────────────────────────────────────────────────
    // The object-store analog for NoSQL: write a small item with PUT, read it
    // back with GET via the cloud's NATIVE NoSQL SDK. `table` is the
    // DynamoDB table (AWS) / Firestore collection (GCP) / Cosmos container
    // (Azure); `namespace` is the Cosmos database (ignored by AWS/GCP).

    /** Read one item/document by id. Never throws — failures are in the map. */
    default Map<String, Object> getItem(String table, String id, String namespace) {
        return NoSqlResult.error(cloud(), table, id,
                new UnsupportedOperationException("getItem not implemented for " + cloud()));
    }

    /** Write a small test item {id, msg, n} so a GET can read it back. */
    default Map<String, Object> putItem(String table, String id, String namespace) {
        return NoSqlResult.error(cloud(), table, id,
                new UnsupportedOperationException("putItem not implemented for " + cloud()));
    }

    // ── Secrets / KMS ────────────────────────────────────────────────────────
    // Full lifecycle round-trips via the cloud's NATIVE secrets/KMS SDK. Each
    // returns a Report map (same shape as probe()); never throws — failures are
    // captured as steps. Clouds that don't implement a surface report a single
    // "not implemented" step rather than breaking, so a partially-wired build
    // still answers honestly per service.

    /** Secret lifecycle: create → add version → access + verify → delete. */
    default Map<String, Object> probeSecret() {
        Report r = new Report(cloud());
        r.step(cloud() + ".secret", false, "not implemented for " + cloud());
        return r.toMap();
    }

    /** KMS round-trip: ensure key → encrypt → decrypt → verify plaintext. */
    default Map<String, Object> probeKms() {
        Report r = new Report(cloud());
        r.step(cloud() + ".kms", false, "not implemented for " + cloud());
        return r.toMap();
    }

    /** Messaging lifecycle: create queue → send → receive + verify → delete, via
     *  the cloud's NATIVE messaging SDK (SQS / Pub/Sub / Storage Queue). */
    default Map<String, Object> probeQueue() {
        Report r = new Report(cloud());
        r.step(cloud() + ".queue", false, "not implemented for " + cloud());
        return r.toMap();
    }

    /** Compute lifecycle: launch → describe/verify → terminate, via the cloud's
     *  NATIVE compute SDK (EC2 / Compute Engine / Azure VMs). */
    default Map<String, Object> probeCompute() {
        Report r = new Report(cloud());
        r.step(cloud() + ".compute", false, "not implemented for " + cloud());
        return r.toMap();
    }

    /** Managed-DB lifecycle: create → describe/verify → delete, via the cloud's
     *  NATIVE managed-database SDK (RDS / Cloud SQL / Azure SQL). */
    default Map<String, Object> probeDatabase() {
        Report r = new Report(cloud());
        r.step(cloud() + ".database", false, "not implemented for " + cloud());
        return r.toMap();
    }
}
