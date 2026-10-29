// Azure Container Apps (Microsoft.App) conformance: the real azure-sdk-for-go
// armappcontainers client against Vyomi, only the ARM endpoint changed.
// Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/arm"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/cloud"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/policy"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/to"
	app "github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/appcontainers/armappcontainers/v3"
)

type fakeCred struct{}

func (fakeCred) GetToken(_ context.Context, _ policy.TokenRequestOptions) (azcore.AccessToken, error) {
	return azcore.AccessToken{Token: "fake-token", ExpiresOn: time.Now().Add(time.Hour)}, nil
}

var failed int

func check(name string, ok bool, detail string) {
	if ok {
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	failed++
	fmt.Printf("[FAIL] %s %s\n", name, detail)
}

func errCode(err error) (int, string) {
	var re *azcore.ResponseError
	if errors.As(err, &re) {
		return re.StatusCode, re.ErrorCode
	}
	return 0, ""
}

// runningStatus reads properties.runningStatus (newer than this SDK's model) straight off the wire.
func runningStatus(ep, id string) string {
	r, err := http.Get(ep + id + "?api-version=2024-03-01")
	if err != nil {
		return err.Error()
	}
	defer r.Body.Close()
	var doc struct {
		Properties struct {
			RunningStatus string `json:"runningStatus"`
		} `json:"properties"`
	}
	_ = json.NewDecoder(r.Body).Decode(&doc)
	return doc.Properties.RunningStatus
}

func main() {
	ep := os.Getenv("ENDPOINT")
	if ep == "" {
		ep = "http://127.0.0.1:9000"
	}
	sub := os.Getenv("SUB")
	if sub == "" {
		sub = "00000000-0000-0000-0000-cloudlearn01"
	}
	rg := fmt.Sprintf("rg-go-app-%d", time.Now().Unix()%100000)
	ctx := context.Background()
	opts := &arm.ClientOptions{ClientOptions: azcore.ClientOptions{
		Cloud: cloud.Configuration{
			ActiveDirectoryAuthorityHost: ep,
			Services: map[cloud.ServiceName]cloud.ServiceConfiguration{cloud.ResourceManager: {Endpoint: ep, Audience: ep}},
		},
		InsecureAllowCredentialWithHTTP: true,
	}}
	cred := fakeCred{}
	envs, _ := app.NewManagedEnvironmentsClient(sub, cred, opts)
	apps, _ := app.NewContainerAppsClient(sub, cred, opts)
	revs, _ := app.NewContainerAppsRevisionsClient(sub, cred, opts)
	reps, _ := app.NewContainerAppsRevisionReplicasClient(sub, cred, opts)
	jobs, _ := app.NewJobsClient(sub, cred, opts)
	dapr, _ := app.NewDaprComponentsClient(sub, cred, opts)

	envName, appName, jobName := "cae-go", "web-go", "job-go"
	loc := "eastus"

	// managed environment lifecycle (LRO poller)
	ep1, err := envs.BeginCreateOrUpdate(ctx, rg, envName, app.ManagedEnvironment{Location: &loc,
		Properties: &app.ManagedEnvironmentProperties{ZoneRedundant: to.Ptr(false)}}, nil)
	var env app.ManagedEnvironmentsClientCreateOrUpdateResponse
	if err == nil {
		env, err = ep1.PollUntilDone(ctx, nil)
	}
	check("ManagedEnvironments.BeginCreateOrUpdate", err == nil && env.Properties != nil && env.Properties.DefaultDomain != nil && *env.Properties.DefaultDomain != "", fmt.Sprint(err))
	g, err := envs.Get(ctx, rg, envName, nil)
	check("ManagedEnvironments.Get", err == nil && *g.Name == envName, fmt.Sprint(err))
	check("environment has staticIp + provisioningState Succeeded", err == nil && g.Properties.StaticIP != nil && *g.Properties.ProvisioningState == app.EnvironmentProvisioningStateSucceeded, "")

	// container app create with ingress + secret + scale
	ap, err := apps.BeginCreateOrUpdate(ctx, rg, appName, app.ContainerApp{Location: &loc,
		Properties: &app.ContainerAppProperties{
			ManagedEnvironmentID: env.ID,
			Configuration: &app.Configuration{
				ActiveRevisionsMode: to.Ptr(app.ActiveRevisionsModeMultiple),
				Ingress:             &app.Ingress{External: to.Ptr(true), TargetPort: to.Ptr(int32(80))},
				Secrets:             []*app.Secret{{Name: to.Ptr("db-pass"), Value: to.Ptr("s3cret")}},
			},
			Template: &app.Template{
				Containers: []*app.Container{{Name: to.Ptr("web"), Image: to.Ptr("mcr.microsoft.com/k8se/quickstart:latest"),
					Resources: &app.ContainerResources{CPU: to.Ptr(0.5), Memory: to.Ptr("1Gi")},
					Env:       []*app.EnvironmentVar{{Name: to.Ptr("MODE"), Value: to.Ptr("test")}, {Name: to.Ptr("PASS"), SecretRef: to.Ptr("db-pass")}}}},
				Scale: &app.Scale{MinReplicas: to.Ptr(int32(1)), MaxReplicas: to.Ptr(int32(5))},
			},
		}}, nil)
	var created app.ContainerAppsClientCreateOrUpdateResponse
	if err == nil {
		created, err = ap.PollUntilDone(ctx, nil)
	}
	check("ContainerApps.BeginCreateOrUpdate", err == nil && created.Properties != nil && created.Properties.LatestRevisionName != nil, fmt.Sprint(err))
	fqdn := ""
	rev1 := ""
	if err == nil {
		fqdn, rev1 = *created.Properties.Configuration.Ingress.Fqdn, *created.Properties.LatestRevisionName
	}
	check("ingress fqdn is assigned from the environment domain", strings.HasPrefix(fqdn, appName+".") && strings.HasSuffix(fqdn, *g.Properties.DefaultDomain), fqdn)
	got, err := apps.Get(ctx, rg, appName, nil)
	check("ContainerApps.Get hides secret values", err == nil && len(got.Properties.Configuration.Secrets) == 1 && got.Properties.Configuration.Secrets[0].Value == nil, fmt.Sprint(err))
	sec, err := apps.ListSecrets(ctx, rg, appName, nil)
	check("ContainerApps.ListSecrets returns the value", err == nil && len(sec.Value) == 1 && *sec.Value[0].Value == "s3cret", fmt.Sprint(err))

	// new template → second revision (Multiple mode keeps both)
	t := got.ContainerApp
	t.Properties.Configuration.Secrets[0].Value = sec.Value[0].Value // GET never returns values; a PUT must resend them
	t.Properties.Template.Containers[0].Image = to.Ptr("mcr.microsoft.com/azuredocs/containerapps-helloworld:latest")
	up, err := apps.BeginCreateOrUpdate(ctx, rg, appName, t, nil)
	var updated app.ContainerAppsClientCreateOrUpdateResponse
	if err == nil {
		updated, err = up.PollUntilDone(ctx, nil)
	}
	check("update with a new template creates a new revision", err == nil && *updated.Properties.LatestRevisionName != rev1, fmt.Sprint(err))
	n := 0
	pager := revs.NewListRevisionsPager(rg, appName, nil)
	for pager.More() {
		pg, e := pager.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(pg.Value)
	}
	check("ContainerAppsRevisions.ListRevisions shows both revisions", err == nil && n == 2, fmt.Sprintf("n=%d err=%v", n, err))
	r1, err := revs.GetRevision(ctx, rg, appName, rev1, nil)
	check("ContainerAppsRevisions.GetRevision", err == nil && *r1.Name == rev1, fmt.Sprint(err))
	_, err = revs.DeactivateRevision(ctx, rg, appName, rev1, nil)
	check("ContainerAppsRevisions.DeactivateRevision", err == nil, fmt.Sprint(err))
	r1, _ = revs.GetRevision(ctx, rg, appName, rev1, nil)
	check("deactivated revision reports Active=false", r1.Properties != nil && r1.Properties.Active != nil && !*r1.Properties.Active, "")
	_, err = revs.ActivateRevision(ctx, rg, appName, rev1, nil)
	check("ContainerAppsRevisions.ActivateRevision", err == nil, fmt.Sprint(err))
	if updated.Properties == nil {
		fmt.Println("cannot continue without the updated app")
		os.Exit(1)
	}
	rl, err := reps.ListReplicas(ctx, rg, appName, *updated.Properties.LatestRevisionName, nil)
	check("ContainerAppsRevisionReplicas.ListReplicas has min replicas", err == nil && len(rl.Value) >= 1, fmt.Sprint(err))

	// stop / start
	st, err := apps.BeginStop(ctx, rg, appName, nil)
	if err == nil {
		_, err = st.PollUntilDone(ctx, nil)
	}
	check("ContainerApps.BeginStop → runningStatus Stopped", err == nil && runningStatus(ep, *created.ID) == "Stopped", fmt.Sprint(err))
	sr, err := apps.BeginStart(ctx, rg, appName, nil)
	if err == nil {
		_, err = sr.PollUntilDone(ctx, nil)
	}
	check("ContainerApps.BeginStart → runningStatus Running", err == nil && runningStatus(ep, *created.ID) == "Running", fmt.Sprint(err))

	// list by resource group + subscription
	cnt := 0
	lp := apps.NewListByResourceGroupPager(rg, nil)
	for lp.More() {
		pg, e := lp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		cnt += len(pg.Value)
	}
	check("ContainerApps.NewListByResourceGroupPager", err == nil && cnt == 1, fmt.Sprintf("cnt=%d %v", cnt, err))
	sp := apps.NewListBySubscriptionPager(nil)
	pg, err := sp.NextPage(ctx)
	check("ContainerApps.NewListBySubscriptionPager", err == nil && len(pg.Value) >= 1, fmt.Sprint(err))

	// Dapr component on the environment
	_, err = dapr.CreateOrUpdate(ctx, rg, envName, "statestore", app.DaprComponent{Properties: &app.DaprComponentProperties{
		ComponentType: to.Ptr("state.redis"), Version: to.Ptr("v1"),
		Metadata: []*app.DaprMetadata{{Name: to.Ptr("redisHost"), Value: to.Ptr("localhost:6379")}}}}, nil)
	check("DaprComponents.CreateOrUpdate", err == nil, fmt.Sprint(err))
	dg, err := dapr.Get(ctx, rg, envName, "statestore", nil)
	check("DaprComponents.Get", err == nil && *dg.Properties.ComponentType == "state.redis", fmt.Sprint(err))

	// job: create, start execution, list executions
	jp, err := jobs.BeginCreateOrUpdate(ctx, rg, jobName, app.Job{Location: &loc, Properties: &app.JobProperties{
		EnvironmentID: env.ID,
		Configuration: &app.JobConfiguration{TriggerType: to.Ptr(app.TriggerTypeManual), ReplicaTimeout: to.Ptr(int32(300)),
			ManualTriggerConfig: &app.JobConfigurationManualTriggerConfig{Parallelism: to.Ptr(int32(1)), ReplicaCompletionCount: to.Ptr(int32(1))}},
		Template: &app.JobTemplate{Containers: []*app.Container{{Name: to.Ptr("job"), Image: to.Ptr("busybox:1.36"),
			Resources: &app.ContainerResources{CPU: to.Ptr(0.25), Memory: to.Ptr("0.5Gi")}}}},
	}}, nil)
	if err == nil {
		_, err = jp.PollUntilDone(ctx, nil)
	}
	check("Jobs.BeginCreateOrUpdate", err == nil, fmt.Sprint(err))
	js, err := jobs.BeginStart(ctx, rg, jobName, nil)
	var exec app.JobsClientStartResponse
	if err == nil {
		exec, err = js.PollUntilDone(ctx, nil)
	}
	check("Jobs.BeginStart returns an execution", err == nil && exec.Name != nil && *exec.Name != "", fmt.Sprint(err))

	// errors carry real ARM codes
	_, err = apps.Get(ctx, rg, "does-not-exist", nil)
	sc, code := errCode(err)
	check("Get missing app → 404 ResourceNotFound", sc == http.StatusNotFound && code == "ResourceNotFound", fmt.Sprint(sc, code))
	bad, err := apps.BeginCreateOrUpdate(ctx, rg, "bad-cpu", app.ContainerApp{Location: &loc, Properties: &app.ContainerAppProperties{
		ManagedEnvironmentID: env.ID, Template: &app.Template{Containers: []*app.Container{{Name: to.Ptr("c"), Image: to.Ptr("nginx"),
			Resources: &app.ContainerResources{CPU: to.Ptr(0.5), Memory: to.Ptr("3Gi")}}}}}}, nil)
	_ = bad
	sc, code = errCode(err)
	check("invalid cpu/memory pair → 400 ContainerAppInvalidResourceTotal", sc == http.StatusBadRequest && code == "ContainerAppInvalidResourceTotal", fmt.Sprint(sc, code))
	_, err = envs.BeginDelete(ctx, rg, envName, nil)
	sc, code = errCode(err)
	check("delete environment with apps → 409", sc == http.StatusConflict, fmt.Sprint(sc, code, err))

	// delete everything
	dj, err := jobs.BeginDelete(ctx, rg, jobName, nil)
	if err == nil {
		_, err = dj.PollUntilDone(ctx, nil)
	}
	check("Jobs.BeginDelete", err == nil, fmt.Sprint(err))
	da, err := apps.BeginDelete(ctx, rg, appName, nil)
	if err == nil {
		_, err = da.PollUntilDone(ctx, nil)
	}
	check("ContainerApps.BeginDelete", err == nil, fmt.Sprint(err))
	_, err = apps.Get(ctx, rg, appName, nil)
	sc, _ = errCode(err)
	check("deleted app → 404", sc == http.StatusNotFound, fmt.Sprint(sc))
	de, err := envs.BeginDelete(ctx, rg, envName, nil)
	if err == nil {
		_, err = de.PollUntilDone(ctx, nil)
	}
	check("ManagedEnvironments.BeginDelete", err == nil, fmt.Sprint(err))

	if failed > 0 {
		fmt.Printf("%d check(s) failed\n", failed)
		os.Exit(1)
	}
}
