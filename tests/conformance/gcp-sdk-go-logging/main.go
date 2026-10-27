// Real google.golang.org/api/logging/v2 (Google API Client Library for Go, REST/JSON — the Go
// GAPIC client cloud.google.com/go/logging is gRPC-only) conformance against Vyomi's Cloud
// Logging API. ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per
// check; exits non-zero on any failure.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	logging "google.golang.org/api/logging/v2"
	"google.golang.org/api/googleapi"
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

func main() {
	endpoint := env("ENDPOINT", "http://127.0.0.1:9000")
	project := env("PROJECT", "go-log-proj")
	fmt.Printf("== google.golang.org/api/logging/v2 (Go) against %s project=%s ==\n", endpoint, project)
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	svc, err := logging.NewService(ctx, option.WithEndpoint(endpoint), option.WithoutAuthentication())
	if err != nil {
		fmt.Printf("[FAIL] client :: %v\n", err)
		os.Exit(1)
	}
	sfx := fmt.Sprintf("%d", time.Now().UnixNano()%1000000)
	parent := "projects/" + project
	logName := parent + "/logs/go-log-" + sfx

	_, err = svc.Entries.Write(&logging.WriteLogEntriesRequest{
		LogName:  logName,
		Resource: &logging.MonitoredResource{Type: "k8s_container", Labels: map[string]string{"cluster_name": "c1", "namespace_name": "prod"}},
		Entries: []*logging.LogEntry{
			{TextPayload: "hello from the Go SDK", Severity: "NOTICE"},
			{JsonPayload: []byte(`{"order":{"id":1234,"state":"failed"}}`), Severity: "CRITICAL"},
			{TextPayload: "slow request", Severity: "WARNING", HttpRequest: &logging.HttpRequest{RequestMethod: "GET", Status: 504}},
		},
	}).Context(ctx).Do()
	check("entries.write (3 entries)", err == nil, fmt.Sprint(err))

	_, err = svc.Entries.Write(&logging.WriteLogEntriesRequest{Entries: []*logging.LogEntry{{TextPayload: "x"}}}).Context(ctx).Do()
	check("entries.write without a log name → 400", httpCode(err) == 400, fmt.Sprint(err))

	list := func(filter string, extra func(*logging.ListLogEntriesRequest)) (*logging.ListLogEntriesResponse, error) {
		req := &logging.ListLogEntriesRequest{ResourceNames: []string{parent}, Filter: filter}
		if extra != nil {
			extra(req)
		}
		return svc.Entries.List(req).Context(ctx).Do()
	}
	scope := `logName="` + logName + `"`
	r, err := list(scope, func(q *logging.ListLogEntriesRequest) { q.OrderBy = "timestamp asc" })
	check("entries.list (all, oldest first)", err == nil && len(r.Entries) == 3 && r.Entries[0].TextPayload == "hello from the Go SDK" &&
		r.Entries[0].InsertId != "" && r.Entries[0].Timestamp != "" && r.Entries[0].Severity == "NOTICE", fmt.Sprint(err, r))
	r, err = list(scope+" AND severity>=ERROR", nil)
	check("entries.list severity>=ERROR", err == nil && len(r.Entries) == 1 && r.Entries[0].Severity == "CRITICAL" &&
		strings.Contains(string(r.Entries[0].JsonPayload), "failed"), fmt.Sprint(err, r))
	r, err = list(scope+` AND jsonPayload.order.state="failed" AND resource.labels.namespace_name="prod"`, nil)
	check("entries.list nested jsonPayload + resource label", err == nil && len(r.Entries) == 1, fmt.Sprint(err, r))
	r, err = list(scope+" AND httpRequest.status>=500", nil)
	check("entries.list httpRequest.status>=500", err == nil && len(r.Entries) == 1 && r.Entries[0].HttpRequest.Status == 504, fmt.Sprint(err, r))
	r, err = list(scope+` AND (severity=NOTICE OR severity=WARNING) AND NOT textPayload:"slow"`, nil)
	check("entries.list OR / NOT / :", err == nil && len(r.Entries) == 1 && r.Entries[0].Severity == "NOTICE", fmt.Sprint(err, r))
	r, err = list(scope, func(q *logging.ListLogEntriesRequest) { q.OrderBy = "timestamp desc"; q.PageSize = 2 })
	var r2 *logging.ListLogEntriesResponse
	if err == nil {
		r2, err = list(scope, func(q *logging.ListLogEntriesRequest) { q.OrderBy = "timestamp desc"; q.PageSize = 2; q.PageToken = r.NextPageToken })
	}
	check("entries.list pagination", err == nil && len(r.Entries) == 2 && r.NextPageToken != "" && len(r2.Entries) == 1, fmt.Sprint(err, r))
	_, err = list("severity=(", nil)
	check("entries.list with a bad filter → 400", httpCode(err) == 400, fmt.Sprint(err))

	lr, err := svc.Projects.Logs.List(parent).Context(ctx).Do()
	found := false
	if err == nil {
		for _, n := range lr.LogNames {
			found = found || n == logName
		}
	}
	check("logs.list contains the log", found, fmt.Sprint(err, lr))

	// sinks
	sinkID := "go-sink-" + sfx
	sinkPath := parent + "/sinks/" + sinkID
	s, err := svc.Projects.Sinks.Create(parent, &logging.LogSink{Name: sinkID, Destination: "pubsub.googleapis.com/projects/" + project + "/topics/logs-" + sfx,
		Filter: "severity>=ERROR", Description: "go sink"}).UniqueWriterIdentity(true).Context(ctx).Do()
	check("sinks.create", err == nil && s.Name == sinkID && strings.HasPrefix(s.WriterIdentity, "serviceAccount:") && s.CreateTime != "", fmt.Sprint(err, s))
	_, err = svc.Projects.Sinks.Create(parent, &logging.LogSink{Name: sinkID, Destination: "storage.googleapis.com/x"}).Context(ctx).Do()
	check("sinks.create duplicate → 409", httpCode(err) == 409, fmt.Sprint(err))
	_, err = svc.Projects.Sinks.Create(parent, &logging.LogSink{Name: "bad-" + sfx, Destination: "storage.googleapis.com/x", Filter: "((("}).Context(ctx).Do()
	check("sinks.create unparseable filter → 400", httpCode(err) == 400, fmt.Sprint(err))
	s, err = svc.Projects.Sinks.Get(sinkPath).Context(ctx).Do()
	check("sinks.get", err == nil && s.Filter == "severity>=ERROR" && strings.Contains(s.Destination, "pubsub.googleapis.com"), fmt.Sprint(err, s))
	s, err = svc.Projects.Sinks.Update(sinkPath, &logging.LogSink{Name: sinkID, Destination: "storage.googleapis.com/go-archive-" + sfx, Filter: "severity>=WARNING"}).
		UpdateMask("destination,filter").Context(ctx).Do()
	check("sinks.update (PUT + update mask)", err == nil && s.Filter == "severity>=WARNING" && strings.HasPrefix(s.Destination, "storage."), fmt.Sprint(err, s))
	sl, err := svc.Projects.Sinks.List(parent).Context(ctx).Do()
	check("sinks.list", err == nil && len(sl.Sinks) >= 1 && sl.Sinks[0].Name == sinkID, fmt.Sprint(err, sl))
	_, err = svc.Projects.Sinks.Delete(sinkPath).Context(ctx).Do()
	_, err2 := svc.Projects.Sinks.Get(sinkPath).Context(ctx).Do()
	check("sinks.delete (then get → 404)", err == nil && httpCode(err2) == 404, fmt.Sprint(err, err2))

	// metrics
	metricID := "go_metric_" + sfx
	m, err := svc.Projects.Metrics.Create(parent, &logging.LogMetric{Name: metricID, Filter: "severity>=ERROR", Description: "errors"}).Context(ctx).Do()
	check("metrics.create", err == nil && m.Name == metricID && m.MetricDescriptor != nil && m.MetricDescriptor.MetricKind == "DELTA" &&
		m.MetricDescriptor.ValueType == "INT64", fmt.Sprint(err, m))
	_, err = svc.Projects.Metrics.Create(parent, &logging.LogMetric{Name: metricID, Filter: "severity>=ERROR"}).Context(ctx).Do()
	check("metrics.create duplicate → 409", httpCode(err) == 409, fmt.Sprint(err))
	m, err = svc.Projects.Metrics.Update(parent+"/metrics/"+metricID, &logging.LogMetric{Name: metricID, Filter: "severity>=WARNING", Description: "warnings"}).Context(ctx).Do()
	check("metrics.update", err == nil && m.Filter == "severity>=WARNING" && m.Description == "warnings", fmt.Sprint(err, m))
	ml, err := svc.Projects.Metrics.List(parent).Context(ctx).Do()
	check("metrics.list", err == nil && len(ml.Metrics) == 1, fmt.Sprint(err, ml))
	_, err = svc.Projects.Metrics.Delete(parent + "/metrics/" + metricID).Context(ctx).Do()
	_, err2 = svc.Projects.Metrics.Get(parent + "/metrics/" + metricID).Context(ctx).Do()
	check("metrics.delete (then get → 404)", err == nil && httpCode(err2) == 404, fmt.Sprint(err, err2))

	// exclusions
	exID := "go-excl-" + sfx
	x, err := svc.Projects.Exclusions.Create(parent, &logging.LogExclusion{Name: exID, Filter: "severity<WARNING", Description: "noise"}).Context(ctx).Do()
	check("exclusions.create", err == nil && x.Name == exID, fmt.Sprint(err, x))
	x, err = svc.Projects.Exclusions.Patch(parent+"/exclusions/"+exID, &logging.LogExclusion{Disabled: true}).UpdateMask("disabled").Context(ctx).Do()
	check("exclusions.patch", err == nil && x.Disabled, fmt.Sprint(err, x))
	_, err = svc.Projects.Exclusions.Patch(parent+"/exclusions/"+exID, &logging.LogExclusion{Disabled: false}).Context(ctx).Do()
	check("exclusions.patch without a mask → 400", httpCode(err) == 400, fmt.Sprint(err))
	_, err = svc.Projects.Exclusions.Delete(parent + "/exclusions/" + exID).Context(ctx).Do()
	_, err2 = svc.Projects.Exclusions.Get(parent + "/exclusions/" + exID).Context(ctx).Do()
	check("exclusions.delete (then get → 404)", err == nil && httpCode(err2) == 404, fmt.Sprint(err, err2))

	// buckets
	bucketID := "go-bucket-" + sfx
	bp := parent + "/locations/global"
	b, err := svc.Projects.Locations.Buckets.Create(bp, &logging.LogBucket{RetentionDays: 45, Description: "go bucket"}).BucketId(bucketID).Context(ctx).Do()
	check("buckets.create", err == nil && strings.HasSuffix(b.Name, "/buckets/"+bucketID) && b.RetentionDays == 45 && b.LifecycleState == "ACTIVE", fmt.Sprint(err, b))
	b, err = svc.Projects.Locations.Buckets.Get(bp + "/buckets/_Default").Context(ctx).Do()
	check("buckets.get _Default", err == nil && b.RetentionDays == 30, fmt.Sprint(err, b))
	b, err = svc.Projects.Locations.Buckets.Patch(bp+"/buckets/"+bucketID, &logging.LogBucket{RetentionDays: 90}).UpdateMask("retentionDays").Context(ctx).Do()
	check("buckets.patch (retention)", err == nil && b.RetentionDays == 90, fmt.Sprint(err, b))
	_, err = svc.Projects.Locations.Buckets.Delete(bp + "/buckets/" + bucketID).Context(ctx).Do()
	b, err2 = svc.Projects.Locations.Buckets.Get(bp + "/buckets/" + bucketID).Context(ctx).Do()
	check("buckets.delete (soft: DELETE_REQUESTED)", err == nil && err2 == nil && b.LifecycleState == "DELETE_REQUESTED", fmt.Sprint(err, err2))
	_, err = svc.Projects.Locations.Buckets.Undelete(bp+"/buckets/"+bucketID, &logging.UndeleteBucketRequest{}).Context(ctx).Do()
	b, _ = svc.Projects.Locations.Buckets.Get(bp + "/buckets/" + bucketID).Context(ctx).Do()
	check("buckets.undelete", err == nil && b != nil && b.LifecycleState == "ACTIVE", fmt.Sprint(err, b))

	md, err := svc.MonitoredResourceDescriptors.List().Context(ctx).Do()
	check("monitoredResourceDescriptors.list", err == nil && len(md.ResourceDescriptors) > 3, fmt.Sprint(err))

	_, err = svc.Projects.Logs.Delete(logName).Context(ctx).Do()
	r, err2 = list(scope, nil)
	check("logs.delete removes the entries", err == nil && err2 == nil && len(r.Entries) == 0, fmt.Sprint(err, err2))

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
