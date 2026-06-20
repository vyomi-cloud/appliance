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
}
