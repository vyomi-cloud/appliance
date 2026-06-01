package cloudlearn.tier;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;

/**
 * Snapshot of the active tier + license + tenant view.
 * Mirrors the response shape of {@code GET /api/license/status}.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record TierStatus(
        @JsonProperty("active_tier") String activeTier,
        @JsonProperty("primary_cloud") String primaryCloud,
        @JsonProperty("period") String period,
        @JsonProperty("seats") int seats,
        @JsonProperty("expires_at") String expiresAt,
        @JsonProperty("grace_until") String graceUntil,
        @JsonProperty("days_until_expiry") Integer daysUntilExpiry,
        @JsonProperty("in_grace_period") boolean inGracePeriod,
        @JsonProperty("price_inr_monthly") Integer priceInrMonthly,
        @JsonProperty("price_inr_annual") Integer priceInrAnnual,
        @JsonProperty("currency") String currency,
        @JsonProperty("currency_symbol") String currencySymbol,
        @JsonProperty("license") Map<String, Object> license
) {
    /** True if the license has expired AND the grace window is over. */
    public boolean isExpired() {
        if (daysUntilExpiry == null) return false;
        return daysUntilExpiry == 0 && !inGracePeriod;
    }
}
