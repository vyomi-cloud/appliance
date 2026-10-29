//go:build windows

package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
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

// enableVT turns on ANSI escape handling for stderr (Windows 10+ consoles), so the
// launch view can colour its output; false → the launcher prints plain lines.
func enableVT() bool {
	k32 := syscall.NewLazyDLL("kernel32.dll")
	getMode, setMode := k32.NewProc("GetConsoleMode"), k32.NewProc("SetConsoleMode")
	h, err := syscall.GetStdHandle(syscall.STD_ERROR_HANDLE)
	if err != nil {
		return false
	}
	var mode uint32
	if r, _, _ := getMode.Call(uintptr(h), uintptr(unsafe.Pointer(&mode))); r == 0 {
		return false
	}
	const enableVirtualTerminalProcessing = 0x0004
	r, _, _ := setMode.Call(uintptr(h), uintptr(mode|enableVirtualTerminalProcessing))
	return r != 0
}
