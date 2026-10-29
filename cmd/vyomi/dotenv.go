package main

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
)

// DotenvLine represents a parsed line in a .env file.
type DotenvLine struct {
	Raw         string
	Key         string
	Value       string
	HasExport   bool
	IsManaged   bool
	IsDirective bool
}

// DotenvFile represents a parsed, line-preserving .env document.
type DotenvFile struct {
	Lines           []*DotenvLine
	LineEnding      string // "\n" or "\r\n"
	KeyIndex        map[string]int
	ManagedMark     int
	TrailingNewline bool // whether the parsed source ended in a line ending
}

// ParseDotenv parses raw bytes into a line-preserving DotenvFile.
func ParseDotenv(content []byte) *DotenvFile {
	lineEnding := "\n"
	if bytes.Contains(content, []byte("\r\n")) {
		lineEnding = "\r\n"
	}

	text := string(content)
	rawLines := strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n")
	// If the content ends with newline, Split produces an extra trailing empty element
	if len(rawLines) > 0 && rawLines[len(rawLines)-1] == "" && len(text) > 0 {
		rawLines = rawLines[:len(rawLines)-1]
	}

	df := &DotenvFile{
		Lines:           make([]*DotenvLine, 0, len(rawLines)),
		LineEnding:      lineEnding,
		KeyIndex:        make(map[string]int),
		ManagedMark:     -1,
		TrailingNewline: len(text) > 0 && strings.HasSuffix(text, "\n"),
	}

	for idx, raw := range rawLines {
		dl := &DotenvLine{Raw: raw}
		trimmed := strings.TrimSpace(raw)

		if strings.HasPrefix(trimmed, "# --- managed by vyomi") {
			dl.IsDirective = true
			df.ManagedMark = idx
		} else if strings.HasPrefix(trimmed, "#") || trimmed == "" {
			dl.IsDirective = true
		} else {
			// Check for export prefix
			lineWithoutExport := trimmed
			hasExport := false
			if strings.HasPrefix(trimmed, "export ") || strings.HasPrefix(trimmed, "export\t") {
				hasExport = true
				lineWithoutExport = strings.TrimSpace(trimmed[len("export"):])
			}

			// Key=Value parsing
			eqIdx := strings.Index(lineWithoutExport, "=")
			if eqIdx > 0 {
				key := strings.TrimSpace(lineWithoutExport[:eqIdx])
				val := strings.TrimSpace(lineWithoutExport[eqIdx+1:])
				dl.Key = key
				dl.Value = unquoteDotenv(val)
				dl.HasExport = hasExport
				df.KeyIndex[key] = idx
			} else {
				dl.IsDirective = true
			}
		}

		df.Lines = append(df.Lines, dl)
	}

	return df
}

