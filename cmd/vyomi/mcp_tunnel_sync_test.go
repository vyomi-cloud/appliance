package main

import (
	"strings"
	"testing"
)

func TestTunnelSync(t *testing.T) {
	t.Setenv("VYOMI_TUNNEL_VERSION", "")
	t.Setenv("VYOMI_TUNNEL_LATEST", "")
	if tunnelSync() != nil {
		t.Fatal("no launcher env: no tunnel field")
	}
	t.Setenv("VYOMI_TUNNEL_VERSION", "1.4.0")
	if got := tunnelSync(); got["installed"] != "1.4.0" || got["upgrade"] != nil {
		t.Fatalf("in sync: %v", got)
	}
	t.Setenv("VYOMI_TUNNEL_LATEST", "1.4.0")
	if got := tunnelSync(); got["upgrade"] != nil {
		t.Fatalf("same version: %v", got)
	}
	t.Setenv("VYOMI_TUNNEL_VERSION", "1.3.3")
	t.Setenv("VYOMI_TUNNEL_LATEST", "1.4.0")
	got := tunnelSync()
	up, _ := got["upgrade"].(string)
	if got["latest"] != "1.4.0" || !strings.Contains(up, "1.3.3") || !strings.Contains(up, "Never run it yourself") {
		t.Fatalf("behind: %v", got)
	}
	t.Setenv("VYOMI_TUNNEL_LATEST", "1.4.0-rc.2")
	t.Setenv("VYOMI_TUNNEL_VERSION", "1.4.0")
	if got := tunnelSync(); got["upgrade"] != nil {
		t.Fatalf("rc of the same version is not newer: %v", got)
	}
}

func TestStatusCarriesTunnelSync(t *testing.T) {
	s, _ := testMCPServer(t)
	t.Setenv("VYOMI_TUNNEL_VERSION", "1.3.3")
	t.Setenv("VYOMI_TUNNEL_LATEST", "1.4.0")
	res, isErr := callTool(t, s, "vyomi_status", map[string]any{})
	if isErr {
		t.Fatal(res["error"])
	}
	tun, ok := res["tunnel"].(map[string]any)
	if !ok || tun["latest"] != "1.4.0" {
		t.Fatalf("vyomi_status should carry the tunnel sync field: %v", res["tunnel"])
	}
}
