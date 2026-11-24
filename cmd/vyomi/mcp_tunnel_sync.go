package main

// Keeping `npx -y vyomi-tunnel mcp` and `vyomi-tunnel mcp` in sync (packaging/tunnel/bin/mcp-launch.mjs): an npx copy hands over to
// the user's installed vyomi-tunnel, so both run the same server. When the npx copy was newer, the launcher sets
// VYOMI_TUNNEL_LATEST beside VYOMI_TUNNEL_VERSION; vyomi_status then tells the agent to suggest the upgrade (the user runs it).

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

func semver3(s string) ([3]int, bool) {
	var v [3]int
	parts := strings.SplitN(strings.TrimPrefix(strings.TrimSpace(s), "v"), ".", 3)
	if len(parts) != 3 {
		return v, false
	}
	for i, p := range parts {
		if j := strings.IndexFunc(p, func(r rune) bool { return r < '0' || r > '9' }); j >= 0 {
			p = p[:j]
		}
		n, err := strconv.Atoi(p)
		if err != nil {
			return v, false
		}
		v[i] = n
	}
	return v, true
}

func semverLess(a, b [3]int) bool {
	for i := 0; i < 3; i++ {
		if a[i] != b[i] {
			return a[i] < b[i]
		}
	}
	return false
}

// tunnelSync reports the installed tunnel the MCP runs from and, when npm has a newer one, the upgrade to suggest. nil when the
// launcher passed nothing (started directly, or by a tunnel before 1.4.0).
func tunnelSync() map[string]any {
	installed := strings.TrimSpace(os.Getenv("VYOMI_TUNNEL_VERSION"))
	if installed == "" {
		return nil
	}
	out := map[string]any{"installed": installed}
	latest := strings.TrimSpace(os.Getenv("VYOMI_TUNNEL_LATEST"))
	iv, ok1 := semver3(installed)
	lv, ok2 := semver3(latest)
	if ok1 && ok2 && semverLess(iv, lv) {
		out["latest"] = latest
		out["upgrade"] = fmt.Sprintf("The installed vyomi-tunnel is %s; npm has %s. Suggest the user upgrade (npm i -g vyomi-tunnel@latest, or brew upgrade vyomi-tunnel) and restart the agent. Never run it yourself.", installed, latest)
	}
	return out
}
