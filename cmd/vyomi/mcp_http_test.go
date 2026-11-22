package main

// The hosted transport: the path set (D-I6), the HTTP contract from plan §6, the rate limit (D-I4) and the log
// line (O-D4).

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"syscall"
	"testing"
	"time"
)

func testHTTPServer(t *testing.T) (*mcpHTTPServer, *bytes.Buffer) {
	t.Helper()
	t.Setenv("VYOMI_MCP_ALLOWED_ORIGINS", "")
	logs := &bytes.Buffer{}
	return newMCPHTTPServer(testHostedServer(t), logs), logs
}

type httpOpt func(*http.Request)

func withHeader(k, v string) httpOpt { return func(r *http.Request) { r.Header.Set(k, v) } }
func withRemote(addr string) httpOpt { return func(r *http.Request) { r.RemoteAddr = addr } }

func do(t *testing.T, h *mcpHTTPServer, method, path, body string, opts ...httpOpt) *httptest.ResponseRecorder {
	t.Helper()
	var r *http.Request
	if body == "" {
		r = httptest.NewRequest(method, "http://vyomi.cloud/placeholder", nil)
	} else {
		r = httptest.NewRequest(method, "http://vyomi.cloud/placeholder", strings.NewReader(body))
	}
	// Set the path directly, so "" (what App Platform can forward after trimming /mcp) is testable too.
	r.URL.Path = path
	r.RequestURI = path
	r.RemoteAddr = "203.0.113.9:54321"
	for _, o := range opts {
		o(r)
	}
	w := httptest.NewRecorder()
	h.handler().ServeHTTP(w, r)
	return w
}

func rpc(t *testing.T, w *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &m); err != nil {
		t.Fatalf("response body is not JSON (%d): %q", w.Code, w.Body.String())
	}
	return m
}

const initBody = `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}`

// D-I6: "/", "", "/mcp" and "/mcp/" all take POST, and none of them redirects (a 301/308 would turn the POST
// into a GET and break every MCP client).
func TestHostedHTTPPathsAcceptPostWithoutRedirect(t *testing.T) {
	h, _ := testHTTPServer(t)
	for _, path := range []string{"", "/", "/mcp", "/mcp/"} {
		w := do(t, h, http.MethodPost, path, initBody)
		if w.Code != http.StatusOK {
			t.Errorf("POST %q: status %d, want 200 (body %s)", path, w.Code, w.Body.String())
		}
		if loc := w.Header().Get("Location"); loc != "" {
			t.Errorf("POST %q redirected to %q; a redirect breaks POST", path, loc)
		}
		if res, ok := rpc(t, w)["result"].(map[string]any); !ok || res["protocolVersion"] != "2025-06-18" {
			t.Errorf("POST %q did not initialize: %s", path, w.Body.String())
		}
	}
	for _, path := range []string{"/healthz", "/mcp/healthz"} {
		w := do(t, h, http.MethodGet, path, "")
		if w.Code != http.StatusOK {
			t.Errorf("GET %q: status %d, want 200", path, w.Code)
		}
		m := rpc(t, w)
		if m["ok"] != true || m["version"] != loadedVersion(t) {
			t.Errorf("GET %q: %s", path, w.Body.String())
		}
	}
	if w := do(t, h, http.MethodGet, "/nope", ""); w.Code != http.StatusNotFound {
		t.Errorf("GET /nope: status %d, want 404", w.Code)
	}
	if w := do(t, h, http.MethodPost, "/healthz", initBody); w.Code != http.StatusMethodNotAllowed {
		t.Errorf("POST /healthz: status %d, want 405", w.Code)
	}
}

func loadedVersion(t *testing.T) string {
	t.Helper()
	m, err := loadMCPMatrix()
	if err != nil {
		t.Fatal(err)
	}
	return m.ApplianceVersion
}

