// Shared-state helper for Firestore: optionally WRITE a doc, then read a named
// doc, via the external gRPC SDK against the emulator. Proves the simulator
// console and real Firestore SDKs share one state (same emulator + project).
package main

import (
	"context"
	"fmt"
	"os"

	"cloud.google.com/go/firestore"
)

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func main() {
	project := env("PROJECT", "gcp-dev")
	ctx := context.Background()
	c, err := firestore.NewClient(ctx, project)
	if err != nil {
		fmt.Println("CLIENT_ERR", err)
		os.Exit(1)
	}
	defer c.Close()

	// WRITE=coll/doc value  -> set fld="value"
	if w := os.Getenv("WRITE"); w != "" {
		var coll, doc string
		fmt.Sscanf(w, "%s", &doc) // placeholder
		// WRITE format "coll|doc|value"
		parts := splitN(w, "|", 3)
		if len(parts) == 3 {
			coll, doc = parts[0], parts[1]
			_, err := c.Collection(coll).Doc(doc).Set(ctx, map[string]any{"fld": parts[2], "src": "sdk"})
			if err != nil {
				fmt.Println("WRITE_ERR", err)
			} else {
				fmt.Println("WROTE", coll+"/"+doc)
			}
		}
	}

	// READ=coll/doc -> print its fld
	if r := os.Getenv("READ"); r != "" {
		parts := splitN(r, "|", 2)
		if len(parts) == 2 {
			snap, err := c.Collection(parts[0]).Doc(parts[1]).Get(ctx)
			if err != nil {
				fmt.Println("READ_ERR", err)
			} else {
				fmt.Println("READ_OK", parts[0]+"/"+parts[1], "fld=", snap.Data()["fld"])
			}
		}
	}
}

func splitN(s, sep string, n int) []string {
	out := []string{}
	cur := ""
	for i := 0; i < len(s); i++ {
		if len(out) < n-1 && i+len(sep) <= len(s) && s[i:i+len(sep)] == sep {
			out = append(out, cur)
			cur = ""
			i += len(sep) - 1
			continue
		}
		cur += string(s[i])
	}
	out = append(out, cur)
	return out
}
