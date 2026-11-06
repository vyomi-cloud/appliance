package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

// boosterBase is the booster's loopback control API (design s15: never the LAN).
func boosterBase() string {
	if v := os.Getenv("VYOMI_BOOSTER_URL"); v != "" {
		return strings.TrimRight(v, "/")
	}
	return "http://127.0.0.1:9000"
}

func boosterCall(method, path string) (map[string]any, error) {
	req, err := http.NewRequest(method, boosterBase()+path, nil)
	if err != nil {
		return nil, err
	}
	resp, err := (&http.Client{Timeout: 10 * time.Second}).Do(req)
	if err != nil {
		return nil, fmt.Errorf("booster not reachable at %s (is it running? try `vyomi up`): %v", boosterBase(), err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	var out map[string]any
	if err := json.Unmarshal(b, &out); err != nil {
		return nil, fmt.Errorf("unexpected response (%d): %s", resp.StatusCode, strings.TrimSpace(string(b)))
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("booster refused (%d): %v", resp.StatusCode, out["error"])
	}
	return out, nil
}

// boosterCmd implements `vyomi booster status|pair`.
func (c *Config) boosterCmd(args []string) int {
	sub := "status"
	if len(args) > 0 {
		sub = args[0]
	}
	switch sub {
	case "status":
		s, err := boosterCall("GET", "/booster/status")
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
		fmt.Printf("booster:   %v (%v)\nversion:   %v\ntier:      %v\nhostname:  %v\nhealth:    %v\n",
			s["booster_id"], ternary(s["headless"] == true, "headless", "not a booster"), s["version"], s["tier"], s["hostname"], health["state"])
		if s["trial"] == true {
			fmt.Printf("trial:     %v day(s) left\n", s["trial_days_left"])
		}
		if res != nil {
			fmt.Printf("capacity:  %v MB cap (70%% of host), usage %v MB\n", res["memory_cap_mb"], res["usage_mb"])
		}
		fmt.Printf("ui:        %v\n", s["nano_ui"])
		return 0
	case "pair":
		p, err := boosterCall("POST", "/booster/pair/start")
		if err != nil {
			return fail(err)
		}
		fmt.Printf("Pairing code: %v   (valid %v s)\nOpen %v and enter this code to attach this booster.\n",
			p["code"], p["expires_in"], p["nano_ui"])
		return 0
	default:
		fmt.Println("usage: vyomi booster status [--json] | vyomi booster pair")
		return 2
	}
}
