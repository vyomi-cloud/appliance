import com.google.cloud.NoCredentials;
import com.google.cloud.storage.Blob;
import com.google.cloud.storage.BlobId;
import com.google.cloud.storage.BlobInfo;
import com.google.cloud.storage.Bucket;
import com.google.cloud.storage.BucketInfo;
import com.google.cloud.storage.Storage;
import com.google.cloud.storage.StorageOptions;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/**
 * Real google-cloud-storage (Java) conformance probe against the CloudLearn
 * simulator. Proves whether an UNMODIFIED Google client library works when
 * pointed at the simulator endpoint (REST + fake-gcs-server backend).
 *
 * Endpoint + project come from env: ENDPOINT (default http://127.0.0.1:9000),
 * PROJECT (default vyomi-project).
 */
public class StorageConformance {
  static int pass = 0, fail = 0;

  static void check(String name, boolean ok, String detail) {
    System.out.println((ok ? "PASS " : "FAIL ") + name + (detail == null || detail.isEmpty() ? "" : " :: " + detail));
    if (ok) pass++; else fail++;
  }

  public static void main(String[] args) {
    String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
    String project = System.getenv().getOrDefault("PROJECT", "vyomi-project");
    System.out.println("== google-cloud-storage (Java) against " + endpoint + " project=" + project + " ==");

    Storage storage = StorageOptions.newBuilder()
        .setHost(endpoint)
        .setProjectId(project)
        .setCredentials(NoCredentials.getInstance())
        .build()
        .getService();

    String bucket = "java-sdk-test-" + System.currentTimeMillis();
    byte[] data = "hello-from-java-sdk".getBytes(StandardCharsets.UTF_8);
    BlobId blobId = BlobId.of(bucket, "greeting.txt");

    try {
      Bucket b = storage.create(BucketInfo.of(bucket));
      check("buckets.insert", b != null && bucket.equals(b.getName()), b == null ? "null" : b.getName());
    } catch (Exception e) { check("buckets.insert", false, e.toString()); }

    try {
      boolean found = false;
      for (Bucket b : storage.list().iterateAll()) { if (bucket.equals(b.getName())) { found = true; break; } }
      check("buckets.list contains new bucket", found, null);
    } catch (Exception e) { check("buckets.list", false, e.toString()); }

    try {
      Blob blob = storage.create(BlobInfo.newBuilder(blobId).setContentType("text/plain").build(), data);
      check("objects.insert (upload)", blob != null, blob == null ? "null" : blob.getName());
    } catch (Exception e) { check("objects.insert", false, e.toString()); }

    try {
      byte[] got = storage.readAllBytes(blobId);
      check("objects.get (download byte-exact)", Arrays.equals(got, data),
          got == null ? "null" : new String(got, StandardCharsets.UTF_8));
    } catch (Exception e) { check("objects.get", false, e.toString()); }

    try {
      boolean delObj = storage.delete(blobId);
      check("objects.delete", delObj, String.valueOf(delObj));
    } catch (Exception e) { check("objects.delete", false, e.toString()); }

    try {
      boolean delBucket = storage.delete(bucket);
      check("buckets.delete", delBucket, String.valueOf(delBucket));
    } catch (Exception e) { check("buckets.delete", false, e.toString()); }

    System.out.println("RESULT pass=" + pass + " fail=" + fail);
    if (fail > 0) System.exit(1);
  }
}
