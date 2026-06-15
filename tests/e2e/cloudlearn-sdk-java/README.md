# cloudlearn-tier-sdk-java

Thin Java client for the Vyomi simulator's tier API. Wraps `/api/license/*` and `/api/runtime/tier`, parses the structured 403 bodies into typed `TierLimitException`s, and provides a `withFallback()` helper for treating tier denials as soft enhancements rather than hard failures.

## Install

Local Maven build:
```bash
mvn install
```

Then in your app's `pom.xml`:
```xml
<dependency>
  <groupId>cloudlearn</groupId>
  <artifactId>cloudlearn-tier-sdk-java</artifactId>
  <version>1.0.0</version>
</dependency>
```

## Use — getStatus + getRuntimeTier

```java
import cloudlearn.tier.*;

TierClient client = TierClient.builder()
    .endpoint("http://192.168.252.7:9000")
    .build();

TierStatus s = client.getStatus();
System.out.printf("Active: %s · ₹%d/mo · expires in %s days%n",
    s.activeTier(), s.priceInrMonthly(), s.daysUntilExpiry());

// All tiers for a pricing page
Map<String, Object> rt = client.getRuntimeTier();
System.out.println("All tiers: " + ((Map) rt.get("all_tiers")).keySet());
```

## Use — signup

```java
client.signup(SignupRequest.builder("alice@example.com")
    .tier("developer")
    .period("annual")
    .build());

// Student requires primary_cloud
client.signup(SignupRequest.builder("bob@example.com")
    .tier("student")
    .primaryCloud("aws")
    .build());

// Enterprise requires seats >= 10
client.signup(SignupRequest.builder("corp@example.com")
    .tier("enterprise")
    .seats(25)
    .period("annual")
    .build());
```

## Use — withFallback (the soft-handler pattern)

The whole point. Wrap any call that might hit a tier limit; on denial the
fallback runs (typically logging) and your broader operation continues:

```java
import software.amazon.awssdk.services.eventbridge.EventBridgeClient;

EventBridgeClient eb = ...;

// On Free tier, EventBridge is locked. Without the fallback, this throws.
// With it, the throw is converted into a soft handler call:
client.withFallback(
    () -> eb.putEvents(PutEventsRequest.builder()
            .entries(PutEventsRequestEntry.builder()
                    .source("my.app")
                    .detailType("OrderCreated")
                    .detail("{\"id\": 1}")
                    .build())
            .build()),
    err -> log.warn("EventBridge denied (tier_locked): upgrade to {} to enable",
                     err.upgradeTo())
);

// Operation continues — order still gets inserted, queued, etc.
// On Developer+ tier, the publish goes through normally.
```

## Use — explicit error checking

```java
try {
    s3.putObject(req, body);
} catch (Exception e) {
    if (TierLimitException.isTierLimit(e)) {
        // route to upgrade UI
        showUpgradeModal();
        return;
    }
    throw e;
}
```

## Use — Student primary-cloud switch

```java
try {
    client.switchPrimaryCloud("gcp");
} catch (TierLimitException e) {
    if ("rate_limited".equals(e.code())) {
        // raw().path("days_until_next_change").asInt() — show the count
        showRateLimitMsg(e.raw().path("days_until_next_change").asInt());
    }
}
```

## What it does NOT do

- **No retry** — when a call is genuinely 403'd, retrying with the same tier will fail again. Use this SDK to route the user to the upgrade flow.
- **No caching** — every `getStatus()` is a fresh HTTP call. Wrap in your own cache if needed (TTL ~30s recommended).
- **No automatic reauth** — when the license expires + grace ends, calls will start failing with `tier_*` codes. Handle that with a re-signup flow.

## Real-world example

See `tests/e2e/java-orders/src/main/java/cloudlearn/orders/OrdersController.java` for the production-shape integration — uses `withFallback` around the EventBridge publish so POST `/orders` stays 200 even when the simulator denies eventing on Free tier.
