import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.List;
import java.util.concurrent.Callable;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.core.SdkBytes;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.ecr.EcrClient;
import software.amazon.awssdk.services.ecr.model.*;

/**
 * AWS SDK for Java v2 conformance for Amazon ECR against the Vyomi appliance.
 *
 * An UNMODIFIED EcrClient with only the endpoint overridden: repository lifecycle,
 * the layer-upload protocol, PutImage / BatchGetImage / ListImages / DescribeImages,
 * policies, tags, scanning, authorization token and the documented error codes.
 *
 *   ENDPOINT=http://localhost:9000 mvn -q -B compile exec:java -Dexec.mainClass=EcrConformance
 *
 * One [PASS]/[FAIL] line per check; exit code 1 on any failure.
 */
public class EcrConformance {
    static int fails = 0;

    static void check(String name, boolean ok) {
        check(name, ok, null);
    }

    static void check(String name, boolean ok, String detail) {
        System.out.println("[" + (ok ? "PASS" : "FAIL") + "] " + name + (!ok && detail != null ? " :: " + detail : ""));
        if (!ok) fails++;
    }

    static <T> T run(String name, Callable<T> c) {
        try {
            T v = c.call();
            check(name, true, null);
            return v;
        } catch (Throwable t) {
            check(name, false, t.toString());
            return null;
        }
    }

    static String sha256(byte[] b) throws Exception {
        StringBuilder sb = new StringBuilder("sha256:");
        for (byte x : MessageDigest.getInstance("SHA-256").digest(b)) sb.append(String.format("%02x", x));
        return sb.toString();
    }

