// Shared-state helper: optionally CREATE a topic, then list all topic IDs the
// external gRPC SDK sees on the emulator. Used to prove the simulator console
// and real SDKs share one Pub/Sub state (same emulator + project).
package main

import (
	"context"
	"fmt"
	"os"

	"cloud.google.com/go/pubsub"
	"google.golang.org/api/iterator"
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
	c, err := pubsub.NewClient(ctx, project)
	if err != nil {
		fmt.Println("CLIENT_ERR", err)
		os.Exit(1)
	}
	defer c.Close()

	if t := os.Getenv("CREATE"); t != "" {
		if _, err := c.CreateTopic(ctx, t); err != nil {
			fmt.Println("CREATE_ERR", err)
		} else {
			fmt.Println("CREATED", t)
		}
	}

	it := c.Topics(ctx)
	for {
		t, err := it.Next()
		if err == iterator.Done {
			break
		}
		if err != nil {
			fmt.Println("LIST_ERR", err)
			break
		}
		fmt.Println("TOPIC:", t.ID())
	}
}
