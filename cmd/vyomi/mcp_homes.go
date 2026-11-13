package main

// Homes: where the simulator lives in v4 (spec §2). A Nano browser tab (reached through the local tunnel on
// :8090 or the cloud relay URL), a local mesh (the headless Pro/Max appliance on :9000), the v3 / v4.0.0
// offline appliance (:9000), or a mesh in the user's Codespace (reached through `vyomi-tunnel forward`).

import (
	"fmt"
	"net/url"
	"strconv"
	"strings"
)

const (
	homeNanoLocal     = "nano-local"
	homeNanoCloud     = "nano-cloud"
	homeMeshLocal     = "mesh-local"
	homeMeshCodespace = "mesh-codespace"
	homeOffline       = "offline"
)

// wiringHome maps a home id to the homes.<x> block of the knowledge (scripts/mcp_wiring.json).
func wiringHome(id string) string {
	switch id {
	case homeNanoLocal, homeNanoCloud:
		return "nano"
	case homeMeshLocal, homeMeshCodespace:
		return "mesh"
	}
	return "offline"
}

// homeSel is the home a tool works against: its id, the endpoint target, and why it was chosen.
type homeSel struct {
	ID      string
	Why     string
	Warning string
	target  mcpTarget
}

func relayPort() int {
	if p, err := strconv.Atoi(envAny("", "RELAY_PORT")); err == nil && p > 0 {
		return p
	}
	return 8090
}

func meshURL() string {
	if u := strings.TrimRight(envAny("", "VYOMI_MESH_URL"), "/"); u != "" {
		return u
	}
	return "http://127.0.0.1:9000"
}

// nanoTarget is the Nano endpoint: VYOMI_ENDPOINT when it names a non-local relay (the cloud relay URL from
// the Nano footer), else the local tunnel. Nano is plain HTTP: no TLS port.
func (s *mcpServer) nanoTarget() (mcpTarget, string) {
	t := mcpTarget{Scheme: "http", Host: "127.0.0.1", SimPort: relayPort(), Account: s.matrix.Defaults.AzureAccount}
	if ep := envAny("", "VYOMI_ENDPOINT"); ep != "" {
		if u, err := url.Parse(ep); err == nil && u.Hostname() != "" && !isLoopback(u.Hostname()) {
			return endpointTarget(u, t), homeNanoCloud
		}
	}
	return t, homeNanoLocal
}

// endpointTarget turns a base URL (scheme, host, optional port, optional path such as the relay session)
// into a target, keeping the defaults it does not override.
func endpointTarget(u *url.URL, t mcpTarget) mcpTarget {
	if u.Scheme != "" {
		t.Scheme = u.Scheme
	}
	t.Host = u.Hostname()
	t.SimPort = 0
	if p, err := strconv.Atoi(u.Port()); err == nil {
		t.SimPort = p
	}
	t.Path = strings.TrimRight(u.EscapedPath(), "/")
	return t
}

func isLoopback(h string) bool {
	return h == "127.0.0.1" || h == "localhost" || h == "::1" || strings.HasPrefix(h, "127.")
}

func (s *mcpServer) meshTarget() mcpTarget {
	t := s.target(nil)
	if u, err := url.Parse(meshURL()); err == nil && u.Hostname() != "" {
		t.Scheme, t.Host = "http", u.Hostname()
		if p, err := strconv.Atoi(u.Port()); err == nil {
			t.SimPort = p
		}
	}
	return t
}

// resolveHome turns a tool's `home` argument into a target. Explicit values never probe; "" / "auto" use the
// resolver (H1), which falls back to the legacy offline target when nothing is reachable.
func (s *mcpServer) resolveHome(arg string) (homeSel, error) {
	switch strings.ToLower(strings.TrimSpace(arg)) {
	case "nano":
		t, id := s.nanoTarget()
		return homeSel{ID: id, Why: "home=nano requested", target: t}, nil
	case "mesh":
		return homeSel{ID: homeMeshLocal, Why: "home=mesh requested", target: s.meshTarget()}, nil
	case "offline":
		return homeSel{ID: homeOffline, Why: "home=offline requested", target: s.target(nil)}, nil
	case "", "auto":
		return s.autoHome(), nil
	}
	return homeSel{}, fmt.Errorf("home must be one of auto, nano, mesh, offline (got %q)", arg)
}

// autoHome: until the resolver lands, the legacy target (VYOMI_ENDPOINT / :9000), labelled offline.
func (s *mcpServer) autoHome() homeSel {
	return homeSel{ID: homeOffline, Why: "default endpoint (VYOMI_ENDPOINT or 127.0.0.1:9000)", target: s.target(nil)}
}
