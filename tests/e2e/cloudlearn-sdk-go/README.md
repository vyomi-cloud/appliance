# cloudlearn-tier-sdk-go

Thin Go client for the CloudLearn simulator's tier API. Same shape as the Java SDK (`cloudlearn-tier-sdk-java`). Wraps `/api/license/*` and `/api/runtime/tier`, parses structured 403/429 bodies into typed `*tier.LimitError`, and provides `WithFallback()` for treating tier denials as soft enhancements.

## Install

```bash
go get cloudlearn.io/tier
```

For local development (this repo):
```go
// go.mod
require cloudlearn.io/tier v1.0.0
replace cloudlearn.io/tier => ../cloudlearn-sdk-go
```

## Use — Status + RuntimeTier

```go
import "cloudlearn.io/tier"

client := tier.NewClient("http://192.168.252.7:9000")

s, err := client.Status(ctx)
if err != nil { log.Fatal(err) }
fmt.Printf("Active: %s · ₹%d/mo · expires in %v days\n",
    s.ActiveTier, *s.PriceInrMonthly, s.DaysUntilExpiry)

// All tiers for a pricing page
rt, _ := client.RuntimeTier(ctx)
fmt.Println("all_tiers keys:", rt["all_tiers"])
```

## Use — Signup

```go
// Free
_, err := client.Signup(ctx, tier.NewSignup("alice@example.com").
    Tier("free").Build())

// Student requires primary_cloud
_, err = client.Signup(ctx, tier.NewSignup("bob@example.com").
    Tier("student").PrimaryCloud("aws").Build())

// Enterprise requires >=10 seats
_, err = client.Signup(ctx, tier.NewSignup("corp@example.com").
    Tier("enterprise").Seats(25).Period("annual").Build())

// Bad signup → typed LimitError
_, err = client.Signup(ctx, tier.NewSignup("bad").Tier("enterprise").Seats(5).Build())
if tle, ok := tier.AsLimitError(err); ok {
    fmt.Printf("denied: code=%s reason=%s\n", tle.Code, tle.Reason)
    // → denied: code=min_seats_required reason=enterprise tier requires at least 10 seats; got 5
}
```

## Use — WithFallback (the soft-handler pattern)

The main reason to use this SDK. Wrap any call that might tier-deny; on
denial your fallback runs and the broader operation continues:

```go
import "cloudlearn.io/tier"

// On Free tier, Eventarc is locked. Without the fallback, the
// trigger fire would surface an error to your caller.
err := tier.WithFallback(
    func() error {
        return fireEventarcTrigger(ctx, "on-item-create")
    },
    func(tle *tier.LimitError) {
        log.Printf("Eventarc denied (tier_locked); upgrade to %s to enable",
            tle.UpgradeTo)
    },
)
// err is nil if it was a tier denial (handler ran), non-nil for real errors
```

Value-returning variant:

```go
url, err := tier.WithFallbackResult(
    func() (string, error) {
        return s3Client.GetSignedURL(ctx, "bucket", "key")
    },
    func(tle *tier.LimitError) {
        log.Print("signed URL not available on Free tier")
    },
)
// url is "" if tier-denied (caller can fall back to a direct link)
```

## Use — explicit check

```go
_, err := pubsubClient.Topic(topic).Publish(ctx, msg).Get(ctx)
if tle, ok := tier.AsLimitError(err); ok {
    showUpgradeUI(tle.UpgradeTo, tle.Reason)
    return
}
if err != nil {
    return err
}
```

## Use — Student primary-cloud switch

```go
_, err := client.SwitchPrimaryCloud(ctx, "gcp")
if tle, ok := tier.AsLimitError(err); ok && tle.Code == "rate_limited" {
    days := int(tle.Raw["days_until_next_change"].(float64))
    fmt.Printf("can switch again in %d days\n", days)
}
```

## What it does NOT do

- **No retry** — when a call is genuinely 403'd, retrying with the same tier will fail again
- **No caching** — each Status() call is a fresh HTTP roundtrip. Wrap in your own cache (TTL ~30s recommended)
- **No SDK-specific error parsing** — `AsLimitError` uses a heuristic message-string match for non-typed errors (boto3, google-cloud-go); the typed path works for direct tier-client calls

## Real-world example

See `tests/e2e/go-inventory/main.go` for the production-shape integration — uses `tier.WithFallback` around the Eventarc trigger fire so POST `/items` stays 200 even when the simulator denies eventing on Free tier.
