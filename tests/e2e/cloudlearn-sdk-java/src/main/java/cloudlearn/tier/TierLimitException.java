package cloudlearn.tier;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Thrown when the simulator returns a 403 with a {@code tier_*} code.
 * The structured response body is exposed via getters so callers can
 * decide what UI to surface (upgrade modal, retry-on-Max, etc.).
 *
 * Body shape (matches the simulator's 403 contract):
 * <pre>
 * {"error": {
 *   "ok": false,
 *   "code": "tier_service_locked"     // OR tier_quantity_limit / tier_storage_limit
 *                                     //    tier_provider_locked / tier_max_spaces
 *                                     //    tier_feature_locked
 *   "reason": "human-readable why",
 *   "upgrade_to": "max",
 *   "active_tier": "free",
 *   "docs": "https://..."
 * }}
 * </pre>
 */
public class TierLimitException extends RuntimeException {

    private static final ObjectMapper M = new ObjectMapper();

    private final String code;
    private final String upgradeTo;
    private final String activeTier;
    private final String docsUrl;
    private final JsonNode raw;

    // Package-private so TierClient's RuntimeTierLimitException subclass can call super().
    TierLimitException(String message, String code, String upgradeTo,
                       String activeTier, String docsUrl, JsonNode raw) {
        super(message);
        this.code = code;
        this.upgradeTo = upgradeTo;
        this.activeTier = activeTier;
        this.docsUrl = docsUrl;
        this.raw = raw;
    }

    public String code()       { return code; }
    public String upgradeTo()  { return upgradeTo; }
    public String activeTier() { return activeTier; }
    public String docsUrl()    { return docsUrl; }
    public JsonNode raw()      { return raw; }

    /**
     * Heuristic: was this throwable (or any cause in its chain) a tier-limit
     * denial? Works against:
     *   - direct TierLimitException
     *   - software.amazon.awssdk SDK exceptions whose getMessage() includes "tier_"
     *   - Spring HttpClientErrorException with body containing tier_*
     *   - any RuntimeException whose message contains a known tier code
     */
    public static boolean isTierLimit(Throwable t) {
        while (t != null) {
            if (t instanceof TierLimitException) return true;
            String msg = String.valueOf(t.getMessage()).toLowerCase();
            if (msg.contains("tier_service_locked")
                    || msg.contains("tier_quantity_limit")
                    || msg.contains("tier_storage_limit")
                    || msg.contains("tier_provider_locked")
                    || msg.contains("tier_max_spaces")
                    || msg.contains("tier_feature_locked")
                    || msg.contains("x-cloudlearn-tier-denied")) return true;
            t = t.getCause();
        }
        return false;
    }

    /**
     * Parse a 403 JSON body into a TierLimitException, or null if it doesn't
     * match the structured shape (caller should treat as a non-tier 403).
     */
    public static TierLimitException fromResponseBody(String body) {
        if (body == null || body.isEmpty()) return null;
        try {
            JsonNode root = M.readTree(body);
            JsonNode err = root.path("error");
            if (err.isMissingNode() || !err.path("ok").isBoolean() || err.path("ok").asBoolean()) {
                // /api/license/* uses {"detail":{...}} not {"error":{...}}
                err = root.path("detail");
                if (err.isMissingNode()) return null;
            }
            String code = err.path("code").asText("");
            if (!code.startsWith("tier_")
                    && !code.equals("primary_cloud_required")
                    && !code.equals("min_seats_required")
                    && !code.equals("rate_limited")) {
                return null;
            }
            return new TierLimitException(
                    err.path("reason").asText("tier limit reached"),
                    code,
                    err.path("upgrade_to").asText(""),
                    err.path("active_tier").asText(""),
                    err.path("docs").asText(""),
                    err
            );
        } catch (Exception e) {
            return null;
        }
    }
}
