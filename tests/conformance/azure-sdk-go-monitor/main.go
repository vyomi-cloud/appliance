// Azure Monitor conformance: the real azure-sdk-for-go armmonitor clients (action groups, metric alerts,
// activity log alerts, autoscale settings) against Vyomi — only the ARM endpoint changed. Prints one
// [PASS]/[FAIL] line per check and exits non-zero on any failure.
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
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/to"
	mon "github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/monitor/armmonitor"
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
	sfx := time.Now().Unix() % 1000000
	rg := "cloudlearn-rg"
	agName := fmt.Sprintf("go-ag-%d", sfx)
	alertName := fmt.Sprintf("go-cpu-%d", sfx)
	actName := fmt.Sprintf("go-act-%d", sfx)
	asName := fmt.Sprintf("go-as-%d", sfx)
	vm := fmt.Sprintf("/subscriptions/%s/resourceGroups/%s/providers/Microsoft.Compute/virtualMachines/vm-%d", sub, rg, sfx)
	agID := fmt.Sprintf("/subscriptions/%s/resourceGroups/%s/providers/microsoft.insights/actionGroups/%s", sub, rg, agName)
	ctx := context.Background()
	opts := &arm.ClientOptions{ClientOptions: azcore.ClientOptions{
		Cloud: cloud.Configuration{
			ActiveDirectoryAuthorityHost: ep,
			Services:                     map[cloud.ServiceName]cloud.ServiceConfiguration{cloud.ResourceManager: {Endpoint: ep, Audience: ep}},
		},
		InsecureAllowCredentialWithHTTP: true,
	}}
	ags, err := mon.NewActionGroupsClient(sub, fakeCred{}, opts)
	if err != nil {
		fmt.Println("[FAIL] client", err)
		os.Exit(1)
	}
	alerts, _ := mon.NewMetricAlertsClient(sub, fakeCred{}, opts)
	acts, _ := mon.NewActivityLogAlertsClient(sub, fakeCred{}, opts)
	autos, _ := mon.NewAutoscaleSettingsClient(sub, fakeCred{}, opts)

	// ── action groups ──
	g, err := ags.CreateOrUpdate(ctx, rg, agName, mon.ActionGroupResource{Location: to.Ptr("Global"),
		Tags: map[string]*string{"env": to.Ptr("conf")},
		Properties: &mon.ActionGroup{GroupShortName: to.Ptr("goag"), Enabled: to.Ptr(true),
			EmailReceivers: []*mon.EmailReceiver{{Name: to.Ptr("oncall"), EmailAddress: to.Ptr("oncall@example.com"), UseCommonAlertSchema: to.Ptr(true)}}}}, nil)
	check("ActionGroups.CreateOrUpdate", err == nil && g.Name != nil && *g.Name == agName, fmt.Sprint(err))
	check("email receiver is Enabled", err == nil && g.Properties != nil && len(g.Properties.EmailReceivers) == 1 &&
		g.Properties.EmailReceivers[0].Status != nil && *g.Properties.EmailReceivers[0].Status == mon.ReceiverStatusEnabled, fmt.Sprint(g.Properties))
	gg, err := ags.Get(ctx, rg, agName, nil)
	check("ActionGroups.Get", err == nil && gg.Tags["env"] != nil && *gg.Tags["env"] == "conf", fmt.Sprint(err))
	_, err = ags.Get(ctx, rg, "no-such-ag", nil)
	check("ActionGroups.Get missing → 404", status(err) == 404, fmt.Sprint(err))
	_, err = ags.CreateOrUpdate(ctx, rg, agName+"x", mon.ActionGroupResource{Location: to.Ptr("Global"),
		Properties: &mon.ActionGroup{GroupShortName: to.Ptr("thisiswaytoolong"), Enabled: to.Ptr(true)}}, nil)
	check("short name over 12 characters → 400", status(err) == 400, fmt.Sprint(err))
	up, err := ags.Update(ctx, rg, agName, mon.ActionGroupPatchBody{Properties: &mon.ActionGroupPatch{Enabled: to.Ptr(false)}}, nil)
	check("ActionGroups.Update (disable)", err == nil && up.Properties != nil && up.Properties.Enabled != nil && !*up.Properties.Enabled, fmt.Sprint(err))
	n := 0
	pg := ags.NewListByResourceGroupPager(rg, nil)
	for pg.More() {
		pp, e := pg.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, x := range pp.Value {
			if *x.Name == agName {
				n++
			}
		}
	}
	check("ActionGroups.ListByResourceGroup", err == nil && n == 1, fmt.Sprint(n, err))
	n = 0
	pg2 := ags.NewListBySubscriptionIDPager(nil)
	for pg2.More() {
		pp, e := pg2.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, x := range pp.Value {
			if *x.Name == agName {
				n++
			}
		}
	}
	check("ActionGroups.ListBySubscriptionID", err == nil && n == 1, fmt.Sprint(n, err))

	// ── metric alerts ──
	crit := &mon.MetricAlertSingleResourceMultipleMetricCriteria{
		ODataType: to.Ptr(mon.OdatatypeMicrosoftAzureMonitorSingleResourceMultipleMetricCriteria),
		AllOf: []*mon.MetricCriteria{{CriterionType: to.Ptr(mon.CriterionTypeStaticThresholdCriterion), Name: to.Ptr("HighCpu"),
			MetricName: to.Ptr("Percentage CPU"), Operator: to.Ptr(mon.OperatorGreaterThan), Threshold: to.Ptr(80.0),
			TimeAggregation: to.Ptr(mon.AggregationTypeEnumAverage)}}}
	rule := func(sev int32, c mon.MetricAlertCriteriaClassification) mon.MetricAlertResource {
		return mon.MetricAlertResource{Location: to.Ptr("global"), Properties: &mon.MetricAlertProperties{
			Description: to.Ptr("cpu high"), Severity: to.Ptr(sev), Enabled: to.Ptr(true), Scopes: []*string{to.Ptr(vm)},
			EvaluationFrequency: to.Ptr("PT1M"), WindowSize: to.Ptr("PT5M"), Criteria: c,
			Actions: []*mon.MetricAlertAction{{ActionGroupID: to.Ptr(agID)}}}}
	}
	a, err := alerts.CreateOrUpdate(ctx, rg, alertName, rule(3, crit), nil)
	check("MetricAlerts.CreateOrUpdate", err == nil && a.Name != nil && *a.Name == alertName, fmt.Sprint(err))
	check("alert has autoMitigate default, lastUpdatedTime and the action group", err == nil && a.Properties != nil && a.Properties.AutoMitigate != nil &&
		*a.Properties.AutoMitigate && a.Properties.LastUpdatedTime != nil && len(a.Properties.Actions) == 1 &&
		*a.Properties.Actions[0].ActionGroupID == agID, fmt.Sprint(a.Properties))
	ga, err := alerts.Get(ctx, rg, alertName, nil)
	okCrit := false
	if err == nil && ga.Properties != nil {
		if sc, ok := ga.Properties.Criteria.(*mon.MetricAlertSingleResourceMultipleMetricCriteria); ok && len(sc.AllOf) == 1 {
			okCrit = *sc.AllOf[0].MetricName == "Percentage CPU" && *sc.AllOf[0].Threshold == 80.0
		}
	}
	check("MetricAlerts.Get returns the criteria", okCrit, fmt.Sprint(err))
	_, err = alerts.Get(ctx, rg, "no-such-alert", nil)
	check("MetricAlerts.Get missing → 404", status(err) == 404, fmt.Sprint(err))
	_, err = alerts.CreateOrUpdate(ctx, rg, alertName+"-bad", rule(9, crit), nil)
	check("severity 9 → 400", status(err) == 400, fmt.Sprint(err))
	bad := rule(3, crit)
	bad.Properties.WindowSize = to.Ptr("PT1M")
	bad.Properties.EvaluationFrequency = to.Ptr("PT15M")
	_, err = alerts.CreateOrUpdate(ctx, rg, alertName+"-bad", bad, nil)
	check("window shorter than evaluation frequency → 400", status(err) == 400, fmt.Sprint(err))
	ua, err := alerts.Update(ctx, rg, alertName, mon.MetricAlertResourcePatch{Properties: &mon.MetricAlertPropertiesPatch{Severity: to.Ptr(int32(1))}}, nil)
	check("MetricAlerts.Update (severity)", err == nil && ua.Properties != nil && *ua.Properties.Severity == 1, fmt.Sprint(err))
	n = 0
	pg3 := alerts.NewListByResourceGroupPager(rg, nil)
	for pg3.More() {
		pp, e := pg3.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, x := range pp.Value {
			if *x.Name == alertName {
				n++
			}
		}
	}
	check("MetricAlerts.ListByResourceGroup", err == nil && n == 1, fmt.Sprint(n, err))
	n = 0
	pg4 := alerts.NewListBySubscriptionPager(nil)
	for pg4.More() {
		pp, e := pg4.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, x := range pp.Value {
			if *x.Name == alertName {
				n++
			}
		}
	}
	check("MetricAlerts.ListBySubscription", err == nil && n == 1, fmt.Sprint(n, err))

	// ── activity log alerts ──
	la, err := acts.CreateOrUpdate(ctx, rg, actName, mon.ActivityLogAlertResource{Location: to.Ptr("Global"), Properties: &mon.AlertRuleProperties{
		Scopes: []*string{to.Ptr("/subscriptions/" + sub)}, Enabled: to.Ptr(true),
		Condition: &mon.AlertRuleAllOfCondition{AllOf: []*mon.AlertRuleAnyOfOrLeafCondition{
			{Field: to.Ptr("category"), Equals: to.Ptr("Administrative")}, {Field: to.Ptr("status"), Equals: to.Ptr("Failed")}}},
		Actions: &mon.ActionList{ActionGroups: []*mon.ActionGroupAutoGenerated{{ActionGroupID: to.Ptr(agID)}}}}}, nil)
	check("ActivityLogAlerts.CreateOrUpdate", err == nil && la.Name != nil && *la.Name == actName, fmt.Sprint(err))
	_, err = acts.CreateOrUpdate(ctx, rg, actName+"-bad", mon.ActivityLogAlertResource{Location: to.Ptr("Global"), Properties: &mon.AlertRuleProperties{
		Scopes: []*string{to.Ptr("/subscriptions/" + sub)}, Enabled: to.Ptr(true),
		Condition: &mon.AlertRuleAllOfCondition{AllOf: []*mon.AlertRuleAnyOfOrLeafCondition{{Field: to.Ptr("status"), Equals: to.Ptr("Failed")}}}}}, nil)
	check("activity log alert without a category condition → 400", status(err) == 400, fmt.Sprint(err))
	gl, err := acts.Get(ctx, rg, actName, nil)
	check("ActivityLogAlerts.Get", err == nil && gl.Properties != nil && len(gl.Properties.Condition.AllOf) == 2, fmt.Sprint(err))
	n = 0
	pg5 := acts.NewListByResourceGroupPager(rg, nil)
	for pg5.More() {
		pp, e := pg5.NextPage(ctx)
		if e != nil {
			err = e
			break
		}
		for _, x := range pp.Value {
			if *x.Name == actName {
				n++
			}
		}
	}
	check("ActivityLogAlerts.ListByResourceGroup", err == nil && n == 1, fmt.Sprint(n, err))

	// ── autoscale settings ──
	prof := &mon.AutoscaleProfile{Name: to.Ptr("default"), Capacity: &mon.ScaleCapacity{Minimum: to.Ptr("1"), Maximum: to.Ptr("5"), Default: to.Ptr("2")},
		Rules: []*mon.ScaleRule{{MetricTrigger: &mon.MetricTrigger{MetricName: to.Ptr("CpuPercentage"), MetricResourceURI: to.Ptr(vm),
			TimeGrain: to.Ptr("PT1M"), Statistic: to.Ptr(mon.MetricStatisticTypeAverage), TimeWindow: to.Ptr("PT10M"),
			TimeAggregation: to.Ptr(mon.TimeAggregationTypeAverage), Operator: to.Ptr(mon.ComparisonOperationTypeGreaterThan), Threshold: to.Ptr(70.0)},
			ScaleAction: &mon.ScaleAction{Direction: to.Ptr(mon.ScaleDirectionIncrease), Type: to.Ptr(mon.ScaleTypeChangeCount),
				Value: to.Ptr("1"), Cooldown: to.Ptr("PT5M")}}}}
	as, err := autos.CreateOrUpdate(ctx, rg, asName, mon.AutoscaleSettingResource{Location: to.Ptr("eastus"), Properties: &mon.AutoscaleSetting{
		Profiles: []*mon.AutoscaleProfile{prof}, TargetResourceURI: to.Ptr(vm), Enabled: to.Ptr(true)}}, nil)
	check("AutoscaleSettings.CreateOrUpdate", err == nil && as.Name != nil && *as.Name == asName, fmt.Sprint(err))
	ga2, err := autos.Get(ctx, rg, asName, nil)
	check("AutoscaleSettings.Get returns profile capacity", err == nil && ga2.Properties != nil && len(ga2.Properties.Profiles) == 1 &&
		*ga2.Properties.Profiles[0].Capacity.Maximum == "5", fmt.Sprint(err))
	badProf := &mon.AutoscaleProfile{Name: to.Ptr("p"), Capacity: &mon.ScaleCapacity{Minimum: to.Ptr("6"), Maximum: to.Ptr("5"), Default: to.Ptr("5")}}
	_, err = autos.CreateOrUpdate(ctx, rg, asName+"-bad", mon.AutoscaleSettingResource{Location: to.Ptr("eastus"),
		Properties: &mon.AutoscaleSetting{Profiles: []*mon.AutoscaleProfile{badProf}}}, nil)
	check("autoscale minimum above maximum → 400", status(err) == 400, fmt.Sprint(err))

	// ── delete ──
	for _, d := range []struct {
		name string
		fn   func() error
	}{
		{"AutoscaleSettings.Delete", func() error { _, e := autos.Delete(ctx, rg, asName, nil); return e }},
		{"ActivityLogAlerts.Delete", func() error { _, e := acts.Delete(ctx, rg, actName, nil); return e }},
		{"MetricAlerts.Delete", func() error { _, e := alerts.Delete(ctx, rg, alertName, nil); return e }},
		{"ActionGroups.Delete", func() error { _, e := ags.Delete(ctx, rg, agName, nil); return e }},
	} {
		e := d.fn()
		check(d.name, e == nil, fmt.Sprint(e))
	}
	_, err = alerts.Get(ctx, rg, alertName, nil)
	check("deleted alert → 404", status(err) == 404, fmt.Sprint(err))
	_, err = ags.Delete(ctx, rg, agName, nil)
	check("delete of an absent action group is idempotent", err == nil, fmt.Sprint(err))
	if failed > 0 {
		fmt.Printf("%d check(s) failed\n", failed)
		os.Exit(1)
	}
}
