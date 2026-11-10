package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestParseDotenvAndRoundtrip(t *testing.T) {
	input := `# Existing comment
DB_HOST=localhost
# Another note
DB_PORT=5432
export DB_USER="my_user"
EMPTY_LINE=

`
	df := ParseDotenv([]byte(input))
	output := string(df.Bytes())
	if output != input {
		t.Fatalf("expected roundtrip match:\nGOT:\n%s\nWANT:\n%s", output, input)
	}
}

func TestCRLFPreservation(t *testing.T) {
	input := "DB_HOST=localhost\r\nDB_PORT=5432\r\n"
	df := ParseDotenv([]byte(input))
	if df.LineEnding != "\r\n" {
		t.Fatalf("expected CRLF line ending, got %q", df.LineEnding)
	}
	df.ApplyUpdates("test", map[string]string{"DB_HOST": "127.0.0.1"})
	output := string(df.Bytes())
	if !strings.Contains(output, "DB_HOST=127.0.0.1\r\n") {
		t.Fatalf("expected CRLF in updated output, got:\n%s", output)
	}
}

func TestInPlaceReplacementAndManagedBlock(t *testing.T) {
	input := `# Header comment
DB_HOST=localhost
export DB_USER=alice
`
	df := ParseDotenv([]byte(input))
	updates := map[string]string{
		"DB_HOST": "postgres.local",
		"DB_USER": "bob",
		"NEW_KEY": "val with spaces and # symbol",
	}

	df.ApplyUpdates("siftly", updates)
	out := string(df.Bytes())

	if !strings.Contains(out, "DB_HOST=postgres.local") {
		t.Errorf("expected DB_HOST replaced in place, got:\n%s", out)
	}
	if !strings.Contains(out, "export DB_USER=bob") {
		t.Errorf("expected export DB_USER preserved with new value, got:\n%s", out)
	}
	if !strings.Contains(out, "# --- managed by vyomi (app: siftly) ---") {
		t.Errorf("expected managed block header, got:\n%s", out)
	}
	if !strings.Contains(out, `NEW_KEY="val with spaces and # symbol"`) {
		t.Errorf("expected quoted NEW_KEY, got:\n%s", out)
	}
}

func TestWriteDotenvAtomicAndBackup(t *testing.T) {
	tmpDir := t.TempDir()
	relPath := "subdir/.env"

	initial := "EXISTING=hello\n"
	targetPath := filepath.Join(tmpDir, filepath.FromSlash(relPath))
	_ = os.MkdirAll(filepath.Dir(targetPath), 0755)
	if err := os.WriteFile(targetPath, []byte(initial), 0644); err != nil {
		t.Fatal(err)
	}

	updates := map[string]string{
		"EXISTING": "world",
		"NEW_VAR":  "123",
	}

	changed, err := WriteDotenv(tmpDir, relPath, "myapp", updates, true)
	if err != nil {
		t.Fatalf("WriteDotenv failed: %v", err)
	}
	if len(changed) != 2 {
		t.Errorf("expected 2 changed keys, got %d", len(changed))
	}

	// Verify target content
	data, err := os.ReadFile(targetPath)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "EXISTING=world") || !strings.Contains(string(data), "NEW_VAR=123") {
		t.Errorf("unexpected content:\n%s", string(data))
	}

	// Verify backup was created
	bakPath := targetPath + ".vyomi.bak"
	bakData, err := os.ReadFile(bakPath)
	if err != nil {
		t.Fatalf("backup file not created: %v", err)
	}
	if string(bakData) != initial {
		t.Errorf("expected backup to match initial content, got %q", string(bakData))
	}
}

func TestUnsafePathRejection(t *testing.T) {
	tmpDir := t.TempDir()
	_, err := WriteDotenv(tmpDir, "../outside.env", "app", map[string]string{"K": "V"}, true)
	if err == nil {
		t.Fatal("expected traversal path to be rejected")
	}

	absPath := filepath.Join(tmpDir, "abs.env")
	_, err = WriteDotenv(tmpDir, absPath, "app", map[string]string{"K": "V"}, true)
	if err == nil {
		t.Fatal("expected absolute path to be rejected")
	}
}

func TestMaskEnvValueAndURLSecrets(t *testing.T) {
	cases := []struct {
		key      string
		val      string
		expected string
	}{
		{
			key:      "DB_PASSWORD",
			val:      "supersecret123",
			expected: "su********23",
		},
		{
			key:      "DATABASE_URL",
			val:      "postgresql://siftly:supersecret123@localhost:35432/siftly",
			expected: "postgresql://siftly:su********23@localhost:35432/siftly",
		},
		{
			key:      "REDIS_URL",
			val:      "redis://:authpass@127.0.0.1:6379/0",
			expected: "redis://:au********ss@127.0.0.1:6379/0",
		},
		{
			key:      "SHORT_PASS",
			val:      "123",
			expected: "123", // Non-secret key name, non-URL
		},
		{
			key:      "SECRET_KEY",
			val:      "123",
			expected: "********", // Secret key with <= 4 chars
		},
		{
			key:      "DATABASE_URL_SHORT",
			val:      "postgresql://siftly:123@localhost:35432/siftly",
			expected: "postgresql://siftly:********@localhost:35432/siftly", // URL with short pass
		},
		{
			key:      "API_ENDPOINT",
			val:      "http://localhost:9000/api/v1",
			expected: "http://localhost:9000/api/v1", // No credentials
		},
		{
			key:      "DB_PORT",
			val:      "35432",
			expected: "35432", // Normal port
		},
	}

	for _, tc := range cases {
		got := MaskEnvValue(tc.key, tc.val)
		if got != tc.expected {
			t.Errorf("MaskEnvValue(%q, %q) = %q, want %q", tc.key, tc.val, got, tc.expected)
		}
	}
}
