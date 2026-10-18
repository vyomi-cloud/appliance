package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestDispatchEnvMockServer(t *testing.T) {
	adminKeyExpected := "mock-test-admin-key-32chars-long-12345"

	// Mock server simulating appliance simulator API
	var lastReqBody map[string]any
	var lastHeader http.Header
	authFail := false

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		lastHeader = r.Header
		bodyBytes, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(bodyBytes, &lastReqBody)

		if authFail || r.Header.Get("X-CloudLearn-Admin-Key") != adminKeyExpected {
			w.WriteHeader(http.StatusForbidden)
			_, _ = w.Write([]byte(`{"ok":false,"code":"admin_key_required"}`))
			return
		}

		if strings.HasSuffix(r.URL.Path, "/resolve") {
			target := "host"
			if tVal, ok := lastReqBody["target"].(string); ok {
				target = tVal
			}

			redisPort := "6379"
			if target == "host" {
				redisPort = "36379"
			}

			resp := map[string]any{
				"ok":     true,
				"app":    "siftly",
				"target": target,
				"resolved": map[string]map[string]string{
					"backend/.env": {
						"DB_HOST":                         "localhost",
						"DB_PORT":                         "35432",
						"DB_PASSWORD":                     "secret_db_password_123",
						"REDIS_PORT":                      redisPort,
						"AZURE_STORAGE_CONNECTION_STRING": "DefaultEndpointsProtocol=http;AccountName=siftlystore;AccountKey=dummykey;BlobEndpoint=http://localhost:9000/azure-data/blob/siftlystore;",
					},
				},
				"warnings": []string{},
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(resp)
			return
		}

		w.WriteHeader(http.StatusNotFound)
	}))
	defer ts.Close()

	u, _ := url.Parse(ts.URL)
	port, _ := strconv.Atoi(u.Port())

	tmpDir := t.TempDir()
	vyomiHome := filepath.Join(tmpDir, "vyomi_home")
	_ = os.MkdirAll(vyomiHome, 0700)
	// Seed admin key
	_ = os.WriteFile(filepath.Join(vyomiHome, "admin_key"), []byte(adminKeyExpected+"\n"), 0600)

	// App repo dir
	repoDir := filepath.Join(tmpDir, "siftly-repo")
	_ = os.MkdirAll(filepath.Join(repoDir, ".vyomi"), 0755)

	profile := AppProfile{
		Version: 1,
		Name:    "siftly",
		Resources: map[string]any{
			"postgres": map[string]any{"siftly": map[string]any{}},
		},
		Outputs: map[string]map[string]string{
			"backend/.env": {
				"DB_HOST": "${postgres.siftly.host}",
			},
		},
	}
	pBytes, _ := json.Marshal(profile)
	_ = os.WriteFile(filepath.Join(repoDir, ".vyomi", "app.json"), pBytes, 0644)

	cfg := &Config{
		VyomiHome: vyomiHome,
		RootDir:   repoDir,
	}

	t.Setenv("VYOMI_SIMULATOR_PORT", strconv.Itoa(port))

	// Register app in registry
	if code := cfg.appAdd([]string{repoDir}); code != 0 {
		t.Fatalf("appAdd failed with code %d", code)
	}

	// 1. Test invalid target
	code := cfg.dispatchEnv([]string{"--app", "siftly", "--target", "invalid"})
	if code != 1 {
		t.Errorf("expected exit code 1 for invalid target, got %d", code)
	}

	// 2. Test 403 Forbidden rejection
	authFail = true
	code = cfg.dispatchEnv([]string{"--app", "siftly"})
	if code != 1 {
		t.Errorf("expected exit code 1 for 403 Forbidden, got %d", code)
	}
	authFail = false

	// 3. Test normal resolve and write
	code = cfg.dispatchEnv([]string{"--app", "siftly"})
	if code != 0 {
		t.Fatalf("dispatchEnv failed with code %d", code)
	}

	// Verify header sent
	if lastHeader.Get("X-CloudLearn-Admin-Key") != adminKeyExpected {
		t.Errorf("expected admin key header %q, got %q", adminKeyExpected, lastHeader.Get("X-CloudLearn-Admin-Key"))
	}

	// Verify file was written
	envFile := filepath.Join(repoDir, "backend", ".env")
	envContent, err := os.ReadFile(envFile)
	if err != nil {
		t.Fatalf("failed to read written .env: %v", err)
	}
	if !strings.Contains(string(envContent), "secret_db_password_123") {
		t.Errorf("expected DB_PASSWORD in written .env, got: %s", string(envContent))
	}

	// 4. Test --check when files are up to date -> exits 0
	code = cfg.dispatchEnv([]string{"--app", "siftly", "--check"})
	if code != 0 {
		t.Errorf("expected --check to exit 0 when files match, got %d", code)
	}

	// 5. Test --check when a file differs (e.g. simulate changed port) -> exits 1
	_ = os.WriteFile(envFile, []byte("DB_HOST=localhost\nREDIS_PORT=9999\n"), 0600)
	code = cfg.dispatchEnv([]string{"--app", "siftly", "--check"})
	if code != 1 {
		t.Errorf("expected --check to exit 1 when file differs, got %d", code)
	}

	// 6. Test --dry-run does not write and succeeds with 0
	code = cfg.dispatchEnv([]string{"--app", "siftly", "--dry-run"})
	if code != 0 {
		t.Errorf("expected --dry-run to exit 0, got %d", code)
	}
	// Verify file content was not overwritten by dry-run
	curContent, _ := os.ReadFile(envFile)
	if !strings.Contains(string(curContent), "REDIS_PORT=9999") {
		t.Errorf("dry run unexpectedly modified file: %s", string(curContent))
	}
}
