package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestValidateProfileSuccess(t *testing.T) {
	p := &AppProfile{
		Version: 1,
		Name:    "my_app",
		Resources: map[string]any{
			"postgres": map[string]any{
				"main": map[string]any{"user": "app_user"},
			},
			"blob": map[string]any{
				"media": map[string]any{},
			},
			"redis": map[string]any{
				"cache": map[string]any{},
			},
			"servicebus": map[string]any{
				"events": map[string]any{},
			},
		},
		Outputs: map[string]map[string]string{
			"config/.env": {
				"DB_HOST": "${postgres.main.host}",
				"DB_PORT": "${postgres.main.port}",
				"SECRET":  "${secret.jwt_key}",
				"URL":     "${postgres.main.url}?sslmode=disable",
				"ESCAPED": "$${escaped.val}",
			},
		},
	}

	if err := ValidateProfile(p); err != nil {
		t.Fatalf("expected valid profile, got: %v", err)
	}
}

func TestValidateProfileErrors(t *testing.T) {
	tests := []struct {
		name    string
		mutate  func(*AppProfile)
		wantErr string
	}{
		{
			name: "unsupported version",
			mutate: func(p *AppProfile) {
				p.Version = 2
			},
			wantErr: "unsupported profile version 2",
		},
		{
			name: "invalid name with dashes",
			mutate: func(p *AppProfile) {
				p.Name = "invalid-name"
			},
			wantErr: "invalid app name",
		},
		{
			name: "missing resources",
			mutate: func(p *AppProfile) {
				p.Resources = nil
			},
			wantErr: "missing 'resources'",
		},
		{
			name: "missing outputs",
			mutate: func(p *AppProfile) {
				p.Outputs = nil
			},
			wantErr: "missing 'outputs'",
		},
		{
			name: "unknown resource type",
			mutate: func(p *AppProfile) {
				p.Resources["dynamodb"] = map[string]any{}
			},
			wantErr: "unknown resource type \"dynamodb\"",
		},
		{
			name: "absolute output path",
			mutate: func(p *AppProfile) {
				p.Outputs["/etc/passwd"] = map[string]string{"K": "V"}
			},
			wantErr: "must be relative to repo root",
		},
		{
			name: "path leaving repo",
			mutate: func(p *AppProfile) {
				p.Outputs["../escape/.env"] = map[string]string{"K": "V"}
			},
			wantErr: "must be relative to repo root",
		},
		{
			name: "malformed resource reference",
			mutate: func(p *AppProfile) {
				p.Outputs["config/.env"] = map[string]string{"K": "${postgres.main}"}
			},
			wantErr: "malformed resource reference",
		},
		{
			name: "malformed secret reference",
			mutate: func(p *AppProfile) {
				p.Outputs["config/.env"] = map[string]string{"K": "${secret}"}
			},
			wantErr: "malformed secret reference",
		},
		{
			name: "unknown resource category in reference",
			mutate: func(p *AppProfile) {
				p.Outputs["config/.env"] = map[string]string{"K": "${mysql.db.host}"}
			},
			wantErr: "unknown resource type \"mysql\"",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			p := &AppProfile{
				Version:   1,
				Name:      "testapp",
				Resources: map[string]any{"postgres": map[string]any{}},
				Outputs:   map[string]map[string]string{"sub/.env": {"A": "B"}},
			}
			tt.mutate(p)
			err := ValidateProfile(p)
			if err == nil {
				t.Fatalf("expected error containing %q, got nil", tt.wantErr)
			}
			if !strings.Contains(err.Error(), tt.wantErr) {
				t.Fatalf("expected error containing %q, got %q", tt.wantErr, err.Error())
			}
		})
	}
}

func TestSiftlyReferenceProfile(t *testing.T) {
	// Root dir of repo is 2 levels up from cmd/vyomi
	samplePath := filepath.Join("..", "..", "samples", "siftly")
	profile, err := LoadProfile(samplePath)
	if err != nil {
		t.Fatalf("LoadProfile(samples/siftly) failed: %v", err)
	}

	if profile.Name != "siftly" {
		t.Errorf("expected app name 'siftly', got %q", profile.Name)
	}
	if profile.Version != 1 {
		t.Errorf("expected version 1, got %d", profile.Version)
	}
	if len(profile.Outputs) != 3 {
		t.Errorf("expected 3 output files, got %d", len(profile.Outputs))
	}
}

