//go:build !windows

package main

import (
	"os/exec"
	"syscall"
)

// probeProcGroup runs the child in its own process group and makes cancellation kill the whole group, so a
// probe that times out (vyomi-tunnel list -> gh codespace ssh) leaves no grandchild behind.
func probeProcGroup(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if cmd.Process == nil {
			return nil
		}
		return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
}