func TestHostedHTTPMethodsOtherThanPost(t *testing.T) {
	h, _ := testHTTPServer(t)
	for _, method := range []string{http.MethodGet, http.MethodDelete, http.MethodPut, http.MethodPatch} {
		w := do(t, h, method, "/mcp", "")
		if w.Code != http.StatusMethodNotAllowed {
			t.Errorf("%s /mcp: status %d, want 405", method, w.Code)
		}
		if w.Header().Get("Allow") != "POST" {
			t.Errorf("%s /mcp: Allow = %q, want POST", method, w.Header().Get("Allow"))
		}
		if rpc(t, w)["error"] == nil {
			t.Errorf("%s /mcp: the body should carry a JSON-RPC error saying why", method)
		}
	}
}

func TestHostedHTTPInitializeNegotiatesAndListsTools(t *testing.T) {
	h, _ := testHTTPServer(t)
	// A version we support is echoed; one we do not falls back to ours.
	for req, want := range map[string]string{"2025-03-26": "2025-03-26", "2024-11-05": "2024-11-05", "1999-01-01": mcpProtocolVersions[0]} {
		body := fmt.Sprintf(`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":%q}}`, req)
		res := rpc(t, do(t, h, http.MethodPost, "/mcp", body))["result"].(map[string]any)
		if res["protocolVersion"] != want {
			t.Errorf("initialize %s -> %v, want %s", req, res["protocolVersion"], want)
		}
	}
	w := do(t, h, http.MethodPost, "/mcp", `{"jsonrpc":"2.0","id":2,"method":"tools/list"}`)
	tools := rpc(t, w)["result"].(map[string]any)["tools"].([]any)
	if len(tools) != len(hostedPin) {
		t.Fatalf("tools/list returned %d tools, want %d", len(tools), len(hostedPin))
	}
	w = do(t, h, http.MethodPost, "/mcp", `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"check_capability","arguments":{"query":"bucket versioning"}}}`)
	res := rpc(t, w)["result"].(map[string]any)
	if res["isError"] == true {
		t.Fatalf("tools/call failed: %s", w.Body.String())
	}
	if w.Header().Get("Content-Type") != "application/json" {
		t.Errorf("Content-Type = %q, want application/json", w.Header().Get("Content-Type"))
	}
}

func TestHostedHTTPNotificationGets202WithEmptyBody(t *testing.T) {
	h, _ := testHTTPServer(t)
	w := do(t, h, http.MethodPost, "/mcp", `{"jsonrpc":"2.0","method":"notifications/initialized"}`)
	if w.Code != http.StatusAccepted {
		t.Errorf("notification: status %d, want 202", w.Code)
	}
	if w.Body.Len() != 0 {
		t.Errorf("notification: body %q, want empty", w.Body.String())
	}
}

// D-I5: batching was removed from MCP; stdio still accepts it (older clients), HTTP does not.
func TestHostedHTTPRejectsBatchesAndBadJSON(t *testing.T) {
	h, _ := testHTTPServer(t)
	w := do(t, h, http.MethodPost, "/mcp", `[{"jsonrpc":"2.0","id":1,"method":"tools/list"}]`)
	if w.Code != http.StatusBadRequest {
		t.Errorf("batch: status %d, want 400", w.Code)
	}
	if e, _ := rpc(t, w)["error"].(map[string]any); e == nil || !strings.Contains(fmt.Sprint(e["message"]), "batch") {
		t.Errorf("batch: the error should say batches are not supported: %s", w.Body.String())
	}
	for _, body := range []string{`{"jsonrpc":`, `not json at all`, `   `} {
		w := do(t, h, http.MethodPost, "/mcp", body)
		if w.Code != http.StatusBadRequest {
			t.Errorf("body %q: status %d, want 400", body, w.Code)
		}
		if e, _ := rpc(t, w)["error"].(map[string]any); e == nil || e["code"] != float64(rpcParseError) {
			t.Errorf("body %q: want a JSON-RPC parse error, got %s", body, w.Body.String())
		}
	}
	// stdio still accepts a batch: local mode is unchanged (rule 8).
	l, out := testMCPServer(t)
	l.handleLine([]byte(`[{"jsonrpc":"2.0","id":1,"method":"tools/list"}]`))
	if !strings.HasPrefix(strings.TrimSpace(out.String()), "[") {
		t.Errorf("stdio should still answer a batch with a batch, got %q", out.String())
	}
}

