package main

import "testing"

func TestParseIamEnforce(t *testing.T) {
	c, s, r, m, err := parseIamEnforce([]string{"aws", "--service", "s3", "audit"})
	if err != nil || c != "aws" || s != "s3" || r != "" || m != "audit" {
		t.Fatalf("got %v %v %v %v %v", c, s, r, m, err)
	}
	if _, _, _, _, err := parseIamEnforce([]string{"aws", "bogus"}); err == nil {
		t.Fatal("bad mode accepted")
	}
	if _, _, _, _, err := parseIamEnforce([]string{"aws", "--service", "a", "--resource", "b", "off"}); err == nil {
		t.Fatal("both accepted")
	}
	d := applyIamMode(map[string]any{"space": "off"}, "", "arn:x", "enforce")
	if d["resources"].(map[string]any)["arn:x"] != "enforce" {
		t.Fatal("resource not set")
	}
}
