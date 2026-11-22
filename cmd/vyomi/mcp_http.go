package main

// Streamable HTTP transport for the hosted MCP server (`vyomi mcp --hosted`), served at https://vyomi.cloud/mcp.
//
// One endpoint: POST a JSON-RPC message, get `application/json` back. No server-sent events (no tool streams and
// no server-initiated calls), no session id, so the server is stateless and any instance answers any request.
// handleMessage is the same function the stdio server uses; only the transport differs.
//
// Paths (D-I6). Behind the portal's App Platform route the `/mcp` prefix is TRIMMED, so the server sees "/" (or
// ""); run locally or in Docker, the client's URL keeps /mcp. Both are served from one handler that switches on
// the path, never an http.ServeMux subtree pattern: ServeMux answers /mcp with a 301 to /mcp/, and a redirect
// turns a client's POST into a GET.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

const (
	mcpHTTPMaxBody     = 256 << 10        // 256 KiB (plan §4 rule 5); over it: 413
	mcpHTTPTimeout     = 10 * time.Second // per request
	mcpHTTPReadTimeout = 15 * time.Second
	mcpHTTPIdleTimeout = 60 * time.Second
	mcpHTTPShutdown    = 10 * time.Second // grace period on SIGTERM
)

// mcpHTTPServer is the hosted server's transport: the MCP server itself, the rate limiter and the request log.
type mcpHTTPServer struct {
	srv     *mcpServer
	limiter *rateLimiter
	logger  *mcpLogger
	origins []string // extra allowed browser origins (VYOMI_MCP_ALLOWED_ORIGINS)
}

func newMCPHTTPServer(s *mcpServer, logTo io.Writer) *mcpHTTPServer {
	h := &mcpHTTPServer{srv: s, limiter: newRateLimiter(), logger: newMCPLogger(logTo)}
	for _, o := range strings.Split(os.Getenv("VYOMI_MCP_ALLOWED_ORIGINS"), ",") {
		if o = strings.TrimSpace(o); o != "" {
			h.origins = append(h.origins, strings.ToLower(o))
		}
	}
	return h
}

// isRPCPath / isHealthPath: the exact paths served, with and without the /mcp prefix the router may have trimmed
// (D-I6). Nothing between them is ever redirected.
func isRPCPath(p string) bool {
	switch p {
	case "", "/", "/mcp", "/mcp/":
		return true
	}
	return false
}

func isHealthPath(p string) bool {
	switch p {
	case "/healthz", "/mcp/healthz":
		return true
	}
	return false
}

// runHostedMCP is `vyomi mcp --hosted`.
func runHostedMCP(listen string) int {
	s, err := newHostedMCPServer()
	if err != nil {
		fmt.Fprintln(os.Stderr, "vyomi mcp --hosted:", err)
		return 1
	}
	addr := hostedListenAddr(listen)
	h := newMCPHTTPServer(s, os.Stderr)
	names := make([]string, 0, len(s.tools))
	for _, t := range s.tools {
		names = append(names, t.Name)
	}
	fmt.Fprintf(os.Stderr, "vyomi mcp --hosted: serving MCP over HTTP on %s (knowledge from appliance v%s; %d read-only tools: %s)\n",
		addr, s.version, len(names), strings.Join(names, ", "))
	fmt.Fprintf(os.Stderr, "vyomi mcp --hosted: POST \"/\" or \"/mcp\" for JSON-RPC, GET /healthz for health. No outbound network, no file access.\n")
	if err := h.serveHTTP(addr); err != nil {
		fmt.Fprintln(os.Stderr, "vyomi mcp --hosted:", err)
		return 1
	}
	return 0
}

// hostedListenAddr: --listen, else :$PORT (App Platform sets PORT), else :8080.
func hostedListenAddr(listen string) string {
	if a := strings.TrimSpace(listen); a != "" {
		if !strings.Contains(a, ":") {
			return ":" + a
		}
		return a
	}
	if p := strings.TrimSpace(os.Getenv("PORT")); p != "" {
		if !strings.Contains(p, ":") {
			return ":" + p
		}
		return p
	}
	return ":8080"
}

// serveHTTP listens on addr until SIGINT/SIGTERM, then drains in-flight requests (App Platform sends SIGTERM on
// every deploy and scale event).
func (h *mcpHTTPServer) serveHTTP(addr string) error {
	srv := &http.Server{
		Addr:              addr,
		Handler:           h.handler(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       mcpHTTPReadTimeout,
		WriteTimeout:      mcpHTTPTimeout + 5*time.Second,
		IdleTimeout:       mcpHTTPIdleTimeout,
		MaxHeaderBytes:    1 << 16,
	}
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return err
	}
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(stop)
	errc := make(chan error, 1)
	go func() {
		if err := srv.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errc <- err
			return
		}
		errc <- nil
	}()
	select {
	case err := <-errc:
		return err
	case sig := <-stop:
		fmt.Fprintf(os.Stderr, "vyomi mcp --hosted: %v, draining for up to %s\n", sig, mcpHTTPShutdown)
		ctx, cancel := context.WithTimeout(context.Background(), mcpHTTPShutdown)
		defer cancel()
		if err := srv.Shutdown(ctx); err != nil {
			return err
		}
		return <-errc
	}
}