func TestHostedHTTPBodyLimit(t *testing.T) {
	h, _ := testHTTPServer(t)
	big := fmt.Sprintf(`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"check_capability","arguments":{"query":%q}}}`,
		strings.Repeat("x", mcpHTTPMaxBody))
	w := do(t, h, http.MethodPost, "/mcp", big)
	if w.Code != http.StatusRequestEntityTooLarge {
		t.Errorf("oversize body: status %d, want 413", w.Code)
	}
	// Same, with no Content-Length (a chunked request), so the limit cannot be bypassed.
	r := httptest.NewRequest(http.MethodPost, "http://vyomi.cloud/mcp", strings.NewReader(big))
	r.ContentLength = -1
	rec := httptest.NewRecorder()
	h.handler().ServeHTTP(rec, r)
	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Errorf("oversize chunked body: status %d, want 413", rec.Code)
	}
	// Just under the limit is served.
	ok := fmt.Sprintf(`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"check_capability","arguments":{"query":%q}}}`,
		strings.Repeat("x", 1000))
	if w := do(t, h, http.MethodPost, "/mcp", ok); w.Code != http.StatusOK {
		t.Errorf("1 KiB body: status %d, want 200", w.Code)
	}
}

func TestHostedHTTPOriginAndProtocolVersionHeaders(t *testing.T) {
	h, _ := testHTTPServer(t)
	for _, origin := range []string{"https://vyomi.cloud", "https://www.vyomi.cloud", "http://localhost:6274", "http://127.0.0.1:6274", "null"} {
		if w := do(t, h, http.MethodPost, "/mcp", initBody, withHeader("Origin", origin)); w.Code != http.StatusOK {
			t.Errorf("Origin %s: status %d, want 200", origin, w.Code)
		}
	}
	for _, origin := range []string{"https://evil.example", "https://vyomi.cloud.evil.example", "http://vyomi-cloud.example"} {
		if w := do(t, h, http.MethodPost, "/mcp", initBody, withHeader("Origin", origin)); w.Code != http.StatusForbidden {
			t.Errorf("Origin %s: status %d, want 403", origin, w.Code)
		}
	}
	// No Origin at all is the normal case for a server-to-server client.
	if w := do(t, h, http.MethodPost, "/mcp", initBody); w.Code != http.StatusOK {
		t.Errorf("no Origin: status %d, want 200", w.Code)
	}
	// An operator can add origins.
	t.Setenv("VYOMI_MCP_ALLOWED_ORIGINS", "https://chat.example, https://other.example")
	h2 := newMCPHTTPServer(testHostedServer(t), io.Discard)
	if w := do(t, h2, http.MethodPost, "/mcp", initBody, withHeader("Origin", "https://chat.example")); w.Code != http.StatusOK {
		t.Errorf("allow-listed origin: status %d, want 200", w.Code)
	}
	if w := do(t, h2, http.MethodPost, "/mcp", initBody, withHeader("Origin", "https://evil.example")); w.Code != http.StatusForbidden {
		t.Errorf("other origin with an allowlist set: status %d, want 403", w.Code)
	}

	for _, v := range mcpProtocolVersions {
		if w := do(t, h, http.MethodPost, "/mcp", initBody, withHeader("MCP-Protocol-Version", v)); w.Code != http.StatusOK {
			t.Errorf("MCP-Protocol-Version %s: status %d, want 200", v, w.Code)
		}
	}
	w := do(t, h, http.MethodPost, "/mcp", initBody, withHeader("MCP-Protocol-Version", "2099-01-01"))
	if w.Code != http.StatusBadRequest {
		t.Errorf("unknown MCP-Protocol-Version: status %d, want 400", w.Code)
	}
	if e, _ := rpc(t, w)["error"].(map[string]any); e == nil || !strings.Contains(fmt.Sprint(e["message"]), mcpProtocolVersions[0]) {
		t.Errorf("the error should name the versions we speak: %s", w.Body.String())
	}
}

