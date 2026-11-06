// AKS / Azure Kubernetes Service conformance: the real azure-sdk-for-go armcontainerservice client
// against Vyomi — only the ARM endpoint changed.
// Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
package main

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/arm"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/cloud"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/policy"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/runtime"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/to"
	aks "github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/containerservice/armcontainerservice/v6"
)

type fakeCred struct{}

func (fakeCred) GetToken(_ context.Context, _ policy.TokenRequestOptions) (azcore.AccessToken, error) {
	return azcore.AccessToken{Token: "fake-token", ExpiresOn: time.Now().Add(time.Hour)}, nil
}

var failed int

var poll = runtime.PollUntilDoneOptions{Frequency: time.Second}

func check(name string, ok bool, detail string) {
	if ok {
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	failed++
	fmt.Printf("[FAIL] %s %s\n", name, detail)
}

func status(err error) int {
	var re *azcore.ResponseError
	if errors.As(err, &re) {
		return re.StatusCode
	}
	return 0
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
	suffix := time.Now().Unix() % 1000000
	rg := fmt.Sprintf("rg-go-aks-%d", suffix)
	name := fmt.Sprintf("goaks%d", suffix)
	ctx := context.Background()
	opts := &arm.ClientOptions{ClientOptions: azcore.ClientOptions{
		Cloud: cloud.Configuration{
			ActiveDirectoryAuthorityHost: ep,
			Services:                     map[cloud.ServiceName]cloud.ServiceConfiguration{cloud.ResourceManager: {Endpoint: ep, Audience: ep}},
		},
		InsecureAllowCredentialWithHTTP: true,
	}}
	clusters, err := aks.NewManagedClustersClient(sub, fakeCred{}, opts)
	if err != nil {
		fmt.Println("[FAIL] client", err)
		os.Exit(1)
	}
	pools, _ := aks.NewAgentPoolsClient(sub, fakeCred{}, opts)
	maint, _ := aks.NewMaintenanceConfigurationsClient(sub, fakeCred{}, opts)
	snaps, _ := aks.NewSnapshotsClient(sub, fakeCred{}, opts)

	// ── managed clusters ──
	p, err := clusters.BeginCreateOrUpdate(ctx, rg, name, aks.ManagedCluster{
		Location: to.Ptr("eastus"),
		Identity: &aks.ManagedClusterIdentity{Type: to.Ptr(aks.ResourceIdentityTypeSystemAssigned)},
		SKU:      &aks.ManagedClusterSKU{Name: to.Ptr(aks.ManagedClusterSKUNameBase), Tier: to.Ptr(aks.ManagedClusterSKUTierFree)},
		Tags:     map[string]*string{"env": to.Ptr("conf")},
		Properties: &aks.ManagedClusterProperties{
			DNSPrefix:         to.Ptr(name + "-dns"),
			KubernetesVersion: to.Ptr("1.29.9"),
			AgentPoolProfiles: []*aks.ManagedClusterAgentPoolProfile{{
				Name: to.Ptr("nodepool1"), Count: to.Ptr[int32](2), VMSize: to.Ptr("Standard_DS2_v2"),
				Mode: to.Ptr(aks.AgentPoolModeSystem), OSType: to.Ptr(aks.OSTypeLinux),
			}},
		},
	}, nil)
	var cl aks.ManagedClustersClientCreateOrUpdateResponse
	if err == nil {
		cl, err = p.PollUntilDone(ctx, &poll)
	}
	check("BeginCreateOrUpdate cluster (LRO)", err == nil && cl.Name != nil && *cl.Name == name, fmt.Sprint(err))
	fqdn := ""
	if cl.Properties != nil && cl.Properties.Fqdn != nil {
		fqdn = *cl.Properties.Fqdn
	}
	check("cluster has FQDN, Succeeded, Running", fqdn != "" && cl.Properties.ProvisioningState != nil && *cl.Properties.ProvisioningState == "Succeeded" &&
		cl.Properties.PowerState != nil && *cl.Properties.PowerState.Code == aks.CodeRunning, fqdn)
	check("system-assigned identity has a principal", cl.Identity != nil && cl.Identity.PrincipalID != nil, "")
	got, err := clusters.Get(ctx, rg, name, nil)
	check("Get cluster", err == nil && got.Tags["env"] != nil && *got.Tags["env"] == "conf" && *got.Properties.KubernetesVersion == "1.29.9", fmt.Sprint(err))
	check("node pool in agentPoolProfiles", err == nil && len(got.Properties.AgentPoolProfiles) == 1 && *got.Properties.AgentPoolProfiles[0].Count == 2, "")
	_, err = clusters.Get(ctx, rg, "nosuchcluster99", nil)
	check("Get missing cluster → 404", status(err) == 404, fmt.Sprint(err))
	up, err := clusters.BeginUpdateTags(ctx, rg, name, aks.TagsObject{Tags: map[string]*string{"env": to.Ptr("updated")}}, nil)
	if err == nil {
		_, err = up.PollUntilDone(ctx, &poll)
	}
	check("BeginUpdateTags", err == nil, fmt.Sprint(err))
	got, err = clusters.Get(ctx, rg, name, nil)
	check("update persisted", err == nil && got.Tags["env"] != nil && *got.Tags["env"] == "updated", fmt.Sprint(err))
	n := 0
	err = nil
	pg := clusters.NewListByResourceGroupPager(rg, nil)
	for pg.More() {
		pp, e := pg.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(pp.Value)
	}
	check("ListByResourceGroup", err == nil && n == 1, fmt.Sprint(n, err))
	n = 0
	err = nil
	pg2 := clusters.NewListPager(nil)
	for pg2.More() {
		pp, e := pg2.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, c := range pp.Value {
			if c.Name != nil && *c.Name == name {
				n++
			}
		}
	}
	check("List (subscription)", n == 1, fmt.Sprint(n, err))
	_, err = clusters.BeginCreateOrUpdate(ctx, rg, "bad"+name, aks.ManagedCluster{Location: to.Ptr("eastus"),
		Properties: &aks.ManagedClusterProperties{DNSPrefix: to.Ptr("bad-dns"), KubernetesVersion: to.Ptr("9.9.9"),
			AgentPoolProfiles: []*aks.ManagedClusterAgentPoolProfile{{Name: to.Ptr("nodepool1"), Count: to.Ptr[int32](1), Mode: to.Ptr(aks.AgentPoolModeSystem)}}}}, nil)
	check("unsupported Kubernetes version → 400", status(err) == 400, fmt.Sprint(err))

	// ── credentials ──
	adm, err := clusters.ListClusterAdminCredentials(ctx, rg, name, nil)
	cfg := ""
	if err == nil && len(adm.Kubeconfigs) > 0 {
		cfg = string(adm.Kubeconfigs[0].Value)
		if dec, e := base64.StdEncoding.DecodeString(cfg); e == nil && strings.Contains(string(dec), "kind: Config") {
			cfg = string(dec)
		}
	}
	check("ListClusterAdminCredentials returns a kubeconfig", err == nil && strings.Contains(cfg, "kind: Config") && strings.Contains(cfg, "clusterAdmin_"), fmt.Sprint(err, cfg))
	usr, err := clusters.ListClusterUserCredentials(ctx, rg, name, nil)
	check("ListClusterUserCredentials", err == nil && len(usr.Kubeconfigs) == 1, fmt.Sprint(err))

	// ── agent pools ──
	pp, err := pools.BeginCreateOrUpdate(ctx, rg, name, "userpool", aks.AgentPool{Properties: &aks.ManagedClusterAgentPoolProfileProperties{
		Count: to.Ptr[int32](1), VMSize: to.Ptr("Standard_D4s_v3"), Mode: to.Ptr(aks.AgentPoolModeUser), OSType: to.Ptr(aks.OSTypeLinux),
		EnableAutoScaling: to.Ptr(true), MinCount: to.Ptr[int32](1), MaxCount: to.Ptr[int32](4)}}, nil)
	var ap aks.AgentPoolsClientCreateOrUpdateResponse
	if err == nil {
		ap, err = pp.PollUntilDone(ctx, &poll)
	}
	check("AgentPools BeginCreateOrUpdate", err == nil && ap.Properties != nil && *ap.Properties.VMSize == "Standard_D4s_v3", fmt.Sprint(err))
	ag, err := pools.Get(ctx, rg, name, "userpool", nil)
	check("AgentPools Get", err == nil && *ag.Properties.Mode == aks.AgentPoolModeUser && *ag.Properties.MaxCount == 4, fmt.Sprint(err))
	n = 0
	err = nil
	pl := pools.NewListPager(rg, name, nil)
	for pl.More() {
		pg, e := pl.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		n += len(pg.Value)
	}
	check("AgentPools List (system + user)", err == nil && n == 2, fmt.Sprint(n, err))
	_, err = pools.BeginCreateOrUpdate(ctx, rg, name, "BadName", aks.AgentPool{Properties: &aks.ManagedClusterAgentPoolProfileProperties{Count: to.Ptr[int32](1)}}, nil)
	check("invalid pool name → 400", status(err) == 400, fmt.Sprint(err))
	sc, err := pools.BeginCreateOrUpdate(ctx, rg, name, "userpool", aks.AgentPool{Properties: &aks.ManagedClusterAgentPoolProfileProperties{
		Count: to.Ptr[int32](3), EnableAutoScaling: to.Ptr(true), MinCount: to.Ptr[int32](1), MaxCount: to.Ptr[int32](4)}}, nil)
	if err == nil {
		_, err = sc.PollUntilDone(ctx, &poll)
	}
	ag, e2 := pools.Get(ctx, rg, name, "userpool", nil)
	check("scale node pool", err == nil && e2 == nil && *ag.Properties.Count == 3, fmt.Sprint(err, e2))
	upg, err := pools.GetUpgradeProfile(ctx, rg, name, "userpool", nil)
	check("pool upgrade profile", err == nil && upg.Properties != nil && len(upg.Properties.Upgrades) > 0, fmt.Sprint(err))
	_, err = pools.BeginDelete(ctx, rg, name, "nodepool1", nil)
	check("deleting the only system pool → 400", status(err) == 400, fmt.Sprint(err))

	// ── upgrades ──
	prof, err := clusters.GetUpgradeProfile(ctx, rg, name, nil)
	check("cluster upgrade profile lists upgrades", err == nil && prof.Properties != nil && prof.Properties.ControlPlaneProfile != nil &&
		len(prof.Properties.ControlPlaneProfile.Upgrades) > 0, fmt.Sprint(err))
	cl.Properties.KubernetesVersion = to.Ptr("1.30.5")
	cl.Properties.AgentPoolProfiles = nil
	uc, err := clusters.BeginCreateOrUpdate(ctx, rg, name, aks.ManagedCluster{Location: to.Ptr("eastus"), Properties: &aks.ManagedClusterProperties{
		DNSPrefix: to.Ptr(name + "-dns"), KubernetesVersion: to.Ptr("1.30.5")}}, nil)
	if err == nil {
		_, err = uc.PollUntilDone(ctx, &poll)
	}
	got, e2 = clusters.Get(ctx, rg, name, nil)
	check("upgrade to 1.30.5", err == nil && e2 == nil && *got.Properties.KubernetesVersion == "1.30.5", fmt.Sprint(err, e2))
	_, err = clusters.BeginCreateOrUpdate(ctx, rg, name, aks.ManagedCluster{Location: to.Ptr("eastus"), Properties: &aks.ManagedClusterProperties{
		DNSPrefix: to.Ptr(name + "-dns"), KubernetesVersion: to.Ptr("1.28.14")}}, nil)
	check("downgrade rejected → 400", status(err) == 400, fmt.Sprint(err))

	// ── stop / start ──
	sp, err := clusters.BeginStop(ctx, rg, name, nil)
	if err == nil {
		_, err = sp.PollUntilDone(ctx, &poll)
	}
	got, e2 = clusters.Get(ctx, rg, name, nil)
	check("BeginStop → Stopped", err == nil && e2 == nil && *got.Properties.PowerState.Code == aks.CodeStopped, fmt.Sprint(err, e2))
	st, err := clusters.BeginStart(ctx, rg, name, nil)
	if err == nil {
		_, err = st.PollUntilDone(ctx, &poll)
	}
	got, e2 = clusters.Get(ctx, rg, name, nil)
	check("BeginStart → Running", err == nil && e2 == nil && *got.Properties.PowerState.Code == aks.CodeRunning, fmt.Sprint(err, e2))

	// ── maintenance configurations ──
	_, err = maint.CreateOrUpdate(ctx, rg, name, "default", aks.MaintenanceConfiguration{Properties: &aks.MaintenanceConfigurationProperties{
		TimeInWeek: []*aks.TimeInWeek{{Day: to.Ptr(aks.WeekDaySunday), HourSlots: []*int32{to.Ptr[int32](1), to.Ptr[int32](2)}}}}}, nil)
	check("MaintenanceConfigurations CreateOrUpdate", err == nil, fmt.Sprint(err))
	mg, err := maint.Get(ctx, rg, name, "default", nil)
	check("MaintenanceConfigurations Get", err == nil && len(mg.Properties.TimeInWeek) == 1, fmt.Sprint(err))

	// ── snapshots ──
	sn, err := snaps.CreateOrUpdate(ctx, rg, "snap"+name, aks.Snapshot{Location: to.Ptr("eastus"), Properties: &aks.SnapshotProperties{
		CreationData: &aks.CreationData{SourceResourceID: ap.ID}}}, nil)
	check("Snapshots CreateOrUpdate from a node pool", err == nil && sn.Properties != nil && *sn.Properties.VMSize == "Standard_D4s_v3", fmt.Sprint(err))
	_, err = snaps.Delete(ctx, rg, "snap"+name, nil)
	check("Snapshots Delete", err == nil, fmt.Sprint(err))

	// ── delete ──
	pd, err := pools.BeginDelete(ctx, rg, name, "userpool", nil)
	if err == nil {
		_, err = pd.PollUntilDone(ctx, &poll)
	}
	check("AgentPools BeginDelete", err == nil, fmt.Sprint(err))
	d, err := clusters.BeginDelete(ctx, rg, name, nil)
	if err == nil {
		_, err = d.PollUntilDone(ctx, &poll)
	}
	check("BeginDelete cluster", err == nil, fmt.Sprint(err))
	_, err = clusters.Get(ctx, rg, name, nil)
	check("deleted cluster → 404", status(err) == 404, fmt.Sprint(err))

	if failed > 0 {
		fmt.Printf("%d check(s) failed\n", failed)
		os.Exit(1)
	}
	fmt.Println("all checks passed")
}
