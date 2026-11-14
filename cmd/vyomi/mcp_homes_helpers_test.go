package main

import (
	"net"
	"path/filepath"
	"strconv"
	"testing"
)

// deadPort returns a loopback port nothing listens on.
func deadPort(t *testing.T) int {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	p := l.Addr().(*net.TCPAddr).Port
	l.Close()
	return p
}

// isolateHomes (every MCP test) hides any real vyomi-tunnel and credentials, so no test ever runs a real tunnel
// or reaches a portal. Ports stay at their defaults so rendering tests see 8090 / 9000.
func isolateHomes(t *testing.T) {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("VYOMI_TARGET", "")
	t.Setenv("VYOMI_TUNNEL_BIN", "")
	t.Setenv("VYOMI_ACCESS_KEY_ID", "")
	t.Setenv("VYOMI_HOME", dir)
	t.Setenv("VYOMI_CREDENTIALS_FILE", filepath.Join(dir, "no-credentials"))
	t.Setenv("PATH", "/usr/bin:/bin") // no vyomi-tunnel from the developer's PATH
	// Suggested forward ports must not depend on what the developer's machine has bound (e.g. an appliance on :9000).
	oldFree := portFree
	portFree = func(int) bool { return true }
	t.Cleanup(func() { portFree = oldFree })
}

// deadHomes (probing tests) points every probe at a dead port, so the resolver only sees the fakes a test starts
// and never a real tab on :8090 or an appliance on :9000 on the developer's machine.
func deadHomes(t *testing.T) {
	t.Helper()
	t.Setenv("RELAY_PORT", strconv.Itoa(deadPort(t)))
	t.Setenv("VYOMI_MESH_URL", "http://127.0.0.1:"+strconv.Itoa(deadPort(t)))
	t.Setenv("VYOMI_SIMULATOR_PORT", strconv.Itoa(deadPort(t)))
	t.Setenv("VYOMI_ENDPOINT", "")
}
