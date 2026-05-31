// Real google.golang.org/api/cloudfunctions/v1 LRO probe: create returns a
// google.longrunning.Operation, poll operations.get to done, then get the
// function. Mirrors how the Functions client and Terraform drive create.
package main

import (
	"context"
	"fmt"
	"os"
	"time"

	cloudfunctions "google.golang.org/api/cloudfunctions/v1"
	"google.golang.org/api/option"
)

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

var pass, fail int

func chk(name string, ok bool, detail string) {
	if ok {
		fmt.Println("PASS", name)
		pass++
	} else {
		fmt.Println("FAIL", name, "::", detail)
		fail++
	}
}

func main() {
	endpoint := env("ENDPOINT", "http://127.0.0.1:9000")
	project := env("PROJECT", "gcp-dev")
	location := "us-central1"
	ctx := context.Background()
	fmt.Printf("== cloudfunctions v1 LRO against %s project=%s ==\n", endpoint, project)

	svc, err := cloudfunctions.NewService(ctx, option.WithoutAuthentication(), option.WithEndpoint(endpoint+"/"))
	if err != nil {
		fmt.Println("FAIL cloudfunctions.NewService ::", err)
		os.Exit(1)
	}

	parent := fmt.Sprintf("projects/%s/locations/%s", project, location)
	fnName := fmt.Sprintf("%s/functions/go-lro-fn-%d", parent, time.Now().Unix())
	fn := &cloudfunctions.CloudFunction{
		Name:             fnName,
		Runtime:          "python311",
		EntryPoint:       "handler",
		SourceArchiveUrl: "gs://example/src.zip",
		HttpsTrigger:     &cloudfunctions.HttpsTrigger{},
	}
	op, err := svc.Projects.Locations.Functions.Create(parent, fn).Do()
	chk("functions.create returns Operation", err == nil && op != nil && op.Name != "", fmt.Sprintf("%v", err))

	done := false
	if op != nil {
		for i := 0; i < 12; i++ {
			o, e := svc.Operations.Get(op.Name).Do()
			if e == nil && o.Done {
				done = true
				break
			}
			time.Sleep(500 * time.Millisecond)
		}
	}
	chk("operations.get polls to done", done, "")

	if got, e := svc.Projects.Locations.Functions.Get(fnName).Do(); e != nil {
		chk("functions.get after create", false, e.Error())
	} else {
		chk("functions.get after create", got != nil, fmt.Sprintf("runtime=%q", got.Runtime))
	}

	_, _ = svc.Projects.Locations.Functions.Delete(fnName).Do()

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
