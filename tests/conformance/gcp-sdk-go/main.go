// Real cloud.google.com/go/storage conformance probe against the CloudLearn
// simulator. Proves whether an UNMODIFIED Google Go client works pointed at the
// simulator. Set STORAGE_EMULATOR_HOST=<host:port> (no scheme) to route both
// read and upload traffic at the simulator's /storage/v1 + /upload/storage/v1.
// PROJECT defaults to vyomi-project.
package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"time"

	"cloud.google.com/go/storage"
)

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func main() {
	project := env("PROJECT", "vyomi-project")
	fmt.Printf("== cloud.google.com/go/storage against STORAGE_EMULATOR_HOST=%s project=%s ==\n",
		os.Getenv("STORAGE_EMULATOR_HOST"), project)

	ctx := context.Background()
	client, err := storage.NewClient(ctx)
	if err != nil {
		fmt.Println("FAIL storage.NewClient ::", err)
		os.Exit(1)
	}
	defer client.Close()

	pass, fail := 0, 0
	chk := func(name string, ok bool, detail string) {
		if ok {
			fmt.Println("PASS", name)
			pass++
		} else {
			fmt.Println("FAIL", name, "::", detail)
			fail++
		}
	}

	bucket := fmt.Sprintf("go-sdk-test-%d", time.Now().UnixNano())
	bkt := client.Bucket(bucket)

	if err := bkt.Create(ctx, project, nil); err != nil {
		chk("buckets.insert", false, err.Error())
	} else {
		chk("buckets.insert", true, "")
	}

	data := []byte("hello-from-go-sdk")
	w := bkt.Object("greeting.txt").NewWriter(ctx)
	w.ContentType = "text/plain"
	_, werr := w.Write(data)
	cerr := w.Close()
	chk("objects.insert (upload)", werr == nil && cerr == nil, fmt.Sprint(werr, " / ", cerr))

	if r, rerr := bkt.Object("greeting.txt").NewReader(ctx); rerr != nil {
		chk("objects.get", false, rerr.Error())
	} else {
		got, _ := io.ReadAll(r)
		r.Close()
		chk("objects.get (download byte-exact)", bytes.Equal(got, data), string(got))
	}

	chk("objects.delete", bkt.Object("greeting.txt").Delete(ctx) == nil, "")
	chk("buckets.delete", bkt.Delete(ctx) == nil, "")

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
