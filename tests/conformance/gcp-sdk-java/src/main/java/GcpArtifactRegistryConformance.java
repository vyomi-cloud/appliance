import com.google.api.gax.core.NoCredentialsProvider;
import com.google.devtools.artifactregistry.v1.ArtifactRegistryClient;
import com.google.devtools.artifactregistry.v1.ArtifactRegistrySettings;
import com.google.devtools.artifactregistry.v1.CreateRepositoryRequest;
import com.google.devtools.artifactregistry.v1.CreateTagRequest;
import com.google.devtools.artifactregistry.v1.DeleteRepositoryRequest;
import com.google.devtools.artifactregistry.v1.DockerImage;
import com.google.devtools.artifactregistry.v1.ListDockerImagesRequest;
import com.google.devtools.artifactregistry.v1.ListPackagesRequest;
import com.google.devtools.artifactregistry.v1.ListRepositoriesRequest;
import com.google.devtools.artifactregistry.v1.ListTagsRequest;
import com.google.devtools.artifactregistry.v1.ListVersionsRequest;
import com.google.devtools.artifactregistry.v1.LocationName;
import com.google.devtools.artifactregistry.v1.Repository;
import com.google.devtools.artifactregistry.v1.RepositoryName;
import com.google.devtools.artifactregistry.v1.Tag;
import com.google.devtools.artifactregistry.v1.UpdateRepositoryRequest;
import com.google.iam.v1.Binding;
import com.google.iam.v1.Policy;
import com.google.iam.v1.SetIamPolicyRequest;
import com.google.protobuf.FieldMask;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

/**
 * Real google-cloud-artifact-registry (Java, HTTP/JSON transport) conformance against Vyomi's
 * Artifact Registry. Only the endpoint is changed (ENDPOINT, default http://127.0.0.1:9000).
 * One [PASS]/[FAIL] line per check; exits non-zero on failure.
 *
 *   ENDPOINT=http://localhost:9000 mvn -q -B compile exec:java -Dexec.mainClass=GcpArtifactRegistryConformance
 */
public class GcpArtifactRegistryConformance {
  static int fails = 0;

  static void check(String name, boolean ok, String detail) {
    System.out.println("[" + (ok ? "PASS" : "FAIL") + "] " + name + (!ok && detail != null && !detail.isEmpty() ? " :: " + detail : ""));
    if (!ok) fails++;
  }

