package main

import (
	"fmt"
	"math"
	"runtime"
	"strconv"
	"strings"
)

// Sizing is the host-aware VM sizing (ported from Get-RecommendedSizing): always
// leave the host enough RAM so a heavy first-boot image pull can't starve it.
type Sizing struct {
	MemGb  int
	Cpus   int
	DiskGb int
}

const gib = 1024 * 1024 * 1024

func recommendedSizing() Sizing {
	cpu := runtime.NumCPU()
	memGb := float64(hostMemBytes()) / gib
	_, freeBytes := diskBytes(homeDir())
	freeGb := float64(freeBytes) / gib

	// Reserve ~4GB for the host OS/hypervisor, then give the VM 85% of the rest.
	vmMem := int(math.Floor((memGb - 4) * 0.85))
	if vmMem < 2 {
		vmMem = 2
	}
	if vmMem > 16 {
		vmMem = 16
	}
	vmCpus := int(math.Max(2, math.Min(math.Max(float64(cpu-1), 1), math.Ceil(float64(vmMem)/2.0))))
	vmDisk := int(math.Min(40, math.Max(20, math.Floor(freeGb*0.5))))
	return Sizing{MemGb: vmMem, Cpus: vmCpus, DiskGb: vmDisk}
}

func itoaG(g int) string { return fmt.Sprintf("%dG", g) }

func atoiDefault(s string, def int) int {
	s = strings.TrimSpace(s)
	if s == "" {
		return def
	}
	if v, err := strconv.Atoi(s); err == nil {
		return v
	}
	return def
}