// O-D4: the log carries no argument values and no client address.
func TestHostedHTTPLogHasNoArgumentsOrAddresses(t *testing.T) {
	h, logs := testHTTPServer(t)
	secret := "zqxjvbnmsecretqueryvalue"
	body := fmt.Sprintf(`{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"check_capability","arguments":{"query":%q}}}`, secret)
	do(t, h, http.MethodPost, "/mcp", body,
		withRemote("198.51.100.77:4444"), withHeader("X-Forwarded-For", "198.51.100.23, 10.0.0.1"), withHeader("User-Agent", "curl/8.4.0"))
	do(t, h, http.MethodGet, "/healthz", "", withRemote("198.51.100.77:4444"))
	line := logs.String()
	for _, banned := range []string{secret, "198.51.100.77", "198.51.100.23", "10.0.0.1", "4444", "curl/8.4.0", "arguments"} {
		if strings.Contains(line, banned) {
			t.Errorf("the request log carries %q:\n%s", banned, line)
		}
	}
	var first mcpLogLine
	if err := json.Unmarshal([]byte(strings.SplitN(strings.TrimSpace(line), "\n", 2)[0]), &first); err != nil {
		t.Fatalf("log line is not JSON: %q", line)
	}
	if first.Method != "tools/call" || first.Tool != "check_capability" || first.Status != 200 || first.Path != "/mcp" || first.HTTPMethod != "POST" {
		t.Errorf("log line = %+v", first)
	}
	if first.Bytes <= 0 || first.Time == "" {
		t.Errorf("log line should carry a byte count and a timestamp: %+v", first)
	}
	// An unknown path is logged as "other", so a scanner's URL never lands in the log.
	logs.Reset()
	do(t, h, http.MethodGet, "/.env.backup", "")
	if !strings.Contains(logs.String(), `"path":"other"`) || strings.Contains(logs.String(), ".env.backup") {
		t.Errorf("unknown paths must be logged as other: %s", logs.String())
	}
}

func TestHostedHTTPRateLimit(t *testing.T) {
	h, _ := testHTTPServer(t)
	now := time.Now()
	h.limiter.now = func() time.Time { return now }
	var limited *httptest.ResponseRecorder
	for i := 0; i < rateLimitBurst+5; i++ {
		w := do(t, h, http.MethodPost, "/mcp", initBody, withRemote("198.51.100.5:1111"))
		if i < rateLimitBurst && w.Code != http.StatusOK {
			t.Fatalf("request %d of the burst: status %d, want 200", i+1, w.Code)
		}
		if w.Code == http.StatusTooManyRequests {
			limited = w
			break
		}
	}
	if limited == nil {
		t.Fatalf("the rate limit never triggered after %d requests from one address", rateLimitBurst+5)
	}
	if ra := limited.Header().Get("Retry-After"); ra == "" || ra == "0" {
		t.Errorf("429 without a usable Retry-After: %q", ra)
	}
	// Another client is unaffected...
	if w := do(t, h, http.MethodPost, "/mcp", initBody, withRemote("198.51.100.6:2222")); w.Code != http.StatusOK {
		t.Errorf("a different address: status %d, want 200", w.Code)
	}
	// ...and the first one recovers as its bucket refills.
	now = now.Add(time.Minute)
	if w := do(t, h, http.MethodPost, "/mcp", initBody, withRemote("198.51.100.5:1111")); w.Code != http.StatusOK {
		t.Errorf("after a minute: status %d, want 200", w.Code)
	}
	// Health checks are never rate limited (App Platform polls /healthz).
	for i := 0; i < rateLimitBurst*3; i++ {
		if w := do(t, h, http.MethodGet, "/healthz", "", withRemote("198.51.100.5:1111")); w.Code != http.StatusOK {
			t.Fatalf("health check %d: status %d, want 200", i+1, w.Code)
		}
	}
}

// The limiter stores a salted hash, never the address itself.
func TestRateLimiterKeysAreHashed(t *testing.T) {
	l := newRateLimiter()
	l.allow("198.51.100.5")
	for k := range l.keys {
		if fmt.Sprint(k) == "198.51.100.5" {
			t.Fatal("the limiter stored a raw address")
		}
	}
	if l.hash("198.51.100.5") == newRateLimiter().hash("198.51.100.5") {
		t.Error("two processes produced the same key for one address; the salt is not working")
	}
	if l.hash("198.51.100.5") != l.hash("198.51.100.5") {
		t.Error("the key is not stable within a process")
	}
}