    public static void main(String[] args) throws Exception {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://localhost:9000");
        EcrClient ecr = EcrClient.builder()
                .endpointOverride(URI.create(endpoint))
                .region(Region.US_EAST_1)
                .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
                .build();
        String repo = "java-conf/app-" + Long.toString(System.currentTimeMillis(), 36);

        Repository created = run("CreateRepository", () -> ecr.createRepository(r -> r.repositoryName(repo)
                .imageScanningConfiguration(s -> s.scanOnPush(false))
                .tags(Tag.builder().key("team").value("platform").build())).repository());
        check("CreateRepository returns ARN, URI and defaults",
                created != null && created.repositoryArn().endsWith(":repository/" + repo)
                        && created.repositoryUri().endsWith("/" + repo)
                        && created.imageTagMutability() == ImageTagMutability.MUTABLE
                        && created.encryptionConfiguration().encryptionType() == EncryptionType.AES256
                        && created.createdAt() != null, String.valueOf(created));
        try {
            ecr.createRepository(r -> r.repositoryName(repo));
            check("CreateRepository twice is RepositoryAlreadyExistsException", false, "no error");
        } catch (RepositoryAlreadyExistsException e) {
            check("CreateRepository twice is RepositoryAlreadyExistsException", true, null);
        }
        try {
            ecr.createRepository(r -> r.repositoryName("Bad_Name"));
            check("CreateRepository rejects an invalid name (InvalidParameterException)", false, "no error");
        } catch (InvalidParameterException e) {
            check("CreateRepository rejects an invalid name (InvalidParameterException)", true, null);
        }
        List<Repository> repos = run("DescribeRepositories by name", () -> ecr.describeRepositories(r -> r.repositoryNames(repo)).repositories());
        check("DescribeRepositories returns the repository", repos != null && repos.size() == 1 && repos.get(0).repositoryName().equals(repo), String.valueOf(repos));
        try {
            ecr.describeRepositories(r -> r.repositoryNames("nope/missing"));
            check("DescribeRepositories on a missing repo is RepositoryNotFoundException", false, "no error");
        } catch (RepositoryNotFoundException e) {
            check("DescribeRepositories on a missing repo is RepositoryNotFoundException", true, null);
        }

        // ── layer upload protocol ──
        byte[] layer = "vyomi-layer-content".getBytes(StandardCharsets.UTF_8);
        String layerDigest = sha256(layer);
        String uploadId = run("InitiateLayerUpload", () -> ecr.initiateLayerUpload(r -> r.repositoryName(repo)).uploadId());
        run("UploadLayerPart", () -> ecr.uploadLayerPart(r -> r.repositoryName(repo).uploadId(uploadId)
                .partFirstByte(0L).partLastByte((long) layer.length - 1).layerPartBlob(SdkBytes.fromByteArray(layer))));
        String got = run("CompleteLayerUpload", () -> ecr.completeLayerUpload(r -> r.repositoryName(repo).uploadId(uploadId)
                .layerDigests(layerDigest)).layerDigest());
        check("CompleteLayerUpload returns the computed digest", layerDigest.equals(got), String.valueOf(got));
        List<Layer> layers = run("BatchCheckLayerAvailability", () -> ecr.batchCheckLayerAvailability(r -> r.repositoryName(repo)
                .layerDigests(layerDigest, "sha256:" + "0".repeat(64))).layers());
        check("layer is AVAILABLE, unknown digest UNAVAILABLE", layers != null && layers.size() == 2
                && layers.get(0).layerAvailability() == LayerAvailability.AVAILABLE
                && layers.get(1).layerAvailability() == LayerAvailability.UNAVAILABLE, String.valueOf(layers));

        // ── images ──
        String manifest = "{\"schemaVersion\":2,\"mediaType\":\"application/vnd.docker.distribution.manifest.v2+json\","
                + "\"config\":{\"mediaType\":\"application/vnd.docker.container.image.v1+json\",\"size\":" + layer.length + ",\"digest\":\"" + layerDigest + "\"},"
                + "\"layers\":[{\"mediaType\":\"application/vnd.docker.image.rootfs.diff.tar.gzip\",\"size\":" + layer.length + ",\"digest\":\"" + layerDigest + "\"}]}";
        String manifestDigest = sha256(manifest.getBytes(StandardCharsets.UTF_8));
        Image put = run("PutImage with tag v1", () -> ecr.putImage(r -> r.repositoryName(repo).imageManifest(manifest).imageTag("v1")).image());
        check("PutImage returns the manifest digest and tag", put != null && manifestDigest.equals(put.imageId().imageDigest())
                && "v1".equals(put.imageId().imageTag()), String.valueOf(put));
        try {
            ecr.putImage(r -> r.repositoryName(repo).imageManifest("{\"schemaVersion\":2,\"config\":{\"digest\":\"sha256:" + "f".repeat(64) + "\",\"size\":1},\"layers\":[]}").imageTag("bad"));
            check("PutImage with an unknown layer is LayersNotFoundException", false, "no error");
        } catch (LayersNotFoundException e) {
            check("PutImage with an unknown layer is LayersNotFoundException", true, null);
        }
        run("PutImage adds a second tag to the same digest", () -> ecr.putImage(r -> r.repositoryName(repo).imageManifest(manifest).imageTag("latest")));
        List<ImageIdentifier> ids = run("ListImages", () -> ecr.listImages(r -> r.repositoryName(repo)).imageIds());
        check("ListImages lists both tags", ids != null && ids.size() == 2, String.valueOf(ids));
        List<ImageDetail> details = run("DescribeImages", () -> ecr.describeImages(r -> r.repositoryName(repo)).imageDetails());
        check("DescribeImages reports one image with both tags and its size", details != null && details.size() == 1
                && details.get(0).imageTags().containsAll(List.of("v1", "latest"))
                && details.get(0).imageSizeInBytes() == 2L * layer.length
                && details.get(0).imagePushedAt() != null, String.valueOf(details));
        BatchGetImageResponse bg = run("BatchGetImage", () -> ecr.batchGetImage(r -> r.repositoryName(repo)
                .imageIds(ImageIdentifier.builder().imageTag("v1").build(), ImageIdentifier.builder().imageTag("nope").build())));
        check("BatchGetImage returns the manifest and a failure for the missing tag", bg != null && bg.images().size() == 1
                && bg.images().get(0).imageManifest().equals(manifest) && bg.failures().size() == 1
                && bg.failures().get(0).failureCode() == ImageFailureCode.IMAGE_NOT_FOUND, String.valueOf(bg));
        String dl = run("GetDownloadUrlForLayer", () -> ecr.getDownloadUrlForLayer(r -> r.repositoryName(repo).layerDigest(layerDigest)).downloadUrl());
        check("GetDownloadUrlForLayer returns a URL for the layer", dl != null && dl.contains(layerDigest), String.valueOf(dl));

        // ── immutability ──
        run("PutImageTagMutability IMMUTABLE", () -> ecr.putImageTagMutability(r -> r.repositoryName(repo).imageTagMutability(ImageTagMutability.IMMUTABLE)));
        String manifest2 = manifest.replace("\"schemaVersion\":2", "\"schemaVersion\": 2");
        try {
            ecr.putImage(r -> r.repositoryName(repo).imageManifest(manifest2).imageTag("v1"));
            check("re-tagging in an IMMUTABLE repo is ImageTagAlreadyExistsException", false, "no error");
        } catch (ImageTagAlreadyExistsException e) {
            check("re-tagging in an IMMUTABLE repo is ImageTagAlreadyExistsException", true, null);
        }
        run("PutImageTagMutability back to MUTABLE", () -> ecr.putImageTagMutability(r -> r.repositoryName(repo).imageTagMutability(ImageTagMutability.MUTABLE)));

        // ── scanning ──
        run("PutImageScanningConfiguration scanOnPush", () -> ecr.putImageScanningConfiguration(r -> r.repositoryName(repo)
                .imageScanningConfiguration(s -> s.scanOnPush(true))));
        run("StartImageScan", () -> ecr.startImageScan(r -> r.repositoryName(repo).imageId(i -> i.imageTag("v1"))));
        DescribeImageScanFindingsResponse sf = run("DescribeImageScanFindings", () -> ecr.describeImageScanFindings(r -> r.repositoryName(repo).imageId(i -> i.imageTag("v1"))));
        check("scan completed", sf != null && sf.imageScanStatus().status() == ScanStatus.COMPLETE, String.valueOf(sf));

        // ── policies ──
        String policy = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"pull\",\"Effect\":\"Allow\",\"Principal\":\"*\",\"Action\":[\"ecr:BatchGetImage\"]}]}";
        run("SetRepositoryPolicy", () -> ecr.setRepositoryPolicy(r -> r.repositoryName(repo).policyText(policy)));
        check("GetRepositoryPolicy round-trips", policy.equals(run("GetRepositoryPolicy", () -> ecr.getRepositoryPolicy(r -> r.repositoryName(repo)).policyText())));
        run("DeleteRepositoryPolicy", () -> ecr.deleteRepositoryPolicy(r -> r.repositoryName(repo)));
        try {
            ecr.getRepositoryPolicy(r -> r.repositoryName(repo));
            check("GetRepositoryPolicy after delete is RepositoryPolicyNotFoundException", false, "no error");
        } catch (RepositoryPolicyNotFoundException e) {
            check("GetRepositoryPolicy after delete is RepositoryPolicyNotFoundException", true, null);
        }
        String lifecycle = "{\"rules\":[{\"rulePriority\":1,\"description\":\"keep 10\",\"selection\":{\"tagStatus\":\"any\",\"countType\":\"imageCountMoreThan\",\"countNumber\":10},\"action\":{\"type\":\"expire\"}}]}";
        run("PutLifecyclePolicy", () -> ecr.putLifecyclePolicy(r -> r.repositoryName(repo).lifecyclePolicyText(lifecycle)));
        check("GetLifecyclePolicy round-trips", lifecycle.equals(run("GetLifecyclePolicy", () -> ecr.getLifecyclePolicy(r -> r.repositoryName(repo)).lifecyclePolicyText())));
        try {
            ecr.putLifecyclePolicy(r -> r.repositoryName(repo).lifecyclePolicyText("{\"rules\":[]}"));
            check("an invalid lifecycle policy is ValidationException/InvalidParameterException", false, "no error");
        } catch (software.amazon.awssdk.awscore.exception.AwsServiceException e) {
            check("an invalid lifecycle policy is ValidationException/InvalidParameterException", e instanceof InvalidParameterException || e.awsErrorDetails().errorCode().equals("ValidationException"), e.toString());
        }

        // ── tags ──
        run("TagResource", () -> ecr.tagResource(r -> r.resourceArn(created.repositoryArn()).tags(Tag.builder().key("env").value("dev").build())));
        List<Tag> tags = run("ListTagsForResource", () -> ecr.listTagsForResource(r -> r.resourceArn(created.repositoryArn())).tags());
        check("ListTagsForResource has the creation tag and the new one", tags != null && tags.size() == 2, String.valueOf(tags));
        run("UntagResource", () -> ecr.untagResource(r -> r.resourceArn(created.repositoryArn()).tagKeys("env")));

        // ── auth ──
        AuthorizationData ad = run("GetAuthorizationToken", () -> ecr.getAuthorizationToken().authorizationData().get(0));
        check("authorization token decodes to AWS:<password> and has a proxy endpoint",
                ad != null && new String(Base64.getDecoder().decode(ad.authorizationToken()), StandardCharsets.UTF_8).startsWith("AWS:")
                        && ad.proxyEndpoint().startsWith("http") && ad.expiresAt() != null, String.valueOf(ad));

        // ── delete ──
        try {
            ecr.deleteRepository(r -> r.repositoryName(repo));
            check("DeleteRepository with images is RepositoryNotEmptyException", false, "no error");
        } catch (RepositoryNotEmptyException e) {
            check("DeleteRepository with images is RepositoryNotEmptyException", true, null);
        }
        BatchDeleteImageResponse bd = run("BatchDeleteImage by tag", () -> ecr.batchDeleteImage(r -> r.repositoryName(repo)
                .imageIds(ImageIdentifier.builder().imageTag("v1").build())));
        check("BatchDeleteImage removed the tag", bd != null && bd.imageIds().size() == 1 && bd.failures().isEmpty(), String.valueOf(bd));
        run("DeleteRepository force", () -> ecr.deleteRepository(r -> r.repositoryName(repo).force(true)));
        try {
            ecr.describeRepositories(r -> r.repositoryNames(repo));
            check("the repository is gone", false, "still there");
        } catch (RepositoryNotFoundException e) {
            check("the repository is gone", true, null);
        }

        System.out.println(fails == 0 ? "all checks passed" : fails + " check(s) failed");
        System.exit(fails == 0 ? 0 : 1);
    }
}
