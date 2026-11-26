#!/bin/sh
# Downloads the SPIKE's third-party guest images into $SCRATCH (default: ./work) and links them where the pages expect them.
# Everything downloaded is untrusted data: it is only ever served as static files / read by the browser, never executed on the host.
# Total ~1.1 GB. Check `df -h /` first (spike rule: abort if < 10 GB free afterwards).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd); SCRATCH=${SCRATCH:-$HERE/work}
mkdir -p "$SCRATCH"/c2w "$SCRATCH"/v86 "$SCRATCH"/qemu
C2W=https://ktock.github.io/container2wasm-demo/containers
for p in amd64-debian-wasi-container:00,01,02,03,04 riscv64-debian-wasi-container:00,01,02 amd64-python-wasi-container:00,01,02 riscv64-python-wasi-container:00,01; do
  n=${p%%:*}; for i in $(echo "${p#*:}" | tr , ' '); do [ -f "$SCRATCH/c2w/$n$i.wasm" ] || curl -sf -o "$SCRATCH/c2w/$n$i.wasm" "$C2W/$n$i.wasm"; done; done
ln -sfn "$SCRATCH/c2w" "$HERE/c2w/images"
# v86 guests: prebuilt Buildroot kernel hosted by the v86 project, Tiny Core 16 (kernel+core.gz out of the ISO), our Debian i386 initramfs
[ -f "$SCRATCH/v86/buildroot-bzimage68.bin" ] || curl -sf -o "$SCRATCH/v86/buildroot-bzimage68.bin" https://i.copy.sh/buildroot-bzimage68.bin
[ -f "$SCRATCH/v86/freedos722.img" ] || curl -sf -o "$SCRATCH/v86/freedos722.img" https://i.copy.sh/freedos722.img
if [ ! -f "$SCRATCH/v86/tc/core.gz" ]; then
  mkdir -p "$SCRATCH/v86/tc" "$SCRATCH/tcx"; curl -sf -o "$SCRATCH/Core-current.iso" http://tinycorelinux.net/16.x/x86/release/Core-current.iso
  bsdtar -xf "$SCRATCH/Core-current.iso" -C "$SCRATCH/tcx" boot/vmlinuz boot/core.gz; cp "$SCRATCH/tcx/boot/vmlinuz" "$SCRATCH/tcx/boot/core.gz" "$SCRATCH/v86/tc/"
fi
# Debian 12 i386 userland on the production Alpine kernel (+ its virtio modules), built WITHOUT Docker/root:
[ -f "$SCRATCH/v86/debian-bookworm-i386.cpio.gz" ] || python3 -I "$HERE/tools/oci2initramfs.py" i386/debian bookworm-slim 386 "$SCRATCH/v86/debian-bookworm-i386.cpio.gz" \
  --init "$HERE/v86/init-debian.sh" --from-cpio "$HERE/../../wasm/vm/image/rootfs.cpio.gz" --keep-cpio-prefix lib/modules
ln -sfn "$SCRATCH/v86" "$HERE/v86/img"
# qemu-wasm demo build (x86_64 Alpine, GPL-2.0 QEMU; ~145 MB)
Q=https://ktock.github.io/qemu-wasm-demo/images/alpine-x86_64
for f in out.js qemu-system-x86_64.wasm qemu-system-x86_64.worker.js load-rootfs.js load-kernel.js load-initramfs.js load-rom.js load-rootfs.data load-kernel.data load-initramfs.data load-rom.data; do
  [ -f "$SCRATCH/qemu/$f" ] || curl -sf -o "$SCRATCH/qemu/$f" "$Q/$f"; done
ln -sfn "$SCRATCH/qemu" "$HERE/qemu-wasm/images"
echo "done; serve with: python3 serve.py 8501   (c2w + qemu-wasm)   and   python3 serve.py 8502 <repo root>   (v86)"
