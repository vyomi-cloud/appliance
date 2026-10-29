// Real google.golang.org/api/monitoring/v3 (the official REST client; cloud.google.com/go/monitoring
// is gRPC-only) conformance against Vyomi's Cloud Monitoring API. ENDPOINT (default
// http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per check; exits non-zero on any failure.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"google.golang.org/api/googleapi"
	monitoring "google.golang.org/api/monitoring/v3"
	"google.golang.org/api/option"
)

var pass, fail int

func check(name string, ok bool, detail string) {
	if ok {
		pass++
		fmt.Printf("[PASS] %s\n", name)
	} else {
		fail++
		fmt.Printf("[FAIL] %s :: %s\n", name, detail)
	}
}

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func httpCode(err error) int {
	var ge *googleapi.Error
	if errors.As(err, &ge) {
		return ge.Code
	}
	return 0
}

func ts(t time.Time) string { return t.UTC().Format(time.RFC3339) }

func main() {
	endpoint := env("ENDPOINT", "http://127.0.0.1:9000")
	project := env("PROJECT", "go-mon-proj")
	fmt.Printf("== google.golang.org/api/monitoring/v3 (Go) against %s project=%s ==\n", endpoint, project)
	ctx, cancel := context.WithTimeout(context.Background(), 180*time.Second)
	defer cancel()
	svc, err := monitoring.NewService(ctx, option.WithEndpoint(strings.TrimRight(endpoint, "/")+"/"), option.WithoutAuthentication())
	if err != nil {
		fmt.Printf("[FAIL] client :: %v\n", err)
		os.Exit(1)
	}
	pname := "projects/" + project
	sfx := fmt.Sprintf("%d", time.Now().UnixNano()%1000000)

	// ── notification channels ─────────────────────────────────────────
	ch, err := svc.Projects.NotificationChannels.Create(pname, &monitoring.NotificationChannel{Type: "email",
		DisplayName: "go-ops-" + sfx, Labels: map[string]string{"email_address": "ops@example.com"}, Enabled: true}).Do()
	check("NotificationChannels.Create (email)", err == nil && strings.HasPrefix(ch.Name, pname+"/notificationChannels/") &&
		ch.VerificationStatus == "VERIFIED", fmt.Sprintf("%v %v", err, ch))
	_, err = svc.Projects.NotificationChannels.Create(pname, &monitoring.NotificationChannel{Type: "email", Labels: map[string]string{}}).Do()
	check("NotificationChannels.Create missing label → 400", httpCode(err) == 400, fmt.Sprintf("%v", err))
	got, err := svc.Projects.NotificationChannels.Get(ch.Name).Do()
	check("NotificationChannels.Get", err == nil && got.Labels["email_address"] == "ops@example.com", fmt.Sprintf("%v", err))
	upd, err := svc.Projects.NotificationChannels.Patch(ch.Name, &monitoring.NotificationChannel{DisplayName: "go-ops-renamed-" + sfx}).
		UpdateMask("display_name").Do()
	check("NotificationChannels.Patch (update mask)", err == nil && strings.HasPrefix(upd.DisplayName, "go-ops-renamed") &&
		upd.Labels["email_address"] == "ops@example.com", fmt.Sprintf("%v %v", err, upd))
	lc, err := svc.Projects.NotificationChannels.List(pname).Do()
	found := false
	if err == nil {
		for _, c := range lc.NotificationChannels {
			found = found || c.Name == ch.Name
		}
	}
	check("NotificationChannels.List", found, fmt.Sprintf("%v", err))
	ld, err := svc.Projects.NotificationChannelDescriptors.List(pname).Do()
	slack := false
	if err == nil {
		for _, d := range ld.ChannelDescriptors {
			slack = slack || d.Type == "slack"
		}
	}
	check("NotificationChannelDescriptors.List", slack, fmt.Sprintf("%v", err))

	// ── alert policies ────────────────────────────────────────────────
	pol, err := svc.Projects.AlertPolicies.Create(pname, &monitoring.AlertPolicy{
		DisplayName: "go-cpu-" + sfx, Combiner: "OR", Enabled: true,
		NotificationChannels: []string{ch.Name},
		Documentation:        &monitoring.Documentation{Content: "CPU is high", MimeType: "text/markdown"},
		UserLabels:           map[string]string{"team": "sre"},
		Conditions: []*monitoring.Condition{{DisplayName: "cpu above 80%",
			ConditionThreshold: &monitoring.MetricThreshold{
				Filter:         `metric.type="compute.googleapis.com/instance/cpu/utilization" AND resource.type="gce_instance"`,
				Comparison:     "COMPARISON_GT",
				ThresholdValue: 0.8,
				Duration:       "300s",
				Aggregations:   []*monitoring.Aggregation{{AlignmentPeriod: "60s", PerSeriesAligner: "ALIGN_MEAN"}},
			}}},
	}).Do()
	check("AlertPolicies.Create", err == nil && strings.HasPrefix(pol.Name, pname+"/alertPolicies/") && pol.Enabled &&
		len(pol.Conditions) == 1 && strings.Contains(pol.Conditions[0].Name, "/conditions/") &&
		pol.Conditions[0].ConditionThreshold.Comparison == "COMPARISON_GT" && pol.Conditions[0].ConditionThreshold.ThresholdValue == 0.8 &&
		pol.Conditions[0].ConditionThreshold.Duration == "300s" && pol.CreationRecord != nil && len(pol.NotificationChannels) == 1,
		fmt.Sprintf("%v %v", err, pol))
	_, err = svc.Projects.AlertPolicies.Create(pname, &monitoring.AlertPolicy{DisplayName: "bad", Combiner: "OR"}).Do()
	check("AlertPolicies.Create without conditions → 400", httpCode(err) == 400, fmt.Sprintf("%v", err))
	g, err := svc.Projects.AlertPolicies.Get(pol.Name).Do()
	check("AlertPolicies.Get", err == nil && g.DisplayName == "go-cpu-"+sfx && g.UserLabels["team"] == "sre" &&
		g.Documentation.Content == "CPU is high", fmt.Sprintf("%v", err))
	up, err := svc.Projects.AlertPolicies.Patch(pol.Name, &monitoring.AlertPolicy{DisplayName: "go-cpu-renamed-" + sfx, ForceSendFields: []string{"Enabled"}}).
		UpdateMask("enabled,display_name").Do()
	check("AlertPolicies.Patch (disable + rename)", err == nil && !up.Enabled &&
		up.DisplayName == "go-cpu-renamed-"+sfx && len(up.Conditions) == 1, fmt.Sprintf("%v %v", err, up))
	lp, err := svc.Projects.AlertPolicies.List(pname).Filter(`display_name = "go-cpu-renamed-` + sfx + `"`).Do()
	check("AlertPolicies.List (filter)", err == nil && len(lp.AlertPolicies) == 1, fmt.Sprintf("%v", err))
	_, err = svc.Projects.AlertPolicies.Get(pname + "/alertPolicies/1").Do()
	check("AlertPolicies.Get missing → 404", httpCode(err) == 404, fmt.Sprintf("%v", err))
	_, err = svc.Projects.NotificationChannels.Delete(ch.Name).Do()
	check("NotificationChannels.Delete in use → 400", httpCode(err) == 400, fmt.Sprintf("%v", err))
	_, err = svc.Projects.AlertPolicies.Delete(pol.Name).Do()
	check("AlertPolicies.Delete", err == nil, fmt.Sprintf("%v", err))
	_, err = svc.Projects.NotificationChannels.Delete(ch.Name).Do()
	check("NotificationChannels.Delete", err == nil, fmt.Sprintf("%v", err))

	// ── metric descriptors + time series ──────────────────────────────
	mtype := "custom.googleapis.com/go/latency_" + sfx
	md, err := svc.Projects.MetricDescriptors.Create(pname, &monitoring.MetricDescriptor{Type: mtype, MetricKind: "GAUGE",
		ValueType: "DOUBLE", Unit: "ms", Description: "request latency",
		Labels: []*monitoring.LabelDescriptor{{Key: "route", ValueType: "STRING"}}}).Do()
	check("MetricDescriptors.Create (custom)", err == nil && md.Type == mtype && md.Name == pname+"/metricDescriptors/"+mtype &&
		md.MetricKind == "GAUGE", fmt.Sprintf("%v %v", err, md))
	_, err = svc.Projects.MetricDescriptors.Create(pname, &monitoring.MetricDescriptor{Type: "compute.googleapis.com/mine",
		MetricKind: "GAUGE", ValueType: "DOUBLE"}).Do()
	check("MetricDescriptors.Create non-custom → 400", httpCode(err) == 400, fmt.Sprintf("%v", err))
	gm, err := svc.Projects.MetricDescriptors.Get(pname + "/metricDescriptors/" + mtype).Do()
	check("MetricDescriptors.Get (id with slashes)", err == nil && gm.Unit == "ms", fmt.Sprintf("%v", err))

	now := time.Now().UTC().Truncate(time.Second)
	write := func(v float64, at time.Time, route string) error {
		_, e := svc.Projects.TimeSeries.Create(pname, &monitoring.CreateTimeSeriesRequest{TimeSeries: []*monitoring.TimeSeries{{
			Metric:   &monitoring.Metric{Type: mtype, Labels: map[string]string{"route": route}},
			Resource: &monitoring.MonitoredResource{Type: "global", Labels: map[string]string{"project_id": project}},
			Points:   []*monitoring.Point{{Interval: &monitoring.TimeInterval{EndTime: ts(at)}, Value: &monitoring.TypedValue{DoubleValue: &v}}}}}}).Do()
		return e
	}
	var werr error
	for i := 0; i < 4; i++ {
		werr = write(float64(i+1)*10, now.Add(time.Duration(i-5)*time.Minute), "/a")
	}
	check("TimeSeries.Create (4 points)", werr == nil, fmt.Sprintf("%v", werr))
	check("TimeSeries.Create out-of-order → 400", httpCode(write(1, now.Add(-9*time.Minute), "/a")) == 400, "expected 400")
	lt, err := svc.Projects.TimeSeries.List(pname).Filter(`metric.type="` + mtype + `"`).IntervalStartTime(ts(now.Add(-time.Hour))).
		IntervalEndTime(ts(now)).View("FULL").Do()
	ok := err == nil && len(lt.TimeSeries) == 1
	if ok {
		s := lt.TimeSeries[0]
		ok = len(s.Points) == 4 && *s.Points[0].Value.DoubleValue == 40 && s.Metric.Labels["route"] == "/a" && s.MetricKind == "GAUGE"
	}
	check("TimeSeries.List (newest first)", ok, fmt.Sprintf("%v %v", err, lt))
	la, err := svc.Projects.TimeSeries.List(pname).Filter(`metric.type="` + mtype + `"`).IntervalStartTime(ts(now.Add(-time.Hour))).
		IntervalEndTime(ts(now)).AggregationAlignmentPeriod("3600s").AggregationPerSeriesAligner("ALIGN_MAX").Do()
	ok = err == nil && len(la.TimeSeries) == 1 && len(la.TimeSeries[0].Points) >= 1 && *la.TimeSeries[0].Points[0].Value.DoubleValue == 40
	check("TimeSeries.List aggregated (ALIGN_MAX)", ok, fmt.Sprintf("%v %v", err, la))
	lm, err := svc.Projects.MetricDescriptors.List(pname).Filter(`metric.type = starts_with("custom.googleapis.com/go/")`).Do()
	check("MetricDescriptors.List (starts_with filter)", err == nil && len(lm.MetricDescriptors) >= 1, fmt.Sprintf("%v", err))
	lr, err := svc.Projects.MonitoredResourceDescriptors.List(pname).Do()
	gce := false
	if err == nil {
		for _, r := range lr.ResourceDescriptors {
			gce = gce || r.Type == "gce_instance"
		}
	}
	check("MonitoredResourceDescriptors.List", gce, fmt.Sprintf("%v", err))
	_, err = svc.Projects.MetricDescriptors.Delete(pname + "/metricDescriptors/" + mtype).Do()
	check("MetricDescriptors.Delete", err == nil, fmt.Sprintf("%v", err))
	_, err = svc.Projects.MetricDescriptors.Get(pname + "/metricDescriptors/" + mtype).Do()
	check("MetricDescriptors.Get after delete → 404", httpCode(err) == 404, fmt.Sprintf("%v", err))

	// ── uptime checks ─────────────────────────────────────────────────
	u, err := svc.Projects.UptimeCheckConfigs.Create(pname, &monitoring.UptimeCheckConfig{DisplayName: "go-home-" + sfx,
		MonitoredResource: &monitoring.MonitoredResource{Type: "uptime_url", Labels: map[string]string{"host": "example.com", "project_id": project}},
		HttpCheck:         &monitoring.HttpCheck{Path: "/", Port: 443, UseSsl: true},
		Period:            "300s", Timeout: "10s"}).Do()
	check("UptimeCheckConfigs.Create", err == nil && strings.HasPrefix(u.Name, pname+"/uptimeCheckConfigs/") &&
		u.HttpCheck.Port == 443 && u.Period == "300s", fmt.Sprintf("%v %v", err, u))
	_, err = svc.Projects.UptimeCheckConfigs.Create(pname, &monitoring.UptimeCheckConfig{DisplayName: "no-timeout"}).Do()
	check("UptimeCheckConfigs.Create invalid → 400", httpCode(err) == 400, fmt.Sprintf("%v", err))
	uu, err := svc.Projects.UptimeCheckConfigs.Patch(u.Name, &monitoring.UptimeCheckConfig{DisplayName: "go-home-2-" + sfx}).UpdateMask("display_name").Do()
	check("UptimeCheckConfigs.Patch", err == nil && strings.HasPrefix(uu.DisplayName, "go-home-2") && uu.HttpCheck.Port == 443, fmt.Sprintf("%v", err))
	_, err = svc.Projects.UptimeCheckConfigs.Delete(u.Name).Do()
	check("UptimeCheckConfigs.Delete", err == nil, fmt.Sprintf("%v", err))

	// ── groups ────────────────────────────────────────────────────────
	grp, err := svc.Projects.Groups.Create(pname, &monitoring.Group{DisplayName: "go-prod-" + sfx,
		Filter: `resource.metadata.name=has_substring("prod")`}).Do()
	check("Groups.Create", err == nil && strings.HasPrefix(grp.Name, pname+"/groups/"), fmt.Sprintf("%v %v", err, grp))
	gg, err := svc.Projects.Groups.Get(grp.Name).Do()
	check("Groups.Get", err == nil && gg.DisplayName == "go-prod-"+sfx, fmt.Sprintf("%v", err))
	ug, err := svc.Projects.Groups.Update(grp.Name, &monitoring.Group{Name: grp.Name, DisplayName: "go-prod-2-" + sfx,
		Filter: `resource.metadata.name=has_substring("prod2")`}).Do()
	check("Groups.Update", err == nil && strings.HasPrefix(ug.DisplayName, "go-prod-2"), fmt.Sprintf("%v", err))
	_, err = svc.Projects.Groups.Delete(grp.Name).Do()
	check("Groups.Delete", err == nil, fmt.Sprintf("%v", err))

	fmt.Printf("\n%d passed, %d failed\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
