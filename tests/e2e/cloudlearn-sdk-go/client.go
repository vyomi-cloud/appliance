package tier

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Client is the tier-API client. Construct with NewClient.
type Client struct {
	endpoint string
	http     *http.Client
}

// NewClient returns a Client pointing at the simulator base URL
// (e.g. http://192.168.252.7:9000). If endpoint is empty, falls back to
// http://127.0.0.1:9000.
func NewClient(endpoint string) *Client {
	if endpoint == "" {
		endpoint = "http://127.0.0.1:9000"
	}
	return &Client{
		endpoint: endpoint,
		http:     &http.Client{Timeout: 10 * time.Second},
	}
}

// WithTimeout returns a copy of the client with the given request timeout.
func (c *Client) WithTimeout(d time.Duration) *Client {
	cp := *c
	cp.http = &http.Client{Timeout: d}
	return &cp
}

// Status returns the active tier + license + tenant view.
func (c *Client) Status(ctx context.Context) (*Status, error) {
	body, err := c.do(ctx, "GET", "/api/license/status", nil)
	if err != nil {
		return nil, err
	}
	var s Status
	if err := json.Unmarshal(body, &s); err != nil {
		return nil, fmt.Errorf("parse /api/license/status: %w", err)
	}
	return &s, nil
}

// RuntimeTier returns the full per-tier policy table (all 4 tiers + active).
// Returned as a generic map since the policy shape is large + best read by
// the caller's pricing page.
func (c *Client) RuntimeTier(ctx context.Context) (map[string]interface{}, error) {
	body, err := c.do(ctx, "GET", "/api/runtime/tier", nil)
	if err != nil {
		return nil, err
	}
	var m map[string]interface{}
	if err := json.Unmarshal(body, &m); err != nil {
		return nil, fmt.Errorf("parse /api/runtime/tier: %w", err)
	}
	return m, nil
}

// Signup activates a new tier. Returns the simulator's license payload
// (which includes the signed JWT under "token"). Returns *LimitError on
// 400/403 (e.g. Student without primary_cloud, Enterprise <10 seats).
func (c *Client) Signup(ctx context.Context, req SignupRequest) (map[string]interface{}, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	respBody, err := c.do(ctx, "POST", "/api/license/signup", body)
	if err != nil {
		return nil, err
	}
	var m map[string]interface{}
	if err := json.Unmarshal(respBody, &m); err != nil {
		return nil, fmt.Errorf("parse /api/license/signup response: %w", err)
	}
	return m, nil
}

// SwitchPrimaryCloud is a Student-tier-only call (1/year rate limit).
// Returns *LimitError on rate_limited (429) or not_applicable (400 for
// non-Student tiers).
func (c *Client) SwitchPrimaryCloud(ctx context.Context, newCloud string) (map[string]interface{}, error) {
	body, err := json.Marshal(map[string]string{"primary_cloud": newCloud})
	if err != nil {
		return nil, err
	}
	respBody, err := c.do(ctx, "POST", "/api/license/switch-cloud", body)
	if err != nil {
		return nil, err
	}
	var m map[string]interface{}
	if err := json.Unmarshal(respBody, &m); err != nil {
		return nil, fmt.Errorf("parse switch-cloud response: %w", err)
	}
	return m, nil
}

// do is the shared HTTP roundtripper. Maps structured 4xx bodies → *LimitError.
func (c *Client) do(ctx context.Context, method, path string, body []byte) ([]byte, error) {
	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.endpoint+path, reader)
	if err != nil {
		return nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("%s %s: %w", method, path, err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)

	if resp.StatusCode == 400 || resp.StatusCode == 403 || resp.StatusCode == 429 {
		if tle := parseLimitErrorBody(raw); tle != nil {
			return nil, tle
		}
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("%s %s: HTTP %d: %s", method, path, resp.StatusCode, string(raw))
	}
	return raw, nil
}
