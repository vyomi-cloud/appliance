//go:build !windows

package main

// On non-Windows hosts multipass is already on PATH and its daemon is managed by
// the OS service manager, so these are no-ops. (This VM path ships on Windows.)
func addMultipassToPath() {}
func startMultipassHost() {}
