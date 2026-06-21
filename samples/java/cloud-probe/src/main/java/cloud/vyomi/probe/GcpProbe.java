package cloud.vyomi.probe;

import com.google.api.gax.core.NoCredentialsProvider;
import com.google.api.gax.grpc.InstantiatingGrpcChannelProvider;
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
import com.google.cloud.kms.v1.CryptoKey;
import com.google.cloud.kms.v1.CryptoKeyName;
import com.google.cloud.kms.v1.DecryptResponse;
import com.google.cloud.kms.v1.EncryptResponse;
import com.google.cloud.kms.v1.KeyManagementServiceClient;
import com.google.cloud.kms.v1.KeyManagementServiceSettings;
import com.google.cloud.kms.v1.KeyRing;
import com.google.cloud.kms.v1.KeyRingName;
import com.google.cloud.kms.v1.LocationName;
import com.google.cloud.secretmanager.v1.AccessSecretVersionResponse;
import com.google.cloud.secretmanager.v1.ProjectName;
import com.google.cloud.secretmanager.v1.Replication;
import com.google.cloud.secretmanager.v1.Secret;
import com.google.cloud.secretmanager.v1.SecretManagerServiceClient;
import com.google.cloud.secretmanager.v1.SecretManagerServiceSettings;
import com.google.cloud.secretmanager.v1.SecretName;
import com.google.cloud.secretmanager.v1.SecretPayload;
import com.google.cloud.secretmanager.v1.SecretVersion;
import com.google.protobuf.ByteString;
import com.google.api.gax.grpc.GrpcTransportChannel;
import com.google.api.gax.rpc.FixedTransportChannelProvider;
import com.google.api.gax.rpc.TransportChannelProvider;
import com.google.cloud.pubsub.v1.Publisher;
import com.google.cloud.pubsub.v1.SubscriptionAdminClient;
import com.google.cloud.pubsub.v1.SubscriptionAdminSettings;
import com.google.cloud.pubsub.v1.TopicAdminClient;
import com.google.cloud.pubsub.v1.TopicAdminSettings;
import com.google.cloud.pubsub.v1.stub.GrpcSubscriberStub;
import com.google.cloud.pubsub.v1.stub.SubscriberStub;
import com.google.cloud.pubsub.v1.stub.SubscriberStubSettings;
import com.google.pubsub.v1.AcknowledgeRequest;
import com.google.pubsub.v1.ProjectSubscriptionName;
import com.google.pubsub.v1.PubsubMessage;
import com.google.pubsub.v1.PullRequest;
import com.google.pubsub.v1.PullResponse;
import com.google.pubsub.v1.PushConfig;
import com.google.pubsub.v1.ReceivedMessage;
import com.google.pubsub.v1.TopicName;
import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;
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
    private final String restEndpoint = ProbeEnv.gcpRestEndpoint();   // https host:port (caddy)
    private final String location = ProbeEnv.gcpLocation();

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
        // setEmulatorHost() alone flips the channel to plaintext but leaves the
        // ENDPOINT pointed at production firestore.googleapis.com:443 (verified
        // by packet capture: the SDK fired a plaintext h2c preface at :443 and
        // got a TLS alert -> "First received frame was not SETTINGS 1503010002").
        // Pin the endpoint AND plaintext explicitly via the channel provider so
        // every RPC actually lands on the emulator.
        InstantiatingGrpcChannelProvider channel = InstantiatingGrpcChannelProvider.newBuilder()
                .setEndpoint(firestoreHost)
                .setChannelConfigurator(b -> b.usePlaintext())
                .build();
        return FirestoreOptions.newBuilder()
                .setProjectId(project)
                .setEmulatorHost(firestoreHost)
                .setHost(firestoreHost)
                .setChannelProvider(channel)
                .setCredentials(NoCredentials.getInstance())
                .setCredentialsProvider(NoCredentialsProvider.create())
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

    @Override
    public Map<String, Object> getObject(String bucket, String key) {
        Storage storage = null;
        try {
            storage = storage();
            Blob blob = storage.get(BlobId.of(bucket, key));
            if (blob == null || !blob.exists()) throw new RuntimeException("object not found");
            return ObjectResult.of("gcp", bucket, key, blob.getContent(), blob.getContentType());
        } catch (Exception e) {
            return ObjectResult.error("gcp", bucket, key, e);
        } finally {
            if (storage != null) try { storage.close(); } catch (Exception ignore) {}
        }
    }

    // ── Firestore (NoSQL) read/write via native SDK ─────────────────────────
    @Override
    public Map<String, Object> getItem(String collection, String id, String namespace) {
        Firestore db = null;
        try {
            db = firestore();
            DocumentSnapshot snap = db.collection(collection).document(id).get().get();
            if (!snap.exists())
                return NoSqlResult.error("gcp", collection, id, new RuntimeException("document not found"));
            return NoSqlResult.of("gcp", collection, id, new LinkedHashMap<>(snap.getData()));
        } catch (Exception e) {
            return NoSqlResult.error("gcp", collection, id, e);
        } finally {
            if (db != null) try { db.close(); } catch (Exception ignore) {}
        }
    }

    @Override
    public Map<String, Object> putItem(String collection, String id, String namespace) {
        Firestore db = null;
        try {
            db = firestore();
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("msg", "hello-vyomi");
            data.put("n", 1);
            db.collection(collection).document(id).set(data).get();
            DocumentSnapshot snap = db.collection(collection).document(id).get().get();
            return NoSqlResult.of("gcp", collection, id, new LinkedHashMap<>(snap.getData()));
        } catch (Exception e) {
            return NoSqlResult.error("gcp", collection, id, e);
        } finally {
            if (db != null) try { db.close(); } catch (Exception ignore) {}
        }
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

    // ── Secret Manager (native SDK over the HttpJson/REST transport) ─────────
    // GCP ships NO emulator for Secret Manager or KMS (unlike Pub/Sub/Firestore),
    // and the default transport is gRPC to *.googleapis.com. We use the SDK's OWN
    // REST transport (newHttpJsonBuilder) pointed at the appliance — still the
    // native SDK, configured the way the SDK supports (like AWS endpointOverride).
    // gax builds HTTPS URLs, so restEndpoint is the caddy host:port, and the
    // caddy cert must be trusted by the JVM (same as the Cosmos probe).
    private SecretManagerServiceClient secretClient() throws Exception {
        SecretManagerServiceSettings settings = SecretManagerServiceSettings.newHttpJsonBuilder()
                .setEndpoint(restEndpoint)
                .setCredentialsProvider(NoCredentialsProvider.create())
                .build();
        return SecretManagerServiceClient.create(settings);
    }

    @Override
    public Map<String, Object> probeSecret() {
        Report r = new Report("gcp");
        r.step("secretmanager.transport", true, "HttpJson(REST) -> " + restEndpoint);
        String secretId = "cloud-probe-" + UUID.randomUUID().toString().substring(0, 12);
        SecretManagerServiceClient client = null;
        boolean created = false;
        try {
            client = secretClient();
            client.createSecret(ProjectName.of(project), secretId,
                    Secret.newBuilder().setReplication(Replication.newBuilder()
                            .setAutomatic(Replication.Automatic.newBuilder().build()).build()).build());
            created = true;
            r.step("secretmanager.createSecret", true, secretId);

            SecretVersion version = client.addSecretVersion(SecretName.of(project, secretId),
                    SecretPayload.newBuilder().setData(ByteString.copyFromUtf8("hello-vyomi")).build());
            r.step("secretmanager.addSecretVersion", true, version.getName());

            AccessSecretVersionResponse resp = client.accessSecretVersion(version.getName());
            String value = resp.getPayload().getData().toStringUtf8();
            r.step("secretmanager.accessSecretVersion+verify", "hello-vyomi".equals(value),
                    "value=" + value);
        } catch (Exception e) {
            r.step("secretmanager.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (client != null) {
                if (created) try { client.deleteSecret(SecretName.of(project, secretId));
                        r.step("secretmanager.deleteSecret", true, "cleaned up"); }
                    catch (Exception e) { r.step("secretmanager.deleteSecret", false, e.getMessage()); }
                try { client.close(); } catch (Exception ignore) {}
            }
        }
        return r.toMap();
    }

    // ── Cloud KMS (native SDK over the HttpJson/REST transport) ──────────────
    private KeyManagementServiceClient kmsClient() throws Exception {
        KeyManagementServiceSettings settings = KeyManagementServiceSettings.newHttpJsonBuilder()
                .setEndpoint(restEndpoint)
                .setCredentialsProvider(NoCredentialsProvider.create())
                .build();
        return KeyManagementServiceClient.create(settings);
    }

    @Override
    public Map<String, Object> probeKms() {
        Report r = new Report("gcp");
        r.step("kms.transport", true, "HttpJson(REST) -> " + restEndpoint);
        r.step("kms.location", true, location);
        String ringId = "cloud-probe-" + UUID.randomUUID().toString().substring(0, 8);
        String keyId = "key-" + UUID.randomUUID().toString().substring(0, 8);
        KeyManagementServiceClient client = null;
        try {
            client = kmsClient();
            LocationName loc = LocationName.of(project, location);
            // Key-ring / crypto-key creation is best-effort: the appliance's
            // Vault-transit backing may auto-provision on first encrypt, so we
            // record these steps but still attempt the encrypt/decrypt round-trip
            // (the real conformance assertion) regardless of their outcome.
            try {
                client.createKeyRing(loc, ringId, KeyRing.newBuilder().build());
                r.step("kms.createKeyRing", true, ringId);
            } catch (Exception e) {
                r.step("kms.createKeyRing", false, e.getClass().getSimpleName() + ": " + e.getMessage());
            }
            try {
                client.createCryptoKey(KeyRingName.of(project, location, ringId), keyId,
                        CryptoKey.newBuilder()
                                .setPurpose(CryptoKey.CryptoKeyPurpose.ENCRYPT_DECRYPT).build());
                r.step("kms.createCryptoKey", true, keyId);
            } catch (Exception e) {
                r.step("kms.createCryptoKey", false, e.getClass().getSimpleName() + ": " + e.getMessage());
            }

            CryptoKeyName keyName = CryptoKeyName.of(project, location, ringId, keyId);
            ByteString plaintext = ByteString.copyFromUtf8("hello-vyomi");
            EncryptResponse enc = client.encrypt(keyName.toString(), plaintext);
            r.step("kms.encrypt", !enc.getCiphertext().isEmpty(),
                    "ciphertext=" + enc.getCiphertext().size() + "B");

            DecryptResponse dec = client.decrypt(keyName.toString(), enc.getCiphertext());
            boolean match = plaintext.equals(dec.getPlaintext());
            r.step("kms.decrypt+verify", match, match ? "plaintext round-trips" : "MISMATCH");
        } catch (Exception e) {
            r.step("kms.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            // GCP KMS key rings / keys are not deletable (only key *versions* are
            // destroyed) — nothing to clean up, matching real Cloud KMS.
            if (client != null) try { client.close(); } catch (Exception ignore) {}
        }
        return r.toMap();
    }

    // ── Pub/Sub (messaging) — native SDK against the gRPC emulator ───────────
    // Like Firestore: a plaintext gRPC channel pinned at the emulator host, with
    // NoCredentials. create topic + subscription → publish → synchronous pull →
    // verify → ack → clean up.
    @Override
    public Map<String, Object> probeQueue() {
        Report r = new Report("gcp");
        String host = ProbeEnv.pubsubEmulatorHost();
        r.step("pubsub.emulatorHost", true, host);
        String topicId = "cloud-probe-" + UUID.randomUUID().toString().substring(0, 8);
        String subId = "cloud-probe-sub-" + UUID.randomUUID().toString().substring(0, 8);
        TopicName topicName = TopicName.of(project, topicId);
        ProjectSubscriptionName subName = ProjectSubscriptionName.of(project, subId);

        ManagedChannel channel = ManagedChannelBuilder.forTarget(host).usePlaintext().build();
        TransportChannelProvider channelProvider =
                FixedTransportChannelProvider.create(GrpcTransportChannel.create(channel));
        TopicAdminClient topicAdmin = null;
        SubscriptionAdminClient subAdmin = null;
        Publisher publisher = null;
        boolean topicCreated = false, subCreated = false;
        try {
            topicAdmin = TopicAdminClient.create(TopicAdminSettings.newBuilder()
                    .setTransportChannelProvider(channelProvider)
                    .setCredentialsProvider(NoCredentialsProvider.create()).build());
            topicAdmin.createTopic(topicName);
            topicCreated = true;
            r.step("pubsub.createTopic", true, topicName.toString());

            subAdmin = SubscriptionAdminClient.create(SubscriptionAdminSettings.newBuilder()
                    .setTransportChannelProvider(channelProvider)
                    .setCredentialsProvider(NoCredentialsProvider.create()).build());
            subAdmin.createSubscription(subName.toString(), topicName, PushConfig.getDefaultInstance(), 10);
            subCreated = true;
            r.step("pubsub.createSubscription", true, subName.toString());

            String body = "hello-vyomi-" + UUID.randomUUID();
            publisher = Publisher.newBuilder(topicName)
                    .setChannelProvider(channelProvider)
                    .setCredentialsProvider(NoCredentialsProvider.create()).build();
            String msgId = publisher.publish(PubsubMessage.newBuilder()
                    .setData(ByteString.copyFromUtf8(body)).build()).get();
            r.step("pubsub.publish", true, "messageId=" + msgId);

            try (SubscriberStub subscriber = GrpcSubscriberStub.create(SubscriberStubSettings.newBuilder()
                    .setTransportChannelProvider(channelProvider)
                    .setCredentialsProvider(NoCredentialsProvider.create()).build())) {
                String received = null, ackId = null;
                for (int i = 0; i < 5 && received == null; i++) {
                    PullResponse resp = subscriber.pullCallable().call(PullRequest.newBuilder()
                            .setSubscription(subName.toString()).setMaxMessages(1).build());
                    if (!resp.getReceivedMessagesList().isEmpty()) {
                        ReceivedMessage rm = resp.getReceivedMessages(0);
                        received = rm.getMessage().getData().toStringUtf8();
                        ackId = rm.getAckId();
                    } else {
                        try { Thread.sleep(300); } catch (InterruptedException ignore) {}
                    }
                }
                boolean match = body.equals(received);
                r.step("pubsub.pull+verify", match, match ? "body matches" : "MISMATCH/empty");
                if (ackId != null) {
                    subscriber.acknowledgeCallable().call(AcknowledgeRequest.newBuilder()
                            .setSubscription(subName.toString()).addAckIds(ackId).build());
                    r.step("pubsub.acknowledge", true, "acked");
                }
            }
        } catch (Exception e) {
            r.step("pubsub.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (publisher != null) try { publisher.shutdown(); } catch (Exception ignore) {}
            if (subCreated && subAdmin != null) try { subAdmin.deleteSubscription(subName.toString());
                    r.step("pubsub.deleteSubscription", true, "cleaned up"); }
                catch (Exception e) { r.step("pubsub.deleteSubscription", false, e.getMessage()); }
            if (topicCreated && topicAdmin != null) try { topicAdmin.deleteTopic(topicName);
                    r.step("pubsub.deleteTopic", true, "cleaned up"); }
                catch (Exception e) { r.step("pubsub.deleteTopic", false, e.getMessage()); }
            if (subAdmin != null) try { subAdmin.close(); } catch (Exception ignore) {}
            if (topicAdmin != null) try { topicAdmin.close(); } catch (Exception ignore) {}
            channel.shutdown();
        }
        return r.toMap();
    }
}
