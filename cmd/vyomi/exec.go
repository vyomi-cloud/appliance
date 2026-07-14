package main

import (
	"os"
	"os/exec"
)

// run executes a command with the CLI's stdio attached (the user sees live output),
// returning its exit error. This is the Go analogue of PowerShell's `& cmd args`.
func run(name string, args ...string) error {
	cmd := exec.Command(name, args...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	return cmd.Run()
}

// runQuiet runs a command discarding its output, returning whether it succeeded.
// The analogue of `try { & cmd | Out-Null; $true } catch { $false }`.
func runQuiet(name string, args ...string) bool {
	cmd := exec.Command(name, args...)
	return cmd.Run() == nil
}

// have reports whether an executable is on PATH (Get-Command -ErrorAction Silently).
func have(name string) bool {
	_, err := exec.LookPath(name)
	return err == nil
}

// capture runs a command and returns its combined stdout, trimmed of nothing.
func capture(name string, args ...string) (string, bool) {
	out, err := exec.Command(name, args...).Output()
	return string(out), err == nil
}
