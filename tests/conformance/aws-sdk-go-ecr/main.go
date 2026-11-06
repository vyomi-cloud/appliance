// Real aws-sdk-go-v2 conformance for Amazon ECR against the Vyomi appliance.
//
// An UNMODIFIED ecr.Client with only BaseEndpoint overridden: repository
// lifecycle, layer upload, PutImage / BatchGetImage / ListImages / DescribeImages,
// policies, tags, scanning, the authorization token and the documented error codes.
//
//	ENDPOINT=http://localhost:9000 GOFLAGS=-mod=mod go run .
//
// One [PASS]/[FAIL] line per check; exit code 1 on any failure.
package main

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/ecr"
	"github.com/aws/aws-sdk-go-v2/service/ecr/types"
)

var fails int

func check(name string, ok bool, detail ...any) {
	if ok {
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	fails++
	fmt.Printf("[FAIL] %s :: %v\n", name, detail)
}

// must records a pass/fail for an operation that should succeed.
func must(name string, err error) bool {
	check(name, err == nil, err)
	return err == nil
}

func sha(b []byte) string { return fmt.Sprintf("sha256:%x", sha256.Sum256(b)) }

func main() {
	ctx := context.Background()
	endpoint := os.Getenv("ENDPOINT")
	if endpoint == "" {
		endpoint = "http://localhost:9000"
	}
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion("us-east-1"),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")))
	if err != nil {
		panic(err)
	}
	c := ecr.NewFromConfig(cfg, func(o *ecr.Options) { o.BaseEndpoint = aws.String(endpoint) })
	repo := fmt.Sprintf("go-conf/app-%d", time.Now().UnixNano()%1_000_000_000)

	cr, err := c.CreateRepository(ctx, &ecr.CreateRepositoryInput{
		RepositoryName:             aws.String(repo),
		ImageScanningConfiguration: &types.ImageScanningConfiguration{ScanOnPush: false},
		Tags:                       []types.Tag{{Key: aws.String("team"), Value: aws.String("platform")}},
	})
	must("CreateRepository", err)
	var arn string
	if err == nil {
		r := cr.Repository
		arn = aws.ToString(r.RepositoryArn)
		check("CreateRepository returns ARN, URI and defaults",
			strings.HasSuffix(arn, ":repository/"+repo) && strings.HasSuffix(aws.ToString(r.RepositoryUri), "/"+repo) &&
				r.ImageTagMutability == types.ImageTagMutabilityMutable && r.EncryptionConfiguration != nil &&
				r.EncryptionConfiguration.EncryptionType == types.EncryptionTypeAes256 && r.CreatedAt != nil, r)
	}
	_, err = c.CreateRepository(ctx, &ecr.CreateRepositoryInput{RepositoryName: aws.String(repo)})
	var exists *types.RepositoryAlreadyExistsException
	check("CreateRepository twice is RepositoryAlreadyExistsException", errors.As(err, &exists), err)
	_, err = c.CreateRepository(ctx, &ecr.CreateRepositoryInput{RepositoryName: aws.String("Bad_Name")})
	var invalid *types.InvalidParameterException
	check("CreateRepository rejects an invalid name (InvalidParameterException)", errors.As(err, &invalid), err)

	dr, err := c.DescribeRepositories(ctx, &ecr.DescribeRepositoriesInput{RepositoryNames: []string{repo}})
	check("DescribeRepositories returns the repository", err == nil && len(dr.Repositories) == 1 && aws.ToString(dr.Repositories[0].RepositoryName) == repo, err)
	_, err = c.DescribeRepositories(ctx, &ecr.DescribeRepositoriesInput{RepositoryNames: []string{"nope/missing"}})
	var notFound *types.RepositoryNotFoundException
	check("DescribeRepositories on a missing repo is RepositoryNotFoundException", errors.As(err, &notFound), err)

	// ── layer upload protocol ──
	layer := []byte("vyomi-go-layer-content")
	layerDigest := sha(layer)
	up, err := c.InitiateLayerUpload(ctx, &ecr.InitiateLayerUploadInput{RepositoryName: aws.String(repo)})
	if must("InitiateLayerUpload", err) {
		_, err = c.UploadLayerPart(ctx, &ecr.UploadLayerPartInput{RepositoryName: aws.String(repo), UploadId: up.UploadId,
			PartFirstByte: aws.Int64(0), PartLastByte: aws.Int64(int64(len(layer) - 1)), LayerPartBlob: layer})
		must("UploadLayerPart", err)
		cl, err := c.CompleteLayerUpload(ctx, &ecr.CompleteLayerUploadInput{RepositoryName: aws.String(repo), UploadId: up.UploadId, LayerDigests: []string{layerDigest}})
		check("CompleteLayerUpload returns the computed digest", err == nil && aws.ToString(cl.LayerDigest) == layerDigest, err)
	}
	av, err := c.BatchCheckLayerAvailability(ctx, &ecr.BatchCheckLayerAvailabilityInput{RepositoryName: aws.String(repo),
		LayerDigests: []string{layerDigest, "sha256:" + strings.Repeat("0", 64)}})
	check("layer is AVAILABLE, unknown digest UNAVAILABLE", err == nil && len(av.Layers) == 2 &&
		av.Layers[0].LayerAvailability == types.LayerAvailabilityAvailable && av.Layers[1].LayerAvailability == types.LayerAvailabilityUnavailable, err)

	// ── images ──
	manifest := fmt.Sprintf(`{"schemaVersion":2,"mediaType":"application/vnd.docker.distribution.manifest.v2+json","config":{"mediaType":"application/vnd.docker.container.image.v1+json","size":%d,"digest":"%s"},"layers":[{"mediaType":"application/vnd.docker.image.rootfs.diff.tar.gzip","size":%d,"digest":"%s"}]}`,
		len(layer), layerDigest, len(layer), layerDigest)
	pi, err := c.PutImage(ctx, &ecr.PutImageInput{RepositoryName: aws.String(repo), ImageManifest: aws.String(manifest), ImageTag: aws.String("v1")})
	check("PutImage returns the manifest digest and tag", err == nil && aws.ToString(pi.Image.ImageId.ImageDigest) == sha([]byte(manifest)) && aws.ToString(pi.Image.ImageId.ImageTag) == "v1", err)
	badManifest := `{"schemaVersion":2,"config":{"digest":"sha256:` + strings.Repeat("f", 64) + `","size":1},"layers":[]}`
	_, err = c.PutImage(ctx, &ecr.PutImageInput{RepositoryName: aws.String(repo), ImageManifest: aws.String(badManifest), ImageTag: aws.String("bad")})
	var noLayers *types.LayersNotFoundException
	check("PutImage with an unknown layer is LayersNotFoundException", errors.As(err, &noLayers), err)
	_, err = c.PutImage(ctx, &ecr.PutImageInput{RepositoryName: aws.String(repo), ImageManifest: aws.String(manifest), ImageTag: aws.String("latest")})
	must("PutImage adds a second tag to the same digest", err)
	_, err = c.PutImage(ctx, &ecr.PutImageInput{RepositoryName: aws.String(repo), ImageManifest: aws.String(manifest), ImageTag: aws.String("latest")})
	var imgExists *types.ImageAlreadyExistsException
	check("PutImage of an identical tag+digest is ImageAlreadyExistsException", errors.As(err, &imgExists), err)

	li, err := c.ListImages(ctx, &ecr.ListImagesInput{RepositoryName: aws.String(repo)})
	check("ListImages lists both tags", err == nil && len(li.ImageIds) == 2, err)
	di, err := c.DescribeImages(ctx, &ecr.DescribeImagesInput{RepositoryName: aws.String(repo)})
	check("DescribeImages reports one image with both tags and its size", err == nil && len(di.ImageDetails) == 1 &&
		len(di.ImageDetails[0].ImageTags) == 2 && aws.ToInt64(di.ImageDetails[0].ImageSizeInBytes) == int64(2*len(layer)) && di.ImageDetails[0].ImagePushedAt != nil, err)
	bg, err := c.BatchGetImage(ctx, &ecr.BatchGetImageInput{RepositoryName: aws.String(repo),
		ImageIds: []types.ImageIdentifier{{ImageTag: aws.String("v1")}, {ImageTag: aws.String("nope")}}})
	check("BatchGetImage returns the manifest and a failure for the missing tag", err == nil && len(bg.Images) == 1 &&
		aws.ToString(bg.Images[0].ImageManifest) == manifest && len(bg.Failures) == 1 && bg.Failures[0].FailureCode == types.ImageFailureCodeImageNotFound, err)
	dl, err := c.GetDownloadUrlForLayer(ctx, &ecr.GetDownloadUrlForLayerInput{RepositoryName: aws.String(repo), LayerDigest: aws.String(layerDigest)})
	check("GetDownloadUrlForLayer returns a URL for the layer", err == nil && strings.Contains(aws.ToString(dl.DownloadUrl), layerDigest), err)

	// ── immutability ──
	_, err = c.PutImageTagMutability(ctx, &ecr.PutImageTagMutabilityInput{RepositoryName: aws.String(repo), ImageTagMutability: types.ImageTagMutabilityImmutable})
	must("PutImageTagMutability IMMUTABLE", err)
	_, err = c.PutImage(ctx, &ecr.PutImageInput{RepositoryName: aws.String(repo), ImageManifest: aws.String(strings.Replace(manifest, `"schemaVersion":2`, `"schemaVersion": 2`, 1)), ImageTag: aws.String("v1")})
	var tagExists *types.ImageTagAlreadyExistsException
	check("re-tagging in an IMMUTABLE repo is ImageTagAlreadyExistsException", errors.As(err, &tagExists), err)
	_, err = c.PutImageTagMutability(ctx, &ecr.PutImageTagMutabilityInput{RepositoryName: aws.String(repo), ImageTagMutability: types.ImageTagMutabilityMutable})
	must("PutImageTagMutability back to MUTABLE", err)

	// ── scanning ──
	_, err = c.PutImageScanningConfiguration(ctx, &ecr.PutImageScanningConfigurationInput{RepositoryName: aws.String(repo), ImageScanningConfiguration: &types.ImageScanningConfiguration{ScanOnPush: true}})
	must("PutImageScanningConfiguration scanOnPush", err)
	_, err = c.StartImageScan(ctx, &ecr.StartImageScanInput{RepositoryName: aws.String(repo), ImageId: &types.ImageIdentifier{ImageTag: aws.String("v1")}})
	must("StartImageScan", err)
	sf, err := c.DescribeImageScanFindings(ctx, &ecr.DescribeImageScanFindingsInput{RepositoryName: aws.String(repo), ImageId: &types.ImageIdentifier{ImageTag: aws.String("v1")}})
	check("DescribeImageScanFindings reports a completed scan", err == nil && sf.ImageScanStatus != nil && sf.ImageScanStatus.Status == types.ScanStatusComplete, err)

	// ── policies ──
	policy := `{"Version":"2012-10-17","Statement":[{"Sid":"pull","Effect":"Allow","Principal":"*","Action":["ecr:BatchGetImage"]}]}`
	_, err = c.SetRepositoryPolicy(ctx, &ecr.SetRepositoryPolicyInput{RepositoryName: aws.String(repo), PolicyText: aws.String(policy)})
	must("SetRepositoryPolicy", err)
	gp, err := c.GetRepositoryPolicy(ctx, &ecr.GetRepositoryPolicyInput{RepositoryName: aws.String(repo)})
	check("GetRepositoryPolicy round-trips", err == nil && aws.ToString(gp.PolicyText) == policy, err)
	_, err = c.DeleteRepositoryPolicy(ctx, &ecr.DeleteRepositoryPolicyInput{RepositoryName: aws.String(repo)})
	must("DeleteRepositoryPolicy", err)
	_, err = c.GetRepositoryPolicy(ctx, &ecr.GetRepositoryPolicyInput{RepositoryName: aws.String(repo)})
	var noPolicy *types.RepositoryPolicyNotFoundException
	check("GetRepositoryPolicy after delete is RepositoryPolicyNotFoundException", errors.As(err, &noPolicy), err)
	lifecycle := `{"rules":[{"rulePriority":1,"description":"keep 10","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}`
	_, err = c.PutLifecyclePolicy(ctx, &ecr.PutLifecyclePolicyInput{RepositoryName: aws.String(repo), LifecyclePolicyText: aws.String(lifecycle)})
	must("PutLifecyclePolicy", err)
	gl, err := c.GetLifecyclePolicy(ctx, &ecr.GetLifecyclePolicyInput{RepositoryName: aws.String(repo)})
	check("GetLifecyclePolicy round-trips", err == nil && aws.ToString(gl.LifecyclePolicyText) == lifecycle, err)
	_, err = c.DeleteLifecyclePolicy(ctx, &ecr.DeleteLifecyclePolicyInput{RepositoryName: aws.String(repo)})
	must("DeleteLifecyclePolicy", err)
	_, err = c.GetLifecyclePolicy(ctx, &ecr.GetLifecyclePolicyInput{RepositoryName: aws.String(repo)})
	var noLifecycle *types.LifecyclePolicyNotFoundException
	check("GetLifecyclePolicy after delete is LifecyclePolicyNotFoundException", errors.As(err, &noLifecycle), err)

	// ── tags ──
	_, err = c.TagResource(ctx, &ecr.TagResourceInput{ResourceArn: aws.String(arn), Tags: []types.Tag{{Key: aws.String("env"), Value: aws.String("dev")}}})
	must("TagResource", err)
	lt, err := c.ListTagsForResource(ctx, &ecr.ListTagsForResourceInput{ResourceArn: aws.String(arn)})
	check("ListTagsForResource has the creation tag and the new one", err == nil && len(lt.Tags) == 2, err)
	_, err = c.UntagResource(ctx, &ecr.UntagResourceInput{ResourceArn: aws.String(arn), TagKeys: []string{"env"}})
	must("UntagResource", err)

	// ── auth ──
	at, err := c.GetAuthorizationToken(ctx, &ecr.GetAuthorizationTokenInput{})
	ok := err == nil && len(at.AuthorizationData) == 1
	if ok {
		raw, derr := base64.StdEncoding.DecodeString(aws.ToString(at.AuthorizationData[0].AuthorizationToken))
		ok = derr == nil && strings.HasPrefix(string(raw), "AWS:") && strings.HasPrefix(aws.ToString(at.AuthorizationData[0].ProxyEndpoint), "http") && at.AuthorizationData[0].ExpiresAt != nil
	}
	check("GetAuthorizationToken decodes to AWS:<password> with a proxy endpoint and expiry", ok, err)

	// ── delete ──
	_, err = c.DeleteRepository(ctx, &ecr.DeleteRepositoryInput{RepositoryName: aws.String(repo)})
	var notEmpty *types.RepositoryNotEmptyException
	check("DeleteRepository with images is RepositoryNotEmptyException", errors.As(err, &notEmpty), err)
	bd, err := c.BatchDeleteImage(ctx, &ecr.BatchDeleteImageInput{RepositoryName: aws.String(repo), ImageIds: []types.ImageIdentifier{{ImageTag: aws.String("v1")}}})
	check("BatchDeleteImage removed the tag", err == nil && len(bd.ImageIds) == 1 && len(bd.Failures) == 0, err)
	_, err = c.DeleteRepository(ctx, &ecr.DeleteRepositoryInput{RepositoryName: aws.String(repo), Force: true})
	must("DeleteRepository force", err)
	_, err = c.DescribeRepositories(ctx, &ecr.DescribeRepositoriesInput{RepositoryNames: []string{repo}})
	check("the repository is gone", errors.As(err, &notFound), err)

	if fails > 0 {
		fmt.Printf("%d check(s) failed\n", fails)
		os.Exit(1)
	}
	fmt.Println("all checks passed")
}
