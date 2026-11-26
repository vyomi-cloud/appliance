#!/bin/sh
# PID 1 for the Debian i386 initramfs spike. Minimal: mounts + an interactive bash on the serial console (ttyS0).
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOME=/root TERM=vt100
mount -t proc proc /proc; mount -t sysfs sys /sys; mount -t devtmpfs dev /dev
mkdir -p /dev/pts /dev/shm /run /tmp; mount -t devpts devpts /dev/pts; mount -t tmpfs tmpfs /run; chmod 1777 /tmp
hostname vyomi-debian
exec setsid -c /bin/bash -c 'exec /bin/bash -i </dev/ttyS0 >/dev/ttyS0 2>&1'
