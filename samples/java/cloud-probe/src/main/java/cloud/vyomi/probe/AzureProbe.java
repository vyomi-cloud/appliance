package cloud.vyomi.probe;

import com.azure.cosmos.CosmosClient;
import com.azure.cosmos.CosmosClientBuilder;
import com.azure.cosmos.CosmosContainer;
import com.azure.cosmos.CosmosDatabase;
import com.azure.cosmos.models.CosmosQueryRequestOptions;
import com.azure.cosmos.models.PartitionKey;
import com.azure.cosmos.util.CosmosPagedIterable;
import com.azure.storage.blob.BlobClient;
import com.azure.storage.blob.BlobContainerClient;
import com.azure.storage.blob.BlobServiceClient;
import com.azure.storage.blob.BlobServiceClientBuilder;
import com.azure.core.util.BinaryData;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Map;
import java.util.UUID;

/**
 * Azure path — native azure-sdk-for-java. Blob rides the Azurite-compatible
 * surface under /azure-data/blob/{account}; Cosmos uses the sim's subset of the
 * Cosmos SQL REST API under /azure-data/cosmos/{account} (gateway mode). Both
 * use the well-known emulator keys (the sim ignores the signature).
 */
@Component
public class AzureProbe implements CloudProbe {

    private final String blobEndpoint = ProbeEnv.azureBlobEndpoint();
    private final String account = ProbeEnv.azureAccount();
    private final String cosmosEndpoint = ProbeEnv.azureCosmosEndpoint();
    private final String cosmosKey = ProbeEnv.azureCosmosKey();

    @Override public String cloud() { return "azure"; }

    /** Blob service client built from an Azurite-style connection string whose
     *  explicit BlobEndpoint keeps every request on the appliance's Azure blob
     *  handler (never the S3 handler). */
    private BlobServiceClient blobService(String acct) {
        return new BlobServiceClientBuilder()
                .connectionString(ProbeEnv.azureConnectionString(acct))
                .buildClient();
    }

    /** POJO Cosmos item (the SDK serializes via Jackson; needs an `id`). */
    public static class ProbeDoc {
        public String id;
        public String msg;
        public int n;
        public ProbeDoc() {}
        public ProbeDoc(String id, String msg, int n) { this.id = id; this.msg = msg; this.n = n; }
    }

    @Override
    public Map<String, Object> probe() {
        Report r = new Report("azure");
        r.step("blob.endpoint", true, blobEndpoint);
        r.step("cosmos.endpoint", true, cosmosEndpoint);
        blobLifecycle(r);
        cosmosLifecycle(r);
        return r.toMap();
    }

    @Override
    public Map<String, Object> getObject(String container, String blobName) {
        return getObject(container, blobName, account);
    }

    @Override
    public Map<String, Object> getObject(String container, String blobName, String acct) {
        String useAcct = (acct == null || acct.isBlank()) ? account : acct.trim();
        try {
            BlobClient bc = blobService(useAcct).getBlobContainerClient(container).getBlobClient(blobName);
            byte[] bytes = bc.downloadContent().toBytes();
            return ObjectResult.of("azure", container, blobName, bytes, bc.getProperties().getContentType());
        } catch (Exception e) {
            return ObjectResult.error("azure", container, blobName, e);
        }
    }

    // ── Cosmos (NoSQL) read/write via native SDK ────────────────────────────
    // NOTE: the Cosmos Java SDK always uses TLS for the gateway connection, so
    // the endpoint must be HTTPS (the appliance's caddy terminator on :9443) and
    // the cert must be trusted. Configure via CLOUDPROBE_COSMOS_ENDPOINT.
    private CosmosClient cosmosClient() {
        return new CosmosClientBuilder()
                .endpoint(cosmosEndpoint)
                .key(cosmosKey)
                .gatewayMode()
                .buildClient();
    }

    private String cosmosDb(String database) {
        return (database == null || database.isBlank()) ? "probe_db" : database.trim();
    }

    @Override
    public Map<String, Object> getItem(String container, String id, String database) {
        CosmosClient client = null;
        try {
            client = cosmosClient();
            CosmosContainer c = client.getDatabase(cosmosDb(database)).getContainer(container);
            @SuppressWarnings("unchecked")
            Map<String, Object> item = c.readItem(id, new PartitionKey(id), Map.class).getItem();
            return NoSqlResult.of("azure", container, id, new java.util.LinkedHashMap<>(item));
        } catch (Exception e) {
            return NoSqlResult.error("azure", container, id, e);
        } finally {
            if (client != null) try { client.close(); } catch (Exception ignore) {}
        }
    }

