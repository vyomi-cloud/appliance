package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

var iamClouds = []string{"aws", "gcp", "azure"}

func iamValidCloud(s string) bool {
	for _, c := range iamClouds {
		if c == s {
			return true
		}
	}
	return false
}

func iamValidMode(s string) bool { return s == "off" || s == "audit" || s == "enforce" }

// iamCall talks to the appliance /api/iam/<cloud>/... routes (same routes Nano serves in the browser).
func (c *Config) iamCall(method, path string, body any) (map[string]any, error) {
	var rd io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, c.applianceURL()+path, rd)
	if err != nil {
		return nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := (&http.Client{Timeout: 15 * time.Second}).Do(req)
	if err != nil {
		return nil, fmt.Errorf("appliance not reachable at %s: %v", c.applianceURL(), err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	var out map[string]any
	if err := json.Unmarshal(b, &out); err != nil {
		return nil, fmt.Errorf("unexpected response (%d): %s", resp.StatusCode, strings.TrimSpace(string(b)))
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("refused (%d): %v", resp.StatusCode, out["error"])
	}
	return out, nil
}

// parseIamEnforce parses: <cloud> [--service S] [--resource R] <mode>.
func parseIamEnforce(args []string) (cloud, service, resource, mode string, err error) {
	var pos []string
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--service", "--resource":
			if i+1 >= len(args) {
				return "", "", "", "", fmt.Errorf("%s needs a value", args[i])
			}
			if args[i] == "--service" {
				service = args[i+1]
			} else {
				resource = args[i+1]
			}
			i++
		default:
			pos = append(pos, args[i])
		}
	}
	if len(pos) != 2 || !iamValidCloud(pos[0]) || !iamValidMode(pos[1]) {
		return "", "", "", "", fmt.Errorf("usage: vyomi iam enforce <aws|gcp|azure> [--service S] [--resource R] <off|audit|enforce>")
	}
	if service != "" && resource != "" {
		return "", "", "", "", fmt.Errorf("use --service or --resource, not both")
	}
	return pos[0], service, resource, pos[1], nil
}

// applyIamMode returns the settings document with one level changed.
func applyIamMode(doc map[string]any, service, resource, mode string) map[string]any {
	sub := func(k string) map[string]any {
		m, _ := doc[k].(map[string]any)
		if m == nil {
			m = map[string]any{}
		}
		doc[k] = m
		return m
	}
	switch {
	case resource != "":
		sub("resources")[resource] = mode
	case service != "":
		sub("services")[service] = mode
	default:
		doc["space"] = mode
	}
	return doc
}

// iamCmd implements `vyomi iam enforce|status|audit`.
func (c *Config) iamCmd(args []string) int {
	if len(args) == 0 {
		fmt.Println("Usage: vyomi iam enforce <aws|gcp|azure> [--service S] [--resource R] <off|audit|enforce> | status | audit [cloud] [--limit N]")
		return 2
	}
	switch args[0] {
	case "enforce":
		cloud, svc, res, mode, err := parseIamEnforce(args[1:])
		if err != nil {
			return fail(err)
		}
		doc, err := c.iamCall("GET", "/api/iam/"+cloud+"/enforcement", nil)
		if err != nil {
			return fail(err)
		}
		out, err := c.iamCall("PUT", "/api/iam/"+cloud+"/enforcement", applyIamMode(doc, svc, res, mode))
		if err != nil {
			return fail(err)
		}
		b, _ := json.Marshal(out)
		fmt.Printf("%s enforcement updated: %s\n", cloud, b)
		return 0
	case "status":
		for _, cl := range iamClouds {
			doc, err := c.iamCall("GET", "/api/iam/"+cl+"/enforcement", nil)
			if err != nil {
				return fail(err)
			}
			b, _ := json.Marshal(doc)
			fmt.Printf("%-6s %s\n", cl, b)
		}
		return 0
	case "audit":
		cloud, limit := "aws", "50"
		rest := args[1:]
		for i := 0; i < len(rest); i++ {
			if rest[i] == "--limit" && i+1 < len(rest) {
				limit = rest[i+1]
				i++
			} else if iamValidCloud(rest[i]) {
				cloud = rest[i]
			}
		}
		out, err := c.iamCall("GET", "/api/iam/"+cloud+"/audit?limit="+url.QueryEscape(limit), nil)
		if err != nil {
			return fail(err)
		}
		recs, _ := out["records"].([]any)
		for _, r := range recs {
			m, _ := r.(map[string]any)
			fmt.Printf("%v  %-10v %-8v %v  %v  (%v)\n", m["time"], m["decision"], m["mode"], m["principal"], m["action"], m["resource"])
		}
		if len(recs) == 0 {
			fmt.Println("no audit records")
		}
		return 0
	}
	fmt.Println("vyomi iam: unknown subcommand", args[0])
	return 2
}
