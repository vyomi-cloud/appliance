package main

import (
	"os"
	"path/filepath"
	"sort"
	"time"
)

var logFile string

// initializeLog creates ~/.vyomi/logs, opens a timestamped up-*.log, and prunes to
// the 10 most recent (Initialize-Log).
func (c *Config) initializeLog() {
	dir := filepath.Join(c.VyomiHome, "logs")
	if os.MkdirAll(dir, 0o755) != nil {
		return
	}
	stamp := time.Now().Format("20060102-150405")
	logFile = filepath.Join(dir, "up-"+stamp+".log")

	entries, err := filepath.Glob(filepath.Join(dir, "up-*.log"))
	if err != nil {
		return
	}
	type fi struct {
		path string
		mod  time.Time
	}
	var files []fi
	for _, p := range entries {
		if st, err := os.Stat(p); err == nil {
			files = append(files, fi{p, st.ModTime()})
		}
	}
	sort.Slice(files, func(i, j int) bool { return files[i].mod.After(files[j].mod) })
	for i := 10; i < len(files); i++ {
		_ = os.Remove(files[i].path)
	}
}

// logAppend writes a timestamped line to the active logfile (best-effort).
func logAppend(msg string) {
	if logFile == "" {
		return
	}
	f, err := os.OpenFile(logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	_, _ = f.WriteString("[" + time.Now().Format("15:04:05") + "] " + msg + "\n")
}