func TestAppRegistryAddListRemove(t *testing.T) {
	tmpDir := t.TempDir()
	cfg := &Config{VyomiHome: tmpDir}

	reg, err := cfg.loadRegistry()
	if err != nil {
		t.Fatalf("loadRegistry failed: %v", err)
	}
	if len(reg.Apps) != 0 {
		t.Fatalf("expected empty registry, got %d apps", len(reg.Apps))
	}

	// Create a dummy app repo
	repoDir := filepath.Join(tmpDir, "sample-repo")
	_ = os.MkdirAll(filepath.Join(repoDir, ".vyomi"), 0755)
	appProfile := AppProfile{
		Version:   1,
		Name:      "dummy",
		Resources: map[string]any{"redis": map[string]any{}},
		Outputs:   map[string]map[string]string{".env": {"REDIS": "${redis.default.host}"}},
	}
	profData, _ := json.Marshal(appProfile)
	_ = os.WriteFile(filepath.Join(repoDir, ".vyomi", "app.json"), profData, 0644)

	// Test app add
	if code := cfg.appAdd([]string{repoDir}); code != 0 {
		t.Fatalf("appAdd returned code %d, expected 0", code)
	}

	// Verify in registry
	reg2, err := cfg.loadRegistry()
	if err != nil {
		t.Fatalf("loadRegistry failed: %v", err)
	}
	if rec, ok := reg2.Apps["dummy"]; !ok || rec.RepoPath != repoDir {
		t.Fatalf("dummy app record mismatch: %+v", rec)
	}

	// Test resolveAppRepo with name
	resolvedDir, resolvedProf, err := cfg.resolveAppRepo("dummy")
	if err != nil {
		t.Fatalf("resolveAppRepo failed: %v", err)
	}
	if resolvedDir != repoDir || resolvedProf.Name != "dummy" {
		t.Fatalf("resolved app mismatch: dir=%s, name=%s", resolvedDir, resolvedProf.Name)
	}

	// Test app list
	if code := cfg.appDumpList(); code != 0 {
		t.Fatalf("appDumpList returned code %d, expected 0", code)
	}

	// Test app remove
	if code := cfg.appRemove([]string{"dummy"}); code != 0 {
		t.Fatalf("appRemove returned code %d, expected 0", code)
	}

	// Verify removed
	reg3, _ := cfg.loadRegistry()
	if _, ok := reg3.Apps["dummy"]; ok {
		t.Fatalf("dummy app still present after remove")
	}
}

func TestWithProfileAndSimulatorPort(t *testing.T) {
	origProfile := os.Getenv("COMPOSE_PROFILES")
	defer func() {
		if origProfile == "" {
			_ = os.Unsetenv("COMPOSE_PROFILES")
		} else {
			_ = os.Setenv("COMPOSE_PROFILES", origProfile)
		}
	}()

	_ = os.Unsetenv("COMPOSE_PROFILES")
	filtered := handleWithProfile([]string{"up", "-d", "--with", "app", "--other"})
	if os.Getenv("COMPOSE_PROFILES") != "app" {
		t.Errorf("expected COMPOSE_PROFILES=app, got %q", os.Getenv("COMPOSE_PROFILES"))
	}
	if len(filtered) != 3 || filtered[0] != "up" || filtered[1] != "-d" || filtered[2] != "--other" {
		t.Errorf("unexpected filtered args: %v", filtered)
	}

	// Append profile
	_ = handleWithProfile([]string{"--with=full"})
	if os.Getenv("COMPOSE_PROFILES") != "app,full" {
		t.Errorf("expected COMPOSE_PROFILES=app,full, got %q", os.Getenv("COMPOSE_PROFILES"))
	}

	// Test simulator port resolution
	cfg := &Config{}
	t.Setenv("VYOMI_SIMULATOR_PORT", "9200")
	if port := cfg.simulatorPort(); port != 9200 {
		t.Errorf("expected port 9200, got %d", port)
	}
	t.Setenv("VYOMI_SIMULATOR_PORT", "")
	if port := cfg.simulatorPort(); port != 9000 {
		t.Errorf("expected default port 9000, got %d", port)
	}
}
