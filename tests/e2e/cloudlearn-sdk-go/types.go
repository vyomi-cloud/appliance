// Package tier provides a Go client for the CloudLearn simulator's tier API.
// Companion to cloudlearn-tier-sdk-java with the same shape.
//
// Wraps:
//
//	GET  /api/license/status      → Status
//	GET  /api/runtime/tier        → RuntimeTier (full policy table)
//	POST /api/license/signup      → activate a tier
//	POST /api/license/switch-cloud → Student primary_cloud change
//
// Plus a WithFallback helper for treating tier denials as soft enhancements
// rather than hard failures.
package tier

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

// Status is the response shape of GET /api/license/status.
type Status struct {
	ActiveTier       string                 `json:"active_tier"`
	PrimaryCloud     string                 `json:"primary_cloud"`
	Period           string                 `json:"period"`
	Seats            int                    `json:"seats"`
	ExpiresAt        string                 `json:"expires_at"`
	GraceUntil       string                 `json:"grace_until"`
	DaysUntilExpiry  *int                   `json:"days_until_expiry"`
	InGracePeriod    bool                   `json:"in_grace_period"`
	PriceInrMonthly  *int                   `json:"price_inr_monthly"`
	PriceInrAnnual   *int                   `json:"price_inr_annual"`
	Currency         string                 `json:"currency"`
	CurrencySymbol   string                 `json:"currency_symbol"`
	License          map[string]interface{} `json:"license"`
}

// IsExpired returns true if the license expired and the grace window is over.
func (s *Status) IsExpired() bool {
	if s.DaysUntilExpiry == nil {
		return false
	}
	return *s.DaysUntilExpiry == 0 && !s.InGracePeriod
}

// SignupRequest is the POST /api/license/signup body. Use SignupBuilder for
// a fluent constructor.
type SignupRequest struct {
	User         string `json:"user"`
	Email        string `json:"email"`
	Tier         string `json:"tier"`
	Period       string `json:"period"`
	PrimaryCloud string `json:"primary_cloud"`
	Seats        int    `json:"seats"`
	DeviceID     string `json:"device_id"`
}

// SignupBuilder is a fluent constructor for SignupRequest.
//
//	req := tier.NewSignup("dev@example.com").
//	    Tier("developer").
//	    Period("annual").
//	    Build()
type SignupBuilder struct{ r SignupRequest }

func NewSignup(email string) *SignupBuilder {
	return &SignupBuilder{r: SignupRequest{
		User: "guest", Email: email, Tier: "free", Period: "monthly", Seats: 1,
	}}
}
func (b *SignupBuilder) User(v string)         *SignupBuilder { b.r.User = v;         return b }
func (b *SignupBuilder) Tier(v string)         *SignupBuilder { b.r.Tier = v;         return b }
func (b *SignupBuilder) Period(v string)       *SignupBuilder { b.r.Period = v;       return b }
func (b *SignupBuilder) PrimaryCloud(v string) *SignupBuilder { b.r.PrimaryCloud = v; return b }
func (b *SignupBuilder) Seats(v int)           *SignupBuilder { b.r.Seats = v;        return b }
func (b *SignupBuilder) DeviceID(v string)     *SignupBuilder { b.r.DeviceID = v;     return b }
func (b *SignupBuilder) Build() SignupRequest  { return b.r }

// LimitError is returned for 403/429 responses with a structured
// tier_*-coded body (or 400 primary_cloud_required / min_seats_required /
// rate_limited from the signup/switch endpoints).
type LimitError struct {
	Code       string                 `json:"code"`
	Reason     string                 `json:"reason"`
	UpgradeTo  string                 `json:"upgrade_to"`
	ActiveTier string                 `json:"active_tier"`
	DocsURL    string                 `json:"docs"`
	Raw        map[string]interface{} `json:"-"`
}

func (e *LimitError) Error() string {
	return fmt.Sprintf("tier limit (%s): %s; upgrade_to=%s", e.Code, e.Reason, e.UpgradeTo)
}

// AsLimitError unwraps an error to a *LimitError if it (or any wrapped
// error) was one. Use this in your error-handling switch:
//
//	if tle, ok := tier.AsLimitError(err); ok {
//	    showUpgradePrompt(tle.UpgradeTo)
//	    return
//	}
func AsLimitError(err error) (*LimitError, bool) {
	var tle *LimitError
	if errors.As(err, &tle) {
		return tle, true
	}
	// Heuristic for SDK exceptions that don't carry the typed body but
	// include the code in their message string (boto3/aws-sdk-go-v2 wrapping).
	if err != nil {
		msg := strings.ToLower(err.Error())
		if strings.Contains(msg, "tier_") || strings.Contains(msg, "x-cloudlearn-tier-denied") {
			return &LimitError{
				Code:   "tier_inferred",
				Reason: err.Error(),
			}, true
		}
	}
	return nil, false
}

// parseLimitErrorBody parses an HTTP response body into a *LimitError, or
// returns nil if the body isn't a structured tier-limit response.
func parseLimitErrorBody(body []byte) *LimitError {
	if len(body) == 0 {
		return nil
	}
	var raw map[string]interface{}
	if err := json.Unmarshal(body, &raw); err != nil {
		return nil
	}
	inner, ok := raw["error"].(map[string]interface{})
	if !ok {
		// /api/license/* uses {"detail":{...}}
		inner, ok = raw["detail"].(map[string]interface{})
		if !ok {
			return nil
		}
	}
	code, _ := inner["code"].(string)
	known := strings.HasPrefix(code, "tier_") ||
		code == "primary_cloud_required" ||
		code == "min_seats_required" ||
		code == "rate_limited"
	if !known {
		return nil
	}
	tle := &LimitError{Code: code, Raw: inner}
	if v, ok := inner["reason"].(string); ok      { tle.Reason = v     }
	if v, ok := inner["upgrade_to"].(string); ok  { tle.UpgradeTo = v  }
	if v, ok := inner["active_tier"].(string); ok { tle.ActiveTier = v }
	if v, ok := inner["docs"].(string); ok        { tle.DocsURL = v    }
	return tle
}
