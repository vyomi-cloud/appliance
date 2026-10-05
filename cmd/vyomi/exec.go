package main

import (
	"context"
	"os"
	"os/exec"
	"time"
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

// runQuietTimeout is runQuiet with a hard deadline. Needed for health checks
// like `docker info` against a wedged daemon, which can hang far longer than
// a normal failure (we've seen 500s/EOFs take 40-60s to surface) — without a
// bound, a polling loop built on runQuiet can overshoot its stated timeout by
// minutes because each failed check itself eats most of the budget.
func runQuietTimeout(d time.Duration, name string, args ...string) bool {
	ctx, cancel := context.WithTimeout(context.Background(), d)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
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
