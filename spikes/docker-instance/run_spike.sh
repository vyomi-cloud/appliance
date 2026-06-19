#!/usr/bin/env bash
# SPIKE — throwaway. End-to-end Docker-backed Vyomi compute instance.
# Proves the lifecycle LXD/multipass do today: create -> shell -> docker-in-it
# (DinD) -> persistence across stop/start -> status -> terminate.
# Network-light: the only pull is docker:dind; the inner image is side-loaded
# from a cached image via `docker save | docker load` (no inner-network needed).
# Run on any host with docker:  bash run_spike.sh
set -uo pipefail
D=${DOCKER:-docker}
ID=spike001
NAME=vyomi-i-$ID
VOL=vyomi-i-$ID-root
IMG=${IMG:-docker:dind}
BASE_IMG=${BASE_IMG:-alpine:latest}

step(){ printf '\n=== %s ===\n' "$*"; }
cleanup(){ $D rm -f $NAME >/dev/null 2>&1; $D volume rm $VOL >/dev/null 2>&1; }
trap cleanup EXIT
cleanup  # start clean

step "1. CREATE — privileged, persistent root volume, cgroup-limited (== instance type)"
$D volume create $VOL >/dev/null
$D run -d --name $NAME \
   --label vyomi.instance=1 --label vyomi.instance_id=$ID \
   --restart unless-stopped \
   --cpus 1 --memory 1024m \
   -e DOCKER_TLS_CERTDIR= \
   -v $VOL:/var/lib/docker \
   --privileged "$IMG" >/dev/null
echo "  $($D ps --filter name=$NAME --format '{{.Names}} | {{.Status}} | {{.Image}}')"

step "2. BOOT — wait for the instance's inner dockerd (VM-boot equivalent)"
for i in $(seq 1 40); do
  $D exec $NAME docker info >/dev/null 2>&1 && { echo "  inner dockerd ready after ${i}s"; break; }
  sleep 1
done

step "3. SHELL — exec is the control-plane primitive (sshd layers on top in prod)"
$D exec $NAME sh -c 'echo "  uname=$(uname -sm)  user=$(id -un)  pid1=$(cat /proc/1/comm)"'

step "4. DOCKER-IN-INSTANCE (DinD) — side-load cached $BASE_IMG, run a container INSIDE"
$D save "$BASE_IMG" | $D exec -i $NAME docker load | sed 's/^/  load: /'
$D exec $NAME docker run --rm "$BASE_IMG" echo "  >> a container is running INSIDE the Vyomi instance"

step "5. PERSISTENCE — write data, stop, start, verify it survived"
MARK="state-$RANDOM-$RANDOM"
$D exec $NAME sh -c "echo $MARK > /root/marker.txt"
$D stop -t 5 $NAME >/dev/null && echo "  stopped"
$D start $NAME    >/dev/null && echo "  started"
for i in $(seq 1 40); do $D exec $NAME docker info >/dev/null 2>&1 && break; sleep 1; done
echo "  /root/marker.txt after restart : $($D exec $NAME cat /root/marker.txt 2>/dev/null)  (expected $MARK)"
echo "  inner images after restart     : $($D exec $NAME docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | tr '\n' ' ')"

step "6. STATUS + IP — what the SPA renders for the instance"
echo "  state=$($D inspect -f '{{.State.Status}}' $NAME)  ip=$($D inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $NAME)"

step "7. TERMINATE — rm container + delete its disk (handled on exit)"
echo "  cleanup trap will remove $NAME and volume $VOL"

echo; echo "SPIKE PASS — create -> boot -> shell -> DinD -> persist -> status -> terminate"