    @Override
    public Map<String, Object> putItem(String container, String id, String database) {
        String db = cosmosDb(database);
        CosmosClient client = null;
        try {
            client = cosmosClient();
            client.createDatabaseIfNotExists(db);
            client.getDatabase(db).createContainerIfNotExists(container, "/id");
            java.util.Map<String, Object> doc = new java.util.LinkedHashMap<>();
            doc.put("id", id);
            doc.put("msg", "hello-vyomi");
            doc.put("n", 1);
            client.getDatabase(db).getContainer(container).createItem(doc);
            return getItem(container, id, db);
        } catch (Exception e) {
            return NoSqlResult.error("azure", container, id, e);
        } finally {
            if (client != null) try { client.close(); } catch (Exception ignore) {}
        }
    }

    // ── Blob (object store) ─────────────────────────────────────────────────
    private void blobLifecycle(Report r) {
        String container = "cloud-probe-" + UUID.randomUUID().toString().substring(0, 12);
        String blobName = "probe/obj-" + UUID.randomUUID() + ".bin";
        byte[] payload = ("vyomi-cloud-probe-" + UUID.randomUUID()).getBytes(StandardCharsets.UTF_8);
        BlobContainerClient cc = null;
        BlobClient bc = null;
        boolean createdContainer = false, put = false;
        try {
            BlobServiceClient svc = blobService(account);
            cc = svc.getBlobContainerClient(container);
            cc.create();
            createdContainer = true;
            r.step("blob.createContainer", true, container);

            bc = cc.getBlobClient(blobName);
            bc.upload(BinaryData.fromBytes(payload), true);
            put = true;
            r.step("blob.upload", true, blobName + " (" + payload.length + "B)");

            byte[] back = bc.downloadContent().toBytes();
            boolean match = Arrays.equals(payload, back);
            r.step("blob.download+verify", match, match ? "bytes match" : "BYTE MISMATCH");

            long size = bc.getProperties().getBlobSize();
            r.step("blob.getProperties", size == payload.length, "size=" + size);

            long n = cc.listBlobs().stream().filter(b -> b.getName().equals(blobName)).count();
            r.step("blob.listBlobs", n == 1, "matched=" + n);
        } catch (Exception e) {
            r.step("blob.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (put && bc != null) try { bc.delete(); r.step("blob.delete", true, "cleaned up"); }
                catch (Exception e) { r.step("blob.delete", false, e.getMessage()); }
            if (createdContainer && cc != null) try { cc.delete(); r.step("blob.deleteContainer", true, "cleaned up"); }
                catch (Exception e) { r.step("blob.deleteContainer", false, e.getMessage()); }
        }
    }

    // ── Cosmos (NoSQL) ──────────────────────────────────────────────────────
    private void cosmosLifecycle(Report r) {
        String dbName = "probe_db_" + UUID.randomUUID().toString().substring(0, 8);
        String containerName = "probe_c_" + UUID.randomUUID().toString().substring(0, 8);
        String id = "item-" + UUID.randomUUID();
        CosmosClient client = null;
        boolean createdDb = false;
        try {
            client = new CosmosClientBuilder()
                    .endpoint(cosmosEndpoint)
                    .key(cosmosKey)
                    .gatewayMode()   // HTTP gateway — right mode for the sim
                    .buildClient();

            client.createDatabaseIfNotExists(dbName);
            createdDb = true;
            r.step("cosmos.createDatabase", true, dbName);

            CosmosDatabase db = client.getDatabase(dbName);
            db.createContainerIfNotExists(containerName, "/id");
            r.step("cosmos.createContainer", true, containerName);

            CosmosContainer c = db.getContainer(containerName);
            c.createItem(new ProbeDoc(id, "hello-vyomi", 1));
            r.step("cosmos.createItem", true, id);

            ProbeDoc read = c.readItem(id, new PartitionKey(id), ProbeDoc.class).getItem();
            boolean match = read != null && "hello-vyomi".equals(read.msg);
            r.step("cosmos.readItem+verify", match, match ? "msg matches" : "MISMATCH/absent");

            CosmosPagedIterable<ProbeDoc> q = c.queryItems(
                    "SELECT * FROM c WHERE c.msg = 'hello-vyomi'",
                    new CosmosQueryRequestOptions(), ProbeDoc.class);
            long count = q.stream().count();
            r.step("cosmos.queryItems", count >= 1, "matched=" + count);

            c.deleteItem(id, new PartitionKey(id), null);
            r.step("cosmos.deleteItem", true, "cleaned up");
        } catch (Exception e) {
            r.step("cosmos.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (createdDb && client != null) try { client.getDatabase(dbName).delete();
                    r.step("cosmos.deleteDatabase", true, "cleaned up"); }
                catch (Exception e) { r.step("cosmos.deleteDatabase", false, e.getMessage()); }
            if (client != null) try { client.close(); } catch (Exception ignore) {}
        }
    }
}
