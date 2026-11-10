package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// meshBase is the mesh's loopback control API (design s15: never the LAN).
func meshBase() string {
	if v := os.Getenv("VYOMI_MESH_URL"); v != "" {
		return strings.TrimRight(v, "/")
	}
	return "http://127.0.0.1:9000"
}

func meshCall(method, path string) (map[string]any, error) {
	req, err := http.NewRequest(method, meshBase()+path, nil)
	if err != nil {
		return nil, err
	}
	resp, err := (&http.Client{Timeout: 10 * time.Second}).Do(req)
	if err != nil {
		return nil, fmt.Errorf("mesh not reachable at %s (is it running? try `vyomi up`): %v", meshBase(), err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	var out map[string]any
	if err := json.Unmarshal(b, &out); err != nil {
		return nil, fmt.Errorf("unexpected response (%d): %s", resp.StatusCode, strings.TrimSpace(string(b)))
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("mesh refused (%d): %v", resp.StatusCode, out["error"])
	}
	return out, nil
}

// meshCmd implements `vyomi mesh status|pair`.
func (c *Config) meshCmd(args []string) int {
	sub := "status"
	if len(args) > 0 {
		sub = args[0]
	}
	switch sub {
	case "status":
		s, err := meshCall("GET", "/mesh/status")
		if err != nil {
			return fail(err)
		}
		if len(args) > 1 && args[1] == "--json" {
			b, _ := json.MarshalIndent(s, "", "  ")
			fmt.Println(string(b))
			return 0
		}
		res, _ := s["resources"].(map[string]any)
		health, _ := s["health"].(map[string]any)
		fmt.Printf("mesh:   %v (%v)\nversion:   %v\ntier:      %v\nhostname:  %v\nhealth:    %v\n",
			s["mesh_id"], ternary(s["headless"] == true, "headless", "not a mesh"), s["version"], s["tier"], s["hostname"], health["state"])
		if s["trial"] == true {
			fmt.Printf("trial:     %v day(s) left\n", s["trial_days_left"])
		}
		if res != nil {
			fmt.Printf("capacity:  %v MB cap (70%% of host), usage %v MB\n", res["memory_cap_mb"], res["usage_mb"])
		}
		fmt.Printf("ui:        %v\n", s["nano_ui"])
		return 0
	case "pair":
		p, err := meshCall("POST", "/mesh/pair/start")
		if err != nil {
			return fail(err)
		}
		fmt.Printf("Pairing code: %v   (valid %v s)\nOpen %v and enter this code to attach this mesh.\n",
			p["code"], p["expires_in"], p["nano_ui"])
		return 0
	default:
		fmt.Println("usage: vyomi mesh status [--json] | vyomi mesh pair")
		return 2
	}
}

// exportHostMem puts the REAL host RAM (MB) in VYOMI_HOST_MEM_MB so docker compose forwards it to the appliance:
// inside a container the appliance only sees the Docker VM, and the mesh's 70% cap is of the HOST (core/mesh.py).
func exportHostMem() {
	if os.Getenv("VYOMI_HOST_MEM_MB") != "" {
		return
	}
	b := hostMemBytes()
	if runtime.GOOS == "darwin" {
		if out, err := exec.Command("sysctl", "-n", "hw.memsize").Output(); err == nil {
			if n, err := strconv.ParseInt(strings.TrimSpace(string(out)), 10, 64); err == nil && n > 0 {
				b = n
			}
		}
	}
	if b > 0 {
		os.Setenv("VYOMI_HOST_MEM_MB", strconv.FormatInt(b/(1024*1024), 10))
	}
}
