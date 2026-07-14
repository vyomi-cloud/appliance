//go:build windows

package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// addMultipassToPath prepends the default Multipass install dir to PATH for this
// process, since multipass.exe lands on PATH only in shells opened after install.
func addMultipassToPath() {
	pf := os.Getenv("ProgramFiles")
	if pf == "" {
		return
	}
	dir := filepath.Join(pf, "Multipass", "bin")
	if !fileExists(dir) {
		return
	}
	cur := os.Getenv("Path")
	if !strings.Contains(strings.ToLower(cur), strings.ToLower(dir)) {
		os.Setenv("Path", dir+string(os.PathListSeparator)+cur)
	}
}

// startMultipassHost best-effort starts the Multipass Windows service so the
// daemon/socket becomes reachable (Start-MultipassHost).
func startMultipassHost() {
	for _, svc := range []string{"Multipass", "multipass", "MultipassService"} {
		_ = exec.Command("net", "start", svc).Run()
	}
}
