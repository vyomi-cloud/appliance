package cloudlearn.tier;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Builder for {@code POST /api/license/signup}. Fluent style:
 *
 * <pre>{@code
 * SignupRequest req = SignupRequest.builder("alice@example.com")
 *     .tier("student")
 *     .primaryCloud("aws")
 *     .period("annual")
 *     .build();
 * client.signup(req);
 * }</pre>
 */
public class SignupRequest {
    private String user;
    private final String email;
    private String tier;
    private String period;
    private String primaryCloud;
    private int seats;
    private String deviceId;

    private SignupRequest(String email) {
        this.email = email;
        this.user = "guest";
        this.tier = "free";
        this.period = "monthly";
        this.primaryCloud = "";
        this.seats = 1;
        this.deviceId = "";
    }

    public static SignupRequest builder(String email) {
        if (email == null || email.isEmpty()) {
            throw new IllegalArgumentException("email is required");
        }
        return new SignupRequest(email);
    }

    public SignupRequest user(String v)         { this.user = v; return this; }
    public SignupRequest tier(String v)         { this.tier = v; return this; }
    public SignupRequest period(String v)       { this.period = v; return this; }
    public SignupRequest primaryCloud(String v) { this.primaryCloud = v; return this; }
    public SignupRequest seats(int v)           { this.seats = v; return this; }
    public SignupRequest deviceId(String v)     { this.deviceId = v; return this; }

    public Map<String, Object> build() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("user", user);
        m.put("email", email);
        m.put("tier", tier);
        m.put("period", period);
        m.put("primary_cloud", primaryCloud);
        m.put("seats", seats);
        m.put("device_id", deviceId);
        return m;
    }
}
