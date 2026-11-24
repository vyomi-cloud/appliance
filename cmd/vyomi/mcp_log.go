package main

// The hosted server's request log (O-D4, design §8): one JSON line per request with a fixed set of fields, for
// uptime and error-rate work and for abuse investigations.
//
// What it must NEVER carry: tool arguments (a scan hit, an AGENTS.md text, a search string), any part of the
// request body, headers, or the client's address. The paths are from the server's own fixed set (anything else is
// logged as "other"), the JSON-RPC method and the tool name come from a two-field decode of the envelope
// (peekMethod), and the rest is counters.

import (
	"encoding/json"
	"io"
	"sync"
	"time"
)

type mcpLogLine struct {
	Time       string `json:"time"`
	HTTPMethod string `json:"http_method"`
	Path       string `json:"path"`
	Method     string `json:"method,omitempty"` // JSON-RPC method, e.g. tools/call
	Tool       string `json:"tool,omitempty"`   // tool name for tools/call
	Status     int    `json:"status"`
	MS         int64  `json:"ms"`
	Bytes      int    `json:"bytes"`
}

type mcpLogger struct {
	mu  sync.Mutex
	w   io.Writer
	now func() time.Time // tests
}

func newMCPLogger(w io.Writer) *mcpLogger {
	return &mcpLogger{w: w, now: time.Now}
}

func (l *mcpLogger) log(line mcpLogLine) {
	if l == nil || l.w == nil {
		return
	}
	line.Time = l.now().UTC().Format("2006-01-02T15:04:05.000Z")
	b, err := json.Marshal(line)
	if err != nil {
		return
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	_, _ = l.w.Write(append(b, '\n'))
}