// QuoteDotenvValue quotes a value if it contains spaces, #, =, or quotes.
func QuoteDotenvValue(v string) string {
	if v == "" {
		return ""
	}
	needsQuote := strings.ContainsAny(v, " \t#=\"'\n\r")
	if !needsQuote {
		return v
	}
	escaped := strings.ReplaceAll(v, `\`, `\\`)
	escaped = strings.ReplaceAll(escaped, `"`, `\"`)
	return `"` + escaped + `"`
}

func unquoteDotenv(v string) string {
	if len(v) >= 2 && ((v[0] == '"' && v[len(v)-1] == '"') || (v[0] == '\'' && v[len(v)-1] == '\'')) {
		inner := v[1 : len(v)-1]
		if v[0] == '"' {
			inner = strings.ReplaceAll(inner, `\"`, `"`)
			inner = strings.ReplaceAll(inner, `\\`, `\`)
		}
		return inner
	}
	return v
}

// ApplyUpdates modifies existing keys in place and appends new keys under a managed block.
// Returns a map of changed keys and their new values.
func (df *DotenvFile) ApplyUpdates(appName string, updates map[string]string) map[string]string {
	changed := make(map[string]string)
	unplaced := make(map[string]string)

	for k, v := range updates {
		if idx, found := df.KeyIndex[k]; found {
			line := df.Lines[idx]
			if line.Value != v {
				changed[k] = v
				line.Value = v
				// Reconstruct raw line preserving export
				prefix := ""
				if line.HasExport {
					prefix = "export "
				}
				line.Raw = fmt.Sprintf("%s%s=%s", prefix, k, QuoteDotenvValue(v))
			}
		} else {
			changed[k] = v
			unplaced[k] = v
		}
	}

	if len(unplaced) == 0 {
		return changed
	}

	// Append unplaced keys under managed section
	if df.ManagedMark == -1 {
		// Add managed header block
		if len(df.Lines) > 0 && df.Lines[len(df.Lines)-1].Raw != "" {
			df.Lines = append(df.Lines, &DotenvLine{Raw: "", IsDirective: true})
		}
		header := fmt.Sprintf("# --- managed by vyomi (app: %s) ---", appName)
		df.Lines = append(df.Lines, &DotenvLine{Raw: header, IsDirective: true})
		df.ManagedMark = len(df.Lines) - 1
	}

	for k, v := range unplaced {
		raw := fmt.Sprintf("%s=%s", k, QuoteDotenvValue(v))
		dl := &DotenvLine{Raw: raw, Key: k, Value: v, IsManaged: true}
		df.Lines = append(df.Lines, dl)
		df.KeyIndex[k] = len(df.Lines) - 1
	}

	return changed
}

// Bytes formats the lines back into content with original line endings.
func (df *DotenvFile) Bytes() []byte {
	var buf bytes.Buffer
	for i, l := range df.Lines {
		buf.WriteString(l.Raw)
		if i < len(df.Lines)-1 || df.TrailingNewline {
			buf.WriteString(df.LineEnding)
		}
	}
	return buf.Bytes()
}

// IsSecretKey checks if a variable name indicates sensitive data.
func IsSecretKey(k string) bool {
	upper := strings.ToUpper(k)
	return strings.Contains(upper, "PASSWORD") ||
		strings.Contains(upper, "SECRET") ||
		strings.Contains(upper, "KEY") ||
		strings.Contains(upper, "TOKEN") ||
		strings.Contains(upper, "CONNECTION_STRING")
}

// MaskValue masks secret values for dry-run output.
func MaskValue(val string) string {
	if val == "" {
		return ""
	}
	if len(val) <= 4 {
		return "********"
	}
	return val[:2] + "********" + val[len(val)-2:]
}

var reURLUserPass = regexp.MustCompile(`([a-zA-Z][a-zA-Z0-9+.-]*://)([^@\s]*?):([^@\s]+)@`)

// MaskURLCredentials masks passwords inside URL strings such as:
// postgresql://siftly:password123@localhost:5432/siftly or redis://:password@127.0.0.1:6379
func MaskURLCredentials(val string) string {
	return reURLUserPass.ReplaceAllStringFunc(val, func(m string) string {
		parts := reURLUserPass.FindStringSubmatch(m)
		if len(parts) == 4 {
			scheme := parts[1]
			user := parts[2]
			pass := parts[3]
			return scheme + user + ":" + MaskValue(pass) + "@"
		}
		return m
	})
}

// MaskEnvValue masks secret values for dry-run output.
// It masks embedded credentials inside URL values (e.g. DATABASE_URL or REDIS_URL),
// and masks the entire value for sensitive keys (e.g. DB_PASSWORD).
func MaskEnvValue(key, val string) string {
	if val == "" {
		return ""
	}
	if reURLUserPass.MatchString(val) {
		return MaskURLCredentials(val)
	}
	if IsSecretKey(key) {
		return MaskValue(val)
	}
	return val
}

// CheckGitTracked checks if a file is tracked by git.
func CheckGitTracked(repoDir, relPath string) (bool, error) {
	if !have("git") {
		return false, nil // Git not available -> warn and proceed
	}
	cmd := exec.Command("git", "ls-files", "--error-unmatch", relPath)
	cmd.Dir = repoDir
	err := cmd.Run()
	if err == nil {
		return true, nil // Exit 0 means tracked
	}
	return false, nil // Exit non-zero means untracked or error
}

// WriteDotenv updates a dotenv file atomically.
func WriteDotenv(repoDir, relPath, appName string, updates map[string]string, allowTracked bool) (map[string]string, error) {
	// 1. Path safety check (clean first so an embedded "../" can't hide
	// before the prefix check runs).
	cleanRel := filepath.Clean(filepath.FromSlash(relPath))
	if filepath.IsAbs(relPath) || cleanRel == ".." || strings.HasPrefix(cleanRel, ".."+string(filepath.Separator)) {
		return nil, fmt.Errorf("unsafe output path %q: must be relative to repository root", relPath)
	}

	targetPath := filepath.Join(repoDir, cleanRel)

	// 2. Git tracked check
	tracked, _ := CheckGitTracked(repoDir, cleanRel)
	if tracked && !allowTracked {
		// Check if any secrets are in the updates
		hasSecret := false
		for k := range updates {
			if IsSecretKey(k) {
				hasSecret = true
				break
			}
		}
		if hasSecret {
			return nil, fmt.Errorf("refusing to write secrets into git-tracked file %q (use --allow-tracked to override)", relPath)
		}
	}

	// 3. Read existing or start fresh
	var content []byte
	exists := false
	if data, err := os.ReadFile(targetPath); err == nil {
		content = data
		exists = true
	} else if !errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("cannot read %s: %w", targetPath, err)
	}

	df := ParseDotenv(content)
	if !exists {
		// Brand new file: end it with a conventional trailing newline.
		df.TrailingNewline = true
	}
	changed := df.ApplyUpdates(appName, updates)
	if len(changed) == 0 && exists {
		return changed, nil // No changes needed
	}

	// 4. Ensure parent directory exists
	dir := filepath.Dir(targetPath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("cannot create dir %s: %w", dir, err)
	}

	// 5. Create backup if file existed
	if exists {
		bakPath := targetPath + ".vyomi.bak"
		_ = os.WriteFile(bakPath, content, 0600)
	}

	// 6. Write atomically (tmp file + sync + rename)
	tmpPath := fmt.Sprintf("%s.tmp.%d", targetPath, os.Getpid())
	newBytes := df.Bytes()

	mode := os.FileMode(0600)
	if info, err := os.Stat(targetPath); err == nil {
		mode = info.Mode()
	}

	if err := os.WriteFile(tmpPath, newBytes, mode); err != nil {
		return nil, fmt.Errorf("cannot write tmp file %s: %w", tmpPath, err)
	}

	if err := os.Rename(tmpPath, targetPath); err != nil {
		_ = os.Remove(tmpPath)
		return nil, fmt.Errorf("atomic rename failed for %s: %w", targetPath, err)
	}

	return changed, nil
}
