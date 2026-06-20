package cloud.vyomi.probe;

import com.google.api.gax.paging.Page;
import com.google.cloud.NoCredentials;
import com.google.cloud.firestore.DocumentReference;
import com.google.cloud.firestore.DocumentSnapshot;
import com.google.cloud.firestore.Firestore;
import com.google.cloud.firestore.FirestoreOptions;
import com.google.cloud.firestore.QuerySnapshot;
import com.google.cloud.storage.Blob;
import com.google.cloud.storage.BlobId;
import com.google.cloud.storage.BlobInfo;
import com.google.cloud.storage.Bucket;
import com.google.cloud.storage.BucketInfo;
import com.google.cloud.storage.Storage;
import com.google.cloud.storage.StorageOptions;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * GCP path — native google-cloud-java SDKs. GCS rides the simulator (:9000 via
 * {@code setHost}); Firestore is the native gRPC emulator (:8080 via
 * {@code setEmulatorHost}). Both use NoCredentials, like the appliance docs.
 */
@Component
public class GcpProbe implements CloudProbe {

    private final String gcsHost = ProbeEnv.gcsHost();
    private final String firestoreHost = ProbeEnv.firestoreEmulatorHost();
    private final String project = ProbeEnv.gcpProject();

    @Override public String cloud() { return "gcp"; }

    private Storage storage() {
        return StorageOptions.newBuilder()
                .setHost(gcsHost)
                .setProjectId(project)
                .setCredentials(NoCredentials.getInstance())
                .build()
                .getService();
    }

    private Firestore firestore() {
        return FirestoreOptions.newBuilder()
                .setProjectId(project)
                .setEmulatorHost(firestoreHost)
                .setCredentials(NoCredentials.getInstance())
                .build()
                .getService();
    }

    @Override
    public Map<String, Object> probe() {
        Report r = new Report("gcp");
        r.step("gcs.host", true, gcsHost);
        r.step("firestore.emulatorHost", true, firestoreHost);
        gcsLifecycle(r);
        firestoreLifecycle(r);
        return r.toMap();
    }

    // ── GCS (object store) ──────────────────────────────────────────────────
    private void gcsLifecycle(Report r) {
        String bucket = "cloud-probe-" + UUID.randomUUID().toString().substring(0, 12);
        String objname = "probe/obj-" + UUID.randomUUID() + ".bin";
        byte[] payload = ("vyomi-cloud-probe-" + UUID.randomUUID()).getBytes(StandardCharsets.UTF_8);
        Storage storage = null;
        boolean created = false, put = false;
        BlobId blobId = BlobId.of(bucket, objname);
        try {
            storage = storage();
            Bucket b = storage.create(BucketInfo.of(bucket));
            created = true;
            r.step("gcs.createBucket", true, b.getName());

            BlobInfo info = BlobInfo.newBuilder(blobId).setContentType("application/octet-stream").build();
            storage.create(info, payload);
            put = true;
            r.step("gcs.create(blob)", true, objname + " (" + payload.length + "B)");

            byte[] back = storage.readAllBytes(blobId);
            boolean match = Arrays.equals(payload, back);
            r.step("gcs.readAllBytes+verify", match, match ? "bytes match" : "BYTE MISMATCH");

            Blob got = storage.get(blobId);
            r.step("gcs.get(metadata)", got != null && got.getSize() == payload.length,
                    "size=" + (got == null ? "null" : got.getSize()));

            Page<Blob> page = storage.list(bucket, Storage.BlobListOption.prefix("probe/"));
            boolean found = false; int n = 0;
            for (Blob bl : page.iterateAll()) { n++; if (bl.getName().equals(objname)) found = true; }
            r.step("gcs.list", found, "blobs=" + n);
        } catch (Exception e) {
            r.step("gcs.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (storage != null) {
                if (put) try { storage.delete(blobId); r.step("gcs.delete(blob)", true, "cleaned up"); }
                    catch (Exception e) { r.step("gcs.delete(blob)", false, e.getMessage()); }
                if (created) try { storage.delete(bucket); r.step("gcs.delete(bucket)", true, "cleaned up"); }
                    catch (Exception e) { r.step("gcs.delete(bucket)", false, e.getMessage()); }
                try { storage.close(); } catch (Exception ignore) {}
            }
        }
    }

    // ── Firestore (NoSQL) ───────────────────────────────────────────────────
    private void firestoreLifecycle(Report r) {
        String collection = "cloud_probe_" + UUID.randomUUID().toString().substring(0, 8);
        String id = "doc-" + UUID.randomUUID();
        Firestore db = null;
        DocumentReference doc = null;
        boolean wrote = false;
        try {
            db = firestore();
            doc = db.collection(collection).document(id);

            Map<String, Object> data = new LinkedHashMap<>();
            data.put("msg", "hello-vyomi");
            data.put("n", 1);
            doc.set(data).get();
            wrote = true;
            r.step("firestore.set", true, collection + "/" + id);

            DocumentSnapshot snap = doc.get().get();
            boolean match = snap.exists() && "hello-vyomi".equals(snap.getString("msg"));
            r.step("firestore.get+verify", match, match ? "msg matches" : "MISMATCH/absent");

            doc.update("n", 2).get();
            DocumentSnapshot after = doc.get().get();
            r.step("firestore.update", after.getLong("n") != null && after.getLong("n") == 2L,
                    "n=" + after.getLong("n"));

            QuerySnapshot q = db.collection(collection).whereEqualTo("msg", "hello-vyomi").get().get();
            r.step("firestore.query", q.size() == 1, "matched=" + q.size());
        } catch (Exception e) {
            r.step("firestore.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (doc != null && wrote) try { doc.delete().get(); r.step("firestore.delete", true, "cleaned up"); }
                catch (Exception e) { r.step("firestore.delete", false, e.getMessage()); }
            if (db != null) try { db.close(); } catch (Exception ignore) {}
        }
    }
}
