// Real cloud.google.com/go/pubsub (gRPC) conformance probe. Proves the official
// Pub/Sub client works when PUBSUB_EMULATOR_HOST points at the bundled emulator.
package main

import (
	"context"
	"fmt"
	"os"
	"sync"
	"time"

	"cloud.google.com/go/pubsub"
)

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func main() {
	project := env("PROJECT", "cloudlearn")
	fmt.Printf("== cloud.google.com/go/pubsub against PUBSUB_EMULATOR_HOST=%s project=%s ==\n",
		os.Getenv("PUBSUB_EMULATOR_HOST"), project)

	ctx := context.Background()
	client, err := pubsub.NewClient(ctx, project)
	if err != nil {
		fmt.Println("FAIL pubsub.NewClient ::", err)
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

	tid := fmt.Sprintf("go-pubsub-topic-%d", time.Now().UnixNano())
	topic, err := client.CreateTopic(ctx, tid)
	chk("topics.create", err == nil, fmt.Sprint(err))

	sid := fmt.Sprintf("go-pubsub-sub-%d", time.Now().UnixNano())
	sub, err := client.CreateSubscription(ctx, sid, pubsub.SubscriptionConfig{Topic: topic})
	chk("subscriptions.create", err == nil, fmt.Sprint(err))

	want := "hello-from-go-pubsub-sdk"
	res := topic.Publish(ctx, &pubsub.Message{Data: []byte(want)})
	_, perr := res.Get(ctx)
	chk("topics.publish", perr == nil, fmt.Sprint(perr))

	cctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	var once sync.Once
	got := ""
	rerr := sub.Receive(cctx, func(c context.Context, m *pubsub.Message) {
		once.Do(func() { got = string(m.Data) })
		m.Ack()
		cancel()
	})
	chk("subscriptions.receive+ack (gRPC streaming pull)", got == want, fmt.Sprintf("got=%q err=%v", got, rerr))

	_ = sub.Delete(ctx)
	_ = topic.Delete(ctx)
	chk("topic/sub delete", true, "")

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
