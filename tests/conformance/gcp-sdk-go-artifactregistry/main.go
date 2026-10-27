// Real cloud.google.com/go/artifactregistry (REST client) conformance against Vyomi's
// Artifact Registry. Only the endpoint is changed (ENDPOINT, default http://localhost:9000).
// One [PASS]/[FAIL] line per check; non-zero exit on failure.
package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	artifactregistry "cloud.google.com/go/artifactregistry/apiv1"
	pb "cloud.google.com/go/artifactregistry/apiv1/artifactregistrypb"
	"google.golang.org/api/iterator"
	"google.golang.org/api/option"
	"google.golang.org/genproto/googleapis/iam/v1"
	"google.golang.org/protobuf/types/known/fieldmaskpb"
)

var fails int

func chk(name string, ok bool, detail string) {
	if ok {
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	fails++
	fmt.Printf("[FAIL] %s :: %s\n", name, detail)
}

func main() {
	ep := os.Getenv("ENDPOINT")
	if ep == "" {
		ep = "http://localhost:9000"
	}
	project := os.Getenv("PROJECT")
	if project == "" {
		project = "gcp-dev"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	c, err := artifactregistry.NewRESTClient(ctx, option.WithEndpoint(ep), option.WithoutAuthentication())
	if err != nil {
		fmt.Println("[FAIL] artifactregistry.NewRESTClient ::", err)
		os.Exit(1)
	}
	defer c.Close()

	parent := fmt.Sprintf("projects/%s/locations/us-central1", project)
	id := fmt.Sprintf("go-ar-%d", time.Now().UnixNano()%1000000000)
	name := parent + "/repositories/" + id

	op, err := c.CreateRepository(ctx, &pb.CreateRepositoryRequest{Parent: parent, RepositoryId: id,
		Repository: &pb.Repository{Format: pb.Repository_DOCKER, Description: "go sdk",
			Labels: map[string]string{"team": "sdk"}}})
	chk("CreateRepository returns an operation", err == nil, fmt.Sprint(err))
	if err != nil {
		os.Exit(1)
	}
	repo, err := op.Wait(ctx)
	chk("CreateRepository operation completes with the repository", err == nil && repo.GetName() == name, fmt.Sprint(err))

	_, err = c.CreateRepository(ctx, &pb.CreateRepositoryRequest{Parent: parent, RepositoryId: id,
		Repository: &pb.Repository{Format: pb.Repository_DOCKER}})
	chk("duplicate CreateRepository fails with ALREADY_EXISTS", err != nil && strings.Contains(err.Error(), "AlreadyExists") || err != nil && strings.Contains(err.Error(), "ALREADY_EXISTS") || err != nil && strings.Contains(err.Error(), "409"), fmt.Sprint(err))

	got, err := c.GetRepository(ctx, &pb.GetRepositoryRequest{Name: name})
	chk("GetRepository returns format, description and labels",
		err == nil && got.GetFormat() == pb.Repository_DOCKER && got.GetDescription() == "go sdk" && got.GetLabels()["team"] == "sdk", fmt.Sprint(err))

	it := c.ListRepositories(ctx, &pb.ListRepositoriesRequest{Parent: parent})
	found := false
	for {
		r, e := it.Next()
		if e == iterator.Done {
			break
		}
		if e != nil {
			err = e
			break
		}
		if r.GetName() == name {
			found = true
		}
	}
	chk("ListRepositories contains the repository", found, fmt.Sprint(err))

	upd, err := c.UpdateRepository(ctx, &pb.UpdateRepositoryRequest{
		Repository: &pb.Repository{Name: name, Description: "updated"},
		UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"description"}}})
	chk("UpdateRepository changes the description", err == nil && upd.GetDescription() == "updated", fmt.Sprint(err))

	pol, err := c.SetIamPolicy(ctx, &iam.SetIamPolicyRequest{Resource: name, Policy: &iam.Policy{
		Bindings: []*iam.Binding{{Role: "roles/artifactregistry.reader", Members: []string{"allUsers"}}}}})
	chk("SetIamPolicy stores the binding", err == nil && len(pol.GetBindings()) == 1, fmt.Sprint(err))
	pol, err = c.GetIamPolicy(ctx, &iam.GetIamPolicyRequest{Resource: name})
	chk("GetIamPolicy returns the binding", err == nil && len(pol.GetBindings()) == 1 && pol.GetBindings()[0].GetMembers()[0] == "allUsers", fmt.Sprint(err))
	perm, err := c.TestIamPermissions(ctx, &iam.TestIamPermissionsRequest{Resource: name, Permissions: []string{"artifactregistry.repositories.get"}})
	chk("TestIamPermissions echoes the permission", err == nil && len(perm.GetPermissions()) == 1, fmt.Sprint(err))

	pit := c.ListPackages(ctx, &pb.ListPackagesRequest{Parent: name})
	_, err = pit.Next()
	chk("ListPackages on an empty repository is empty", err == iterator.Done, fmt.Sprint(err))

	// A `docker push` has no API method: the data-plane hook records it (same engine call).
	resp, err := http.Post(ep+"/api/gcp/sub/artifactregistry/pushSample/"+id, "application/json", strings.NewReader(`{"image":"app","tag":"v1"}`))
	if resp != nil {
		resp.Body.Close()
	}
	chk("push a sample image through the data-plane hook", err == nil && resp.StatusCode == 200, fmt.Sprint(err))
	dit := c.ListDockerImages(ctx, &pb.ListDockerImagesRequest{Parent: name})
	img, err := dit.Next()
	chk("ListDockerImages returns the pushed image with its tag", err == nil && len(img.GetTags()) == 1 && img.GetTags()[0] == "v1" && strings.Contains(img.GetUri(), id+"/app@sha256:"), fmt.Sprint(err))
	pk, err := c.ListPackages(ctx, &pb.ListPackagesRequest{Parent: name}).Next()
	chk("ListPackages returns the image package", err == nil && strings.HasSuffix(pk.GetName(), "/packages/app"), fmt.Sprint(err))
	vr, err := c.ListVersions(ctx, &pb.ListVersionsRequest{Parent: pk.GetName()}).Next()
	chk("ListVersions returns the digest version", err == nil && strings.Contains(vr.GetName(), "/versions/sha256:"), fmt.Sprint(err))
	tg, err := c.CreateTag(ctx, &pb.CreateTagRequest{Parent: pk.GetName(), TagId: "stable", Tag: &pb.Tag{Version: vr.GetName()}})
	chk("CreateTag points a new tag at the version", err == nil && strings.HasSuffix(tg.GetName(), "/tags/stable"), fmt.Sprint(err))
	tgs := c.ListTags(ctx, &pb.ListTagsRequest{Parent: pk.GetName()})
	n := 0
	for {
		if _, e := tgs.Next(); e != nil {
			break
		}
		n++
	}
	chk("ListTags returns both tags", n == 2, fmt.Sprint(n))
	vop, err := c.DeleteVersion(ctx, &pb.DeleteVersionRequest{Name: vr.GetName()})
	if err == nil {
		err = vop.Wait(ctx)
	}
	chk("DeleteVersion completes", err == nil, fmt.Sprint(err))
	_, err = c.ListTags(ctx, &pb.ListTagsRequest{Parent: pk.GetName()}).Next()
	chk("deleting the version removes its tags", err == iterator.Done, fmt.Sprint(err))

	_, err = c.GetRepository(ctx, &pb.GetRepositoryRequest{Name: parent + "/repositories/does-not-exist"})
	chk("GetRepository of a missing repository is NOT_FOUND", err != nil && (strings.Contains(err.Error(), "NotFound") || strings.Contains(err.Error(), "404")), fmt.Sprint(err))

	dop, err := c.DeleteRepository(ctx, &pb.DeleteRepositoryRequest{Name: name})
	if err == nil {
		err = dop.Wait(ctx)
	}
	chk("DeleteRepository completes", err == nil, fmt.Sprint(err))
	_, err = c.GetRepository(ctx, &pb.GetRepositoryRequest{Name: name})
	chk("repository is gone after delete", err != nil, "still found")

	if fails > 0 {
		fmt.Printf("%d check(s) failed\n", fails)
		os.Exit(1)
	}
	fmt.Println("all checks passed")
}
