// Real google.golang.org/api sqladmin/v1beta4 (Instances.Patch)
// conformance against Vyomi. ENDPOINT (default http://127.0.0.1:9000), PROJECT.
// One [PASS]/[FAIL] line per check; exits non-zero on any failure.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"google.golang.org/api/googleapi"
	"google.golang.org/api/option"
	sqladmin "google.golang.org/api/sqladmin/v1beta4"
)

var fail int

func check(name string, ok bool, detail string) {
	if ok {
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
	endpoint := strings.TrimRight(env("ENDPOINT", "http://127.0.0.1:9000"), "/") + "/"
	project := env("PROJECT", "vyomi-project")
	ctx, cancel := context.WithTimeout(context.Background(), 240*time.Second)
	defer cancel()
	sfx := fmt.Sprintf("%d", time.Now().UnixNano()%1000000)

	sql, err := sqladmin.NewService(ctx, option.WithEndpoint(endpoint), option.WithoutAuthentication())
	if err != nil {
		fmt.Printf("[FAIL] sql client :: %v\n", err)
		os.Exit(1)
	}
	name := "go-patch-" + sfx
	_, err = sql.Instances.Insert(project, &sqladmin.DatabaseInstance{Name: name, DatabaseVersion: "POSTGRES_15", Region: "us-central1",
		Settings: &sqladmin.Settings{Tier: "db-custom-1-3840"}}).Do()
	check("Instances.Insert", err == nil, fmt.Sprint(err))
	_, err = sql.Instances.Patch(project, name, &sqladmin.DatabaseInstance{Settings: &sqladmin.Settings{Tier: "db-custom-2-7680",
		UserLabels: map[string]string{"env": "test"}}}).Do()
	check("Instances.Patch", err == nil, fmt.Sprint(err))
	inst, err := sql.Instances.Get(project, name).Do()
	check("Instances.Get reflects patched tier + labels", err == nil && inst.Settings != nil && inst.Settings.Tier == "db-custom-2-7680" &&
		inst.Settings.UserLabels["env"] == "test", fmt.Sprintf("%v %v", err, inst))
	_, err = sql.Instances.Patch(project, "no-such-"+sfx, &sqladmin.DatabaseInstance{}).Do()
	check("Instances.Patch missing → 404", httpCode(err) == 404, fmt.Sprint(err))
	_, _ = sql.Instances.Delete(project, name).Do()

	if fail > 0 {
		fmt.Printf("%d check(s) failed\n", fail)
		os.Exit(1)
	}
}