// handler wraps the request handler in the per-request timeout. The handler itself recovers from a panic, so a
// bug in one request can never take the process down or leak a stack trace to the caller.
func (h *mcpHTTPServer) handler() http.Handler {
	timeout, _ := json.Marshal(rpcResponse{JSONRPC: "2.0", ID: json.RawMessage("null"),
		Error: &rpcError{rpcInternalError, "the request took too long; try again"}})
	return http.TimeoutHandler(http.HandlerFunc(h.serve), mcpHTTPTimeout, string(timeout))
}

func (h *mcpHTTPServer) serve(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	rec := &responseRecorder{ResponseWriter: w, status: http.StatusOK}
	line := mcpLogLine{HTTPMethod: r.Method, Path: logPath(r.URL.Path)}
	defer func() {
		if v := recover(); v != nil {
			// No arguments and no address reach stderr (O-D4): only the panic value and where it happened.
			fmt.Fprintf(os.Stderr, "vyomi mcp --hosted: recovered panic on %s %s: %v\n", r.Method, logPath(r.URL.Path), v)
			if !rec.wrote {
				writeRPCError(rec, http.StatusInternalServerError, rpcInternalError, "internal error")
			}
		}
		line.Status = rec.status
		line.Bytes = rec.bytes
		line.MS = time.Since(start).Milliseconds()
		h.logger.log(line)
	}()
	h.route(rec, r, &line)
}

func (h *mcpHTTPServer) route(w *responseRecorder, r *http.Request, line *mcpLogLine) {
	switch {
	case isHealthPath(r.URL.Path):
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			methodNotAllowed(w, "GET")
			return
		}
		writeHTTPJSON(w, http.StatusOK, map[string]any{"ok": true, "version": h.srv.version, "tools": len(h.srv.tools)})
		return
	case !isRPCPath(r.URL.Path):
		writeHTTPJSON(w, http.StatusNotFound, map[string]any{
			"error": "not found. This is an MCP server: POST JSON-RPC to this origin's /mcp, or GET /mcp/healthz.",
		})
		return
	}

	// GET would be the SSE stream of a streaming server, DELETE would end a session: this server has neither
	// (stateless, JSON responses only), so both are 405 with Allow: POST, as the MCP spec expects.
	if r.Method != http.MethodPost {
		methodNotAllowed(w, "POST")
		return
	}
	if !h.originAllowed(r.Header.Get("Origin")) {
		writeRPCError(w, http.StatusForbidden, rpcInvalidRequest, "this origin is not allowed to call the Vyomi MCP server from a browser")
		return
	}
	if v := strings.TrimSpace(r.Header.Get("MCP-Protocol-Version")); v != "" && !contains(mcpProtocolVersions, v) {
		writeRPCError(w, http.StatusBadRequest, rpcInvalidRequest,
			"unsupported MCP-Protocol-Version "+v+"; this server speaks "+strings.Join(mcpProtocolVersions, ", "))
		return
	}
	if ok, retry := h.limiter.allow(clientKey(r)); !ok {
		w.Header().Set("Retry-After", fmt.Sprint(int(retry.Seconds()+0.999)))
		writeRPCError(w, http.StatusTooManyRequests, rpcInternalError, "too many requests; retry in a moment")
		return
	}
	if r.ContentLength > mcpHTTPMaxBody {
		writeRPCError(w, http.StatusRequestEntityTooLarge, rpcInvalidRequest,
			fmt.Sprintf("request body is larger than %d bytes", mcpHTTPMaxBody))
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, mcpHTTPMaxBody+1))
	if err != nil {
		writeRPCError(w, http.StatusBadRequest, rpcParseError, "could not read the request body")
		return
	}
	if len(body) > mcpHTTPMaxBody {
		writeRPCError(w, http.StatusRequestEntityTooLarge, rpcInvalidRequest,
			fmt.Sprintf("request body is larger than %d bytes", mcpHTTPMaxBody))
		return
	}
	body = trimSpaceBytes(body)
	if len(body) == 0 {
		writeRPCError(w, http.StatusBadRequest, rpcParseError, "empty request body; POST one JSON-RPC message")
		return
	}
	// Batching was removed from MCP in 2025-06-18 (D-I5): stdio still accepts it, HTTP does not.
	if body[0] == '[' {
		writeRPCError(w, http.StatusBadRequest, rpcInvalidRequest,
			"JSON-RPC batches are not supported over HTTP; send one message per request")
		return
	}
	// Malformed JSON is a transport-level failure here, so it gets a 400 as well as the JSON-RPC parse error
	// (stdio has no status code and answers with the error alone).
	if !json.Valid(body) {
		writeRPCError(w, http.StatusBadRequest, rpcParseError, "parse error: the body is not valid JSON")
		return
	}
	line.Method, line.Tool = peekMethod(body)
	resp, isRequest := h.srv.handleMessage(body)
	if !isRequest {
		// A notification has no reply (MCP: 202 Accepted with an empty body).
		w.WriteHeader(http.StatusAccepted)
		return
	}
	writeHTTPJSON(w, http.StatusOK, resp)
}

