package main

import (
	"sort"
	"strings"
	"testing"
)

// Guardrail: the MCP is a knowledge/config helper, not an administration channel. Its tool list is pinned here so a new
// tool, a new write path or a changed hint is a deliberate, reviewed change (it can never edit the simulator's config,
// database, signed code or image; the only write is one .env.vyomi* file in the user's own project).
func TestMCPToolSurfaceIsPinned(t *testing.T) {
	s, _ := testMCPServer(t)
	readOnly := []string{"vyomi_agents_md", "vyomi_capability", "vyomi_env", "vyomi_reach", "vyomi_scan_repo", "vyomi_services", "vyomi_snippet", "vyomi_status"}
	writers := []string{"vyomi_write_env"}

	var gotRO, gotW []string
	for _, tool := range s.buildTools() {
		switch {
		case tool.ReadOnly && !tool.Destructive:
			gotRO = append(gotRO, tool.Name)
		case !tool.ReadOnly:
			gotW = append(gotW, tool.Name)
			if !tool.Destructive {
				t.Errorf("%s writes, so it must carry destructiveHint=true", tool.Name)
			}
		default:
			t.Errorf("%s is read-only and destructive at once", tool.Name)
		}
	}
	sort.Strings(gotRO)
	sort.Strings(gotW)
	if strings.Join(gotRO, ",") != strings.Join(readOnly, ",") {
		t.Errorf("read-only tools changed: got %v want %v (a new tool needs a deliberate review)", gotRO, readOnly)
	}
	if strings.Join(gotW, ",") != strings.Join(writers, ",") {
		t.Errorf("writing tools changed: got %v want %v — the MCP must not gain write/exec tools without review", gotW, writers)
	}
}

// The hint reaches clients: tools/list carries destructiveHint=true for the writer and readOnlyHint=true for the rest.
func TestMCPToolAnnotationsOnTheWire(t *testing.T) {
	s, _ := testMCPServer(t)
	for _, tool := range s.buildTools() {
		a := tool.describe()["annotations"].(map[string]any)
		if tool.Name == "vyomi_write_env" {
			if a["destructiveHint"] != true || a["readOnlyHint"] != false {
				t.Errorf("vyomi_write_env annotations: %v", a)
			}
			continue
		}
		if a["readOnlyHint"] != true || a["destructiveHint"] != false {
			t.Errorf("%s annotations: %v", tool.Name, a)
		}
	}
}
