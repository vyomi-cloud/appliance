//go:build windows

package main

import "os/exec"

// probeProcGroup: on Windows exec.CommandContext's default Kill is used; WaitDelay bounds the wait for
// grandchildren that keep the pipes open.
func probeProcGroup(cmd *exec.Cmd) {}