// originAllowed: a server-to-server client sends no Origin, and that is the normal case. A browser origin is
// accepted only from vyomi.cloud, from loopback (the MCP Inspector) or from VYOMI_MCP_ALLOWED_ORIGINS.
func (h *mcpHTTPServer) originAllowed(origin string) bool {
	origin = strings.TrimSpace(origin)
	if origin == "" || strings.EqualFold(origin, "null") {
		return true
	}
	lower := strings.ToLower(origin)
	for _, o := range h.origins {
		if o == lower {
			return true
		}
	}
	u, err := url.Parse(origin)
	if err != nil {
		return false
	}
	host := strings.ToLower(u.Hostname())
	return host == "vyomi.cloud" || host == "www.vyomi.cloud" || isLoopback(host)
}

// peekMethod reads only the JSON-RPC method and, for tools/call, the tool name: the two fields the log carries
// (O-D4). Arguments are never touched.
func peekMethod(body []byte) (method, tool string) {
	var req struct {
		Method string `json:"method"`
		Params struct {
			Name string `json:"name"`
		} `json:"params"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		return "", ""
	}
	if req.Method == "tools/call" {
		return req.Method, req.Params.Name
	}
	return req.Method, ""
}

// logPath keeps the request path out of the log unless it is one of the paths this server serves, so a scanner's
// URL never lands in the log.
func logPath(p string) string {
	if isRPCPath(p) || isHealthPath(p) {
		if p == "" {
			return "/"
		}
		return p
	}
	return "other"
}

// clientKey is the address the rate limiter counts against: the first X-Forwarded-For hop when a proxy set one
// (App Platform and Cloudflare do), else the peer address. It is hashed before it is stored and never logged.
func clientKey(r *http.Request) string {
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		if first, _, ok := strings.Cut(xff, ","); ok {
			return strings.TrimSpace(first)
		}
		return strings.TrimSpace(xff)
	}
	if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		return host
	}
	return r.RemoteAddr
}

func methodNotAllowed(w http.ResponseWriter, allow string) {
	w.Header().Set("Allow", allow)
	writeRPCError(w, http.StatusMethodNotAllowed, rpcInvalidRequest,
		"this MCP server answers "+allow+" only: it is stateless and returns JSON, with no SSE stream and no session to end")
}

func writeHTTPJSON(w http.ResponseWriter, status int, v any) {
	b, err := json.Marshal(v)
	if err != nil {
		writeRPCError(w, http.StatusInternalServerError, rpcInternalError, "could not encode the response")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_, _ = w.Write(b)
}

// writeRPCError answers a transport-level failure as both an HTTP status and a JSON-RPC error, so a client that
// only reads the body still gets the reason (policy 5A: graceful errors that say how to fix the call).
func writeRPCError(w http.ResponseWriter, status, code int, msg string) {
	b, _ := json.Marshal(rpcResponse{JSONRPC: "2.0", ID: json.RawMessage("null"), Error: &rpcError{Code: code, Message: msg}})
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_, _ = w.Write(b)
}

func trimSpaceBytes(b []byte) []byte {
	i, j := 0, len(b)
	for i < j && (b[i] == ' ' || b[i] == '\t' || b[i] == '\n' || b[i] == '\r') {
		i++
	}
	for j > i && (b[j-1] == ' ' || b[j-1] == '\t' || b[j-1] == '\n' || b[j-1] == '\r') {
		j--
	}
	return b[i:j]
}

// responseRecorder keeps the status and byte count for the log line, and whether anything was written (so the
// panic handler knows if it can still answer).
type responseRecorder struct {
	http.ResponseWriter
	status int
	bytes  int
	wrote  bool
}

func (r *responseRecorder) WriteHeader(status int) {
	if r.wrote {
		return
	}
	r.status = status
	r.wrote = true
	r.ResponseWriter.WriteHeader(status)
}

func (r *responseRecorder) Write(b []byte) (int, error) {
	if !r.wrote {
		r.wrote = true
	}
	n, err := r.ResponseWriter.Write(b)
	r.bytes += n
	return n, err
}
