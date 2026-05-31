// Real google.golang.org/api/sqladmin LRO probe: Insert returns an Operation,
// poll operations.get to DONE, then Get the instance, then Delete (Operation).
// This mirrors how Terraform and the Cloud SQL clients drive create/delete.
package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"google.golang.org/api/option"
	sqladmin "google.golang.org/api/sqladmin/v1beta4"
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
	ctx := context.Background()
	fmt.Printf("== sqladmin LRO against %s project=%s ==\n", endpoint, project)

	svc, err := sqladmin.NewService(ctx, option.WithoutAuthentication(), option.WithEndpoint(endpoint+"/"))
	if err != nil {
		fmt.Println("FAIL sqladmin.NewService ::", err)
		os.Exit(1)
	}

	name := fmt.Sprintf("go-lro-sql-%d", time.Now().Unix())
	op, err := svc.Instances.Insert(project, &sqladmin.DatabaseInstance{
		Name:            name,
		DatabaseVersion: "POSTGRES_16",
		Region:          "us-central1",
		Settings:        &sqladmin.Settings{Tier: "db-f1-micro"},
	}).Do()
	chk("instances.insert returns Operation", err == nil && op != nil && op.Name != "", fmt.Sprintf("%v op=%+v", err, op))

	done := false
	if op != nil {
		for i := 0; i < 12; i++ {
			o, e := svc.Operations.Get(project, op.Name).Do()
			if e == nil && o.Status == "DONE" {
				done = true
				break
			}
			time.Sleep(500 * time.Millisecond)
		}
	}
	chk("operations.get polls to DONE", done, "")

	if inst, e := svc.Instances.Get(project, name).Do(); e != nil {
		chk("instances.get after create", false, e.Error())
	} else {
		chk("instances.get after create", inst != nil && inst.Name == name, fmt.Sprintf("name=%q state=%q", inst.Name, inst.State))
	}

	dop, de := svc.Instances.Delete(project, name).Do()
	chk("instances.delete returns Operation", de == nil && dop != nil && dop.Name != "", fmt.Sprintf("%v", de))

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
