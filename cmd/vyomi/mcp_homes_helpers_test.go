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

// probelessHomes (rendering tests) points the probes that can CHOOSE a home at ports nothing listens on, while
// leaving the rendering defaults alone, so a vyomi-tunnel running on the developer's :8090 (or a local mesh)
// cannot change which home a home=auto call picks. Unlike deadHomes it keeps VYOMI_SIMULATOR_PORT at 9000,
// because these tests assert the offline endpoint: whatever answers on :9000, the offline home renders the same
// legacy target, so the result is the same with or without an appliance running.
func probelessHomes(t *testing.T) {
	t.Helper()
	t.Setenv("RELAY_PORT", strconv.Itoa(deadPort(t)))                         // the Nano tunnel probe
	t.Setenv("VYOMI_MESH_URL", "http://127.0.0.1:"+strconv.Itoa(deadPort(t))) // the local mesh probe
	t.Setenv("VYOMI_ENDPOINT", "")                                            // no relay or legacy override
	t.Setenv("VYOMI_TARGET", "")                                              // no explicit choice
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