  public static void main(String[] args) throws Exception {
    String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
    String project = System.getenv().getOrDefault("PROJECT", "vyomi-project");
    String id = "java-ar-" + (System.currentTimeMillis() % 1000000000L);
    LocationName parent = LocationName.of(project, "us-central1");
    String name = RepositoryName.of(project, "us-central1", id).toString();

    ArtifactRegistrySettings settings = ArtifactRegistrySettings.newHttpJsonBuilder()
        .setEndpoint(endpoint)
        .setCredentialsProvider(NoCredentialsProvider.create())
        .build();
    try (ArtifactRegistryClient c = ArtifactRegistryClient.create(settings)) {
      try {
        Repository created = c.createRepositoryAsync(CreateRepositoryRequest.newBuilder()
            .setParent(parent.toString()).setRepositoryId(id)
            .setRepository(Repository.newBuilder().setFormat(Repository.Format.DOCKER).setDescription("java sdk")
                .putLabels("team", "sdk")).build()).get();
        check("CreateRepository completes with the repository", name.equals(created.getName()), created.getName());
      } catch (Exception e) { check("CreateRepository completes with the repository", false, e.toString()); return; }

      try {
        c.createRepositoryAsync(CreateRepositoryRequest.newBuilder().setParent(parent.toString()).setRepositoryId(id)
            .setRepository(Repository.newBuilder().setFormat(Repository.Format.DOCKER)).build()).get();
        check("duplicate CreateRepository fails with ALREADY_EXISTS", false, "no error");
      } catch (Exception e) {
        check("duplicate CreateRepository fails with ALREADY_EXISTS", e.toString().contains("AlreadyExists") || e.toString().contains("ALREADY_EXISTS") || e.toString().contains("Aborted") || e.toString().contains("Conflict") || e.toString().contains("409"), e.toString());
      }

      try {
        Repository r = c.getRepository(name);
        check("GetRepository returns format, description and labels",
            r.getFormat() == Repository.Format.DOCKER && r.getDescription().equals("java sdk") && "sdk".equals(r.getLabelsMap().get("team")), r.toString());
      } catch (Exception e) { check("GetRepository returns format, description and labels", false, e.toString()); }

      try {
        boolean found = false;
        for (Repository r : c.listRepositories(ListRepositoriesRequest.newBuilder().setParent(parent.toString()).build()).iterateAll())
          if (r.getName().equals(name)) found = true;
        check("ListRepositories contains the repository", found, "");
      } catch (Exception e) { check("ListRepositories contains the repository", false, e.toString()); }

      try {
        Repository u = c.updateRepository(UpdateRepositoryRequest.newBuilder()
            .setRepository(Repository.newBuilder().setName(name).setDescription("updated"))
            .setUpdateMask(FieldMask.newBuilder().addPaths("description")).build());
        check("UpdateRepository changes the description", "updated".equals(u.getDescription()), u.getDescription());
      } catch (Exception e) { check("UpdateRepository changes the description", false, e.toString()); }

      try {
        c.setIamPolicy(SetIamPolicyRequest.newBuilder().setResource(name).setPolicy(Policy.newBuilder()
            .addBindings(Binding.newBuilder().setRole("roles/artifactregistry.reader").addMembers("allUsers"))).build());
        Policy p = c.getIamPolicy(com.google.iam.v1.GetIamPolicyRequest.newBuilder().setResource(name).build());
        check("Set/GetIamPolicy round-trips the binding", p.getBindingsCount() == 1 && p.getBindings(0).getMembers(0).equals("allUsers"), p.toString());
      } catch (Exception e) { check("Set/GetIamPolicy round-trips the binding", false, e.toString()); }

      try {
        HttpResponse<String> resp = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build().send(HttpRequest.newBuilder(
            URI.create(endpoint + "/api/gcp/sub/artifactregistry/pushSample/" + id))
            .header("content-type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString("{\"image\":\"app\",\"tag\":\"v1\"}")).build(), HttpResponse.BodyHandlers.ofString());
        check("push a sample image through the data-plane hook", resp.statusCode() == 200, resp.body());
        DockerImage img = c.listDockerImages(ListDockerImagesRequest.newBuilder().setParent(name).build()).iterateAll().iterator().next();
        check("ListDockerImages returns the pushed image with its tag", img.getTagsCount() == 1 && img.getTags(0).equals("v1") && img.getUri().contains(id + "/app@sha256:"), img.toString());
        com.google.devtools.artifactregistry.v1.Package pkg = c.listPackages(ListPackagesRequest.newBuilder().setParent(name).build()).iterateAll().iterator().next();
        check("ListPackages returns the image package", pkg.getName().endsWith("/packages/app"), pkg.getName());
        com.google.devtools.artifactregistry.v1.Version ver = c.listVersions(ListVersionsRequest.newBuilder().setParent(pkg.getName()).build()).iterateAll().iterator().next();
        Tag t = c.createTag(CreateTagRequest.newBuilder().setParent(pkg.getName()).setTagId("stable")
            .setTag(Tag.newBuilder().setVersion(ver.getName())).build());
        check("CreateTag points a new tag at the version", t.getName().endsWith("/tags/stable"), t.getName());
        int n = 0;
        for (Tag ignored : c.listTags(ListTagsRequest.newBuilder().setParent(pkg.getName()).build()).iterateAll()) n++;
        check("ListTags returns both tags", n == 2, "n=" + n);
      } catch (Exception e) { check("packages / versions / tags flow", false, e.toString()); }

      try {
        c.deleteRepositoryAsync(DeleteRepositoryRequest.newBuilder().setName(name).build()).get();
        check("DeleteRepository completes", true, "");
      } catch (Exception e) { check("DeleteRepository completes", false, e.toString()); }
      try {
        c.getRepository(name);
        check("GetRepository after delete is NOT_FOUND", false, "still found");
      } catch (Exception e) {
        check("GetRepository after delete is NOT_FOUND", e.toString().contains("NotFound") || e.toString().contains("NOT_FOUND") || e.toString().contains("404"), e.toString());
      }
    }
    System.out.println(fails == 0 ? "all checks passed" : fails + " check(s) failed");
    System.exit(fails == 0 ? 0 : 1);
  }
}
