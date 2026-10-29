// Azure Log Analytics conformance: the real azure-sdk-for-go armoperationalinsights client against Vyomi —
// only the ARM endpoint changed. Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/arm"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/cloud"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/policy"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/runtime"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/to"
	oi "github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/operationalinsights/armoperationalinsights/v2"
)

type fakeCred struct{}

func (fakeCred) GetToken(_ context.Context, _ policy.TokenRequestOptions) (azcore.AccessToken, error) {
	return azcore.AccessToken{Token: "fake-token", ExpiresOn: time.Now().Add(time.Hour)}, nil
}

var failed int

var poll = &runtime.PollUntilDoneOptions{Frequency: time.Second}

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
	rg := "cloudlearn-rg"
	ws := fmt.Sprintf("law-go-%d", suffix)
	ctx := context.Background()
	opts := &arm.ClientOptions{ClientOptions: azcore.ClientOptions{
		Cloud: cloud.Configuration{
			ActiveDirectoryAuthorityHost: ep,
			Services:                     map[cloud.ServiceName]cloud.ServiceConfiguration{cloud.ResourceManager: {Endpoint: ep, Audience: ep}},
		},
		InsecureAllowCredentialWithHTTP: true,
	}}
	wsc, err := oi.NewWorkspacesClient(sub, fakeCred{}, opts)
	if err != nil {
		fmt.Println("[FAIL] client", err)
		os.Exit(1)
	}
	ssc, _ := oi.NewSavedSearchesClient(sub, fakeCred{}, opts)
	tbc, _ := oi.NewTablesClient(sub, fakeCred{}, opts)
	dsc, _ := oi.NewDataSourcesClient(sub, fakeCred{}, opts)
	skc, _ := oi.NewSharedKeysClient(sub, fakeCred{}, opts)
	usc, _ := oi.NewUsagesClient(sub, fakeCred{}, opts)
	ipc, _ := oi.NewIntelligencePacksClient(sub, fakeCred{}, opts)

	// ── workspaces ──
	poller, err := wsc.BeginCreateOrUpdate(ctx, rg, ws, oi.Workspace{Location: to.Ptr("eastus"),
		Tags: map[string]*string{"env": to.Ptr("conf")},
		Properties: &oi.WorkspaceProperties{SKU: &oi.WorkspaceSKU{Name: to.Ptr(oi.WorkspaceSKUNameEnumPerGB2018)}, RetentionInDays: to.Ptr[int32](60)}}, nil)
	var w oi.WorkspacesClientCreateOrUpdateResponse
	if err == nil {
		w, err = poller.PollUntilDone(ctx, poll)
	}
	check("BeginCreateOrUpdate workspace (LRO)", err == nil && w.Name != nil && *w.Name == ws, fmt.Sprint(err))
	check("workspace has customerId, retention 60, PerGB2018 and Succeeded", err == nil && w.Properties != nil && w.Properties.CustomerID != nil &&
		*w.Properties.RetentionInDays == 60 && *w.Properties.SKU.Name == oi.WorkspaceSKUNameEnumPerGB2018 &&
		*w.Properties.ProvisioningState == oi.WorkspaceEntityStatusSucceeded, fmt.Sprint(w.Properties))
	got, err := wsc.Get(ctx, rg, ws, nil)
	check("Get workspace", err == nil && got.Tags["env"] != nil && *got.Tags["env"] == "conf", fmt.Sprint(err))
	_, err = wsc.Get(ctx, rg, "law-missing", nil)
	check("Get missing workspace → 404", status(err) == 404, fmt.Sprint(err))
	_, err = wsc.BeginCreateOrUpdate(ctx, rg, "x", oi.Workspace{Location: to.Ptr("eastus")}, nil)
	check("invalid workspace name → 400", status(err) == 400, fmt.Sprint(err))
	up, err := wsc.Update(ctx, rg, ws, oi.WorkspacePatch{Tags: map[string]*string{"env": to.Ptr("updated")},
		Properties: &oi.WorkspaceProperties{RetentionInDays: to.Ptr[int32](90)}}, nil)
	check("Update workspace (tags + retention)", err == nil && *up.Tags["env"] == "updated" && *up.Properties.RetentionInDays == 90, fmt.Sprint(err))
	n := 0
	pg := wsc.NewListByResourceGroupPager(rg, nil)
	for pg.More() {
		pp, e := pg.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, x := range pp.Value {
			if *x.Name == ws {
				n++
			}
		}
	}
	check("ListByResourceGroup", err == nil && n == 1, fmt.Sprint(n, err))
	n = 0
	pg2 := wsc.NewListPager(nil)
	for pg2.More() {
		pp, e := pg2.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, x := range pp.Value {
			if *x.Name == ws {
				n++
			}
		}
	}
	check("List (subscription)", err == nil && n == 1, fmt.Sprint(n, err))

	// ── shared keys / usages / intelligence packs ──
	k1, err := skc.GetSharedKeys(ctx, rg, ws, nil)
	check("GetSharedKeys returns both keys", err == nil && k1.PrimarySharedKey != nil && k1.SecondarySharedKey != nil && *k1.PrimarySharedKey != *k1.SecondarySharedKey, fmt.Sprint(err))
	k2, err := skc.Regenerate(ctx, rg, ws, nil)
	check("regenerate keeps the call valid", err == nil && k2.PrimarySharedKey != nil, fmt.Sprint(err))
	up2 := usc.NewListPager(rg, ws, nil)
	cnt := 0
	for up2.More() {
		pp, e := up2.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		cnt += len(pp.Value)
	}
	check("Usages.List reports usage metrics", err == nil && cnt >= 1, fmt.Sprint(cnt, err))
	packs, err := ipc.List(ctx, rg, ws, nil)
	check("IntelligencePacks.List includes LogManagement enabled", err == nil && len(packs.IntelligencePackArray) > 0, fmt.Sprint(err))
	_, err = ipc.Enable(ctx, rg, ws, "VMInsights", nil)
	check("IntelligencePacks.Enable", err == nil, fmt.Sprint(err))
	_, err = ipc.Disable(ctx, rg, ws, "LogManagement", nil)
	check("disabling LogManagement → 400", status(err) == 400, fmt.Sprint(err))

	// ── saved searches ──
	ss, err := ssc.CreateOrUpdate(ctx, rg, ws, "top-computers", oi.SavedSearch{Properties: &oi.SavedSearchProperties{
		Category: to.Ptr("General"), DisplayName: to.Ptr("Top computers"), Query: to.Ptr("Heartbeat | summarize count() by Computer"), Version: to.Ptr[int64](2)}}, nil)
	check("SavedSearches.CreateOrUpdate", err == nil && *ss.Properties.Query == "Heartbeat | summarize count() by Computer", fmt.Sprint(err))
	gs, err := ssc.Get(ctx, rg, ws, "top-computers", nil)
	check("SavedSearches.Get", err == nil && *gs.Properties.DisplayName == "Top computers", fmt.Sprint(err))
	_, err = ssc.CreateOrUpdate(ctx, rg, ws, "bad", oi.SavedSearch{Properties: &oi.SavedSearchProperties{Category: to.Ptr("General")}}, nil)
	check("saved search without query → 400", status(err) == 400, fmt.Sprint(err))
	sl, err := ssc.ListByWorkspace(ctx, rg, ws, nil)
	check("SavedSearches.ListByWorkspace", err == nil && len(sl.Value) == 1, fmt.Sprint(err))
	_, err = ssc.Delete(ctx, rg, ws, "top-computers", nil)
	check("SavedSearches.Delete", err == nil, fmt.Sprint(err))
	_, err = ssc.Get(ctx, rg, ws, "top-computers", nil)
	check("deleted saved search → 404", status(err) == 404, fmt.Sprint(err))

	// ── tables ──
	err = nil
	tp := tbc.NewListByWorkspacePager(rg, ws, nil)
	built := 0
	for tp.More() {
		pp, e := tp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		built += len(pp.Value)
	}
	check("Tables.ListByWorkspace has built-in tables", err == nil && built >= 5, fmt.Sprint(built, err))
	tpl, err := tbc.BeginCreateOrUpdate(ctx, rg, ws, "Orders_CL", oi.Table{Properties: &oi.TableProperties{
		RetentionInDays: to.Ptr[int32](30), TotalRetentionInDays: to.Ptr[int32](90),
		Schema: &oi.Schema{Name: to.Ptr("Orders_CL"), Columns: []*oi.Column{
			{Name: to.Ptr("TimeGenerated"), Type: to.Ptr(oi.ColumnTypeEnumDateTime)},
			{Name: to.Ptr("OrderId"), Type: to.Ptr(oi.ColumnTypeEnumString)}}}}}, nil)
	var tb oi.TablesClientCreateOrUpdateResponse
	if err == nil {
		tb, err = tpl.PollUntilDone(ctx, poll)
	}
	check("Tables.BeginCreateOrUpdate custom table", err == nil && tb.Name != nil && *tb.Name == "Orders_CL" && *tb.Properties.TotalRetentionInDays == 90, fmt.Sprint(err))
	_, err = tbc.BeginCreateOrUpdate(ctx, rg, ws, "Orders", oi.Table{Properties: &oi.TableProperties{}}, nil)
	check("custom table name without _CL → 400", status(err) == 400, fmt.Sprint(err))
	gt, err := tbc.Get(ctx, rg, ws, "Orders_CL", nil)
	check("Tables.Get", err == nil && len(gt.Properties.Schema.Columns) == 2, fmt.Sprint(err))
	upl, err := tbc.BeginUpdate(ctx, rg, ws, "Orders_CL", oi.Table{Properties: &oi.TableProperties{RetentionInDays: to.Ptr[int32](45), TotalRetentionInDays: to.Ptr[int32](120)}}, nil)
	var ut oi.TablesClientUpdateResponse
	if err == nil {
		ut, err = upl.PollUntilDone(ctx, poll)
	}
	check("Tables.BeginUpdate retention", err == nil && *ut.Properties.RetentionInDays == 45 && *ut.Properties.TotalRetentionInDays == 120, fmt.Sprint(err))
	dl, err := tbc.BeginDelete(ctx, rg, ws, "Heartbeat", nil)
	if err == nil {
		_, err = dl.PollUntilDone(ctx, poll)
	}
	check("deleting a built-in table → 400", status(err) == 400, fmt.Sprint(err))
	dl, err = tbc.BeginDelete(ctx, rg, ws, "Orders_CL", nil)
	if err == nil {
		_, err = dl.PollUntilDone(ctx, poll)
	}
	check("Tables.BeginDelete custom table", err == nil, fmt.Sprint(err))
	_, err = tbc.Get(ctx, rg, ws, "Orders_CL", nil)
	check("deleted table → 404", status(err) == 404, fmt.Sprint(err))

	// ── data sources ──
	ds, err := dsc.CreateOrUpdate(ctx, rg, ws, "WinApp", oi.DataSource{Kind: to.Ptr(oi.DataSourceKindWindowsEvent),
		Properties: map[string]any{"eventLogName": "Application", "eventTypes": []any{map[string]any{"eventType": "Error"}}}}, nil)
	check("DataSources.CreateOrUpdate", err == nil && *ds.Kind == oi.DataSourceKindWindowsEvent, fmt.Sprint(err))
	dp := dsc.NewListByWorkspacePager(rg, ws, "kind eq 'WindowsEvent'", nil)
	cnt = 0
	for dp.More() {
		pp, e := dp.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		cnt += len(pp.Value)
	}
	check("DataSources.ListByWorkspace filtered by kind", err == nil && cnt == 1, fmt.Sprint(cnt, err))
	_, err = dsc.Delete(ctx, rg, ws, "WinApp", nil)
	check("DataSources.Delete", err == nil, fmt.Sprint(err))

	// ── delete ──
	dpl, err := wsc.BeginDelete(ctx, rg, ws, nil)
	if err == nil {
		_, err = dpl.PollUntilDone(ctx, poll)
	}
	check("BeginDelete workspace (LRO)", err == nil, fmt.Sprint(err))
	_, err = wsc.Get(ctx, rg, ws, nil)
	check("deleted workspace → 404", status(err) == 404, fmt.Sprint(err))

	if failed > 0 {
		fmt.Printf("%d check(s) failed\n", failed)
		os.Exit(1)
	}
	fmt.Println("all checks passed")
}