// A panicking handler is answered with a 500 and never takes the process down.
func TestHostedHTTPRecoversFromPanic(t *testing.T) {
	h, logs := testHTTPServer(t)
	boom := &mcpTool{Name: "boom", Title: "boom", ReadOnly: true, Schema: obj(map[string]any{}),
		handler: func(json.RawMessage) (any, error) { panic("boom") }}
	h.srv.tools = append(h.srv.tools, boom)
	h.srv.index()
	stderr := os.Stderr
	r, wpipe, _ := os.Pipe()
	os.Stderr = wpipe
	w := do(t, h, http.MethodPost, "/mcp", `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"boom","arguments":{}}}`)
	os.Stderr = stderr
	wpipe.Close()
	noise, _ := io.ReadAll(r)
	if w.Code != http.StatusInternalServerError {
		t.Errorf("panicking tool: status %d, want 500", w.Code)
	}
	if rpc(t, w)["error"] == nil {
		t.Errorf("panicking tool: want a JSON-RPC error body, got %q", w.Body.String())
	}
	if !strings.Contains(string(noise), "recovered panic") {
		t.Errorf("the panic should be reported on stderr: %q", noise)
	}
	if !strings.Contains(logs.String(), `"status":500`) {
		t.Errorf("the panicking request should still be logged: %s", logs.String())
	}
	// The server keeps serving.
	if w := do(t, h, http.MethodPost, "/mcp", initBody); w.Code != http.StatusOK {
		t.Errorf("after a panic: status %d, want 200", w.Code)
	}
}

func TestHostedListenAddr(t *testing.T) {
	t.Setenv("PORT", "")
	for arg, want := range map[string]string{"": ":8080", ":9999": ":9999", "9999": ":9999", "127.0.0.1:9999": "127.0.0.1:9999"} {
		if got := hostedListenAddr(arg); got != want {
			t.Errorf("hostedListenAddr(%q) = %q, want %q", arg, got, want)
		}
	}
	t.Setenv("PORT", "8081")
	if got := hostedListenAddr(""); got != ":8081" {
		t.Errorf("hostedListenAddr with PORT=8081 = %q, want :8081", got)
	}
	if got := hostedListenAddr(":9999"); got != ":9999" {
		t.Errorf("--listen must win over PORT, got %q", got)
	}
}

// End to end over a real socket, including the graceful shutdown App Platform relies on (SIGTERM on every
// deploy): in-flight requests finish and serveHTTP returns cleanly.
func TestHostedHTTPServeAndGracefulShutdown(t *testing.T) {
	h, _ := testHTTPServer(t)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := ln.Addr().String()
	ln.Close()
	done := make(chan error, 1)
	go func() { done <- h.serveHTTP(addr) }()

	base := "http://" + addr
	deadline := time.Now().Add(5 * time.Second)
	for {
		resp, err := http.Get(base + "/healthz")
		if err == nil {
			resp.Body.Close()
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("the server never came up on %s: %v", addr, err)
		}
		time.Sleep(10 * time.Millisecond)
	}
	resp, err := http.Post(base+"/mcp", "application/json", strings.NewReader(initBody))
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK || !strings.Contains(string(body), `"protocolVersion"`) {
		t.Fatalf("POST /mcp over a socket: %d %s", resp.StatusCode, body)
	}
	// The client's URL keeps /mcp here; behind the portal route the prefix is trimmed and "/" serves the same.
	resp, err = http.Post(base+"/", "application/json", strings.NewReader(initBody))
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("POST / over a socket: %d", resp.StatusCode)
	}

	if err := syscall.Kill(os.Getpid(), syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("serveHTTP returned %v, want a clean shutdown", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("serveHTTP did not return after SIGTERM")
	}
	if _, err := http.Get(base + "/healthz"); err == nil {
		t.Error("the listener is still accepting connections after shutdown")
	}
}
