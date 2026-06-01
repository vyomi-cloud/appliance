package cloudlearn.tier;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import java.util.function.Consumer;
import java.util.function.Supplier;

/**
 * Thin client for the CloudLearn tier API.
 *
 * <p>All methods are blocking; for async use, wrap in your own executor.
 * No external deps beyond Jackson — uses {@link java.net.http.HttpClient}.
 *
 * <h2>Typical usage</h2>
 * <pre>{@code
 * TierClient client = TierClient.builder()
 *     .endpoint("http://192.168.252.7:9000")
 *     .build();
 *
 * TierStatus status = client.getStatus();
 *
 * // Wrap a call so tier denials become a soft handler instead of an exception:
 * client.withFallback(
 *     () -> { eb.putEvents(...); return null; },
 *     err -> log.warn("EventBridge limited; upgrade to {}: {}",
 *                      err.upgradeTo(), err.getMessage())
 * );
 *
 * // Sign up at a new tier
 * client.signup(SignupRequest.builder("dev@example.com")
 *         .tier("developer").period("annual").build());
 * }</pre>
 */
public class TierClient {

    private static final ObjectMapper M = new ObjectMapper();

    private final URI endpoint;
    private final HttpClient http;
    private final Duration timeout;

    private TierClient(URI endpoint, Duration timeout) {
        this.endpoint = endpoint;
        this.http = HttpClient.newBuilder().connectTimeout(timeout).build();
        this.timeout = timeout;
    }

    // ---- builder --------------------------------------------------------
    public static class Builder {
        private String endpoint = "http://127.0.0.1:9000";
        private Duration timeout = Duration.ofSeconds(10);
        public Builder endpoint(String url) { this.endpoint = url; return this; }
        public Builder timeout(Duration d)  { this.timeout = d;   return this; }
        public TierClient build()           { return new TierClient(URI.create(endpoint), timeout); }
    }
    public static Builder builder() { return new Builder(); }

    // ---- core API -------------------------------------------------------

    /** GET /api/license/status → current active tier + license + tenant view. */
    public TierStatus getStatus() {
        var resp = send("GET", "/api/license/status", null);
        try {
            return M.readValue(resp.body(), TierStatus.class);
        } catch (Exception e) {
            throw new RuntimeException("Failed to parse /api/license/status: " + e.getMessage(), e);
        }
    }

    /** GET /api/runtime/tier → full policy table for ALL tiers + active. */
    public Map<String, Object> getRuntimeTier() {
        var resp = send("GET", "/api/runtime/tier", null);
        try {
            return M.readValue(resp.body(), Map.class);
        } catch (Exception e) {
            throw new RuntimeException("Failed to parse /api/runtime/tier: " + e.getMessage(), e);
        }
    }

    /** POST /api/license/signup → activate a new tier. */
    public Map<String, Object> signup(SignupRequest request) {
        try {
            String body = M.writeValueAsString(request.build());
            var resp = send("POST", "/api/license/signup", body);
            return M.readValue(resp.body(), Map.class);
        } catch (TierLimitException tle) {
            throw tle;
        } catch (Exception e) {
            throw new RuntimeException("signup failed: " + e.getMessage(), e);
        }
    }

    /** POST /api/license/switch-cloud → Student tier primary_cloud change (1/year). */
    public Map<String, Object> switchPrimaryCloud(String newCloud) {
        try {
            String body = M.writeValueAsString(Map.of("primary_cloud", newCloud));
            var resp = send("POST", "/api/license/switch-cloud", body);
            return M.readValue(resp.body(), Map.class);
        } catch (TierLimitException tle) {
            throw tle;
        } catch (Exception e) {
            throw new RuntimeException("switch-cloud failed: " + e.getMessage(), e);
        }
    }

    // ---- fallback wrapper ----------------------------------------------

    /**
     * Run {@code op}; if it throws a {@link TierLimitException} (or any
     * exception {@link TierLimitException#isTierLimit} recognizes), invoke
     * {@code onLimit} with a synthetic TierLimitException and swallow the
     * error. Use this around best-effort calls (eventing, optional sinks)
     * where tier denials shouldn't break the broader operation.
     *
     * <pre>{@code
     * client.withFallback(
     *     () -> { eb.putEvents(...); return null; },
     *     err -> log.warn("EventBridge denied: {}", err.upgradeTo())
     * );
     * }</pre>
     */
    public <T> T withFallback(Supplier<T> op, Consumer<TierLimitException> onLimit) {
        try {
            return op.get();
        } catch (Throwable t) {
            if (TierLimitException.isTierLimit(t)) {
                TierLimitException tle = t instanceof TierLimitException
                        ? (TierLimitException) t
                        : new RuntimeTierLimitException(t);
                onLimit.accept(tle);
                return null;
            }
            if (t instanceof RuntimeException) throw (RuntimeException) t;
            throw new RuntimeException(t);
        }
    }

    /** void variant for ops with no return value. */
    public void withFallback(Runnable op, Consumer<TierLimitException> onLimit) {
        withFallback(() -> { op.run(); return null; }, onLimit);
    }

    // ---- internal -------------------------------------------------------

    private HttpResponse<String> send(String method, String path, String body) {
        HttpRequest.Builder b = HttpRequest.newBuilder()
                .uri(URI.create(endpoint + path))
                .timeout(timeout);
        if (body != null) {
            b.method(method, HttpRequest.BodyPublishers.ofString(body))
             .header("Content-Type", "application/json");
        } else {
            b.method(method, HttpRequest.BodyPublishers.noBody());
        }
        try {
            HttpResponse<String> resp = http.send(b.build(), HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() == 403 || resp.statusCode() == 429 || resp.statusCode() == 400) {
                TierLimitException tle = TierLimitException.fromResponseBody(resp.body());
                if (tle != null) throw tle;
            }
            if (resp.statusCode() >= 400) {
                throw new RuntimeException("HTTP " + resp.statusCode() + ": " + resp.body());
            }
            return resp;
        } catch (TierLimitException tle) {
            throw tle;
        } catch (Exception e) {
            throw new RuntimeException(method + " " + path + " failed: " + e.getMessage(), e);
        }
    }

    /** Synthetic wrapper when a non-TierLimitException is recognized via heuristic. */
    private static class RuntimeTierLimitException extends TierLimitException {
        RuntimeTierLimitException(Throwable cause) {
            super(cause.getMessage(), "tier_inferred", "", "", "", null);
            initCause(cause);
        }
    }
}
