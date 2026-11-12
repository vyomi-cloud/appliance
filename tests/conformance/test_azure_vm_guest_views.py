"""Azure VM Inventory / Update Manager / Performance diagnostics, read from a REAL guest (docker exec on an alpine and a debian
container).  Skips (exit 0 with a note) when Docker is unavailable.  Run: PYTHONPATH=. python tests/conformance/test_azure_vm_guest_views.py"""
import shutil
import subprocess
import sys
import uuid
from core import ssh_access_core as sa

if not shutil.which("docker") or subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
    print("SKIP: docker not available"); sys.exit(0)

def check(n, c):
    if not c: raise AssertionError(n)
    print("  ok ", n)

def start(image):
    name = "vyomi-guestview-" + uuid.uuid4().hex[:6]
    subprocess.run(["docker", "run", "-d", "--name", name, image, "sleep", "300"], check=True, capture_output=True)
    return name

def runner(name):
    def run(_iid, sh):
        p = subprocess.run(["docker", "exec", name, "sh", "-c", sh], capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout
    return run

created = []
try:
    for image, fmt in (("postgres:16-alpine", "apk"), ("vyomi/appliance:3.0.45", "dpkg")):
        have = subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0
        if not have:
            print(f"  skip {image}: not present locally (no download in tests)"); continue
        n = start(image); created.append(n); run = runner(n)
        inv = sa.parse_inventory(run("x", sa.INVENTORY_CMD)[1])
        check(f"{image}: inventory reads the guest OS ({inv['os']['name']})", bool(inv["os"]["name"]) and inv["os"]["kernel"])
        check(f"{image}: package manager {fmt} with real packages", inv["packageManager"] == fmt and inv["packageCount"] > 5 and all(p["name"] for p in inv["packages"]))
        perf = sa.parse_perf(run("x", sa.PERF_CMD)[1])
        check(f"{image}: perf counters are live", perf["memTotalBytes"] > 0 and perf["cpus"] >= 1 and len(perf["loadAvg"]) == 3 and perf["diskRootUsedPercent"] is not None)
        check(f"{image}: top processes parsed", len(perf["topProcesses"]) >= 1)
        up = sa.parse_updates(run("x", sa.updates_command(False, False))[1])
        check(f"{image}: update assessment runs with {up['packageManager']}", up["supported"] and up["packageManager"] == ("apt" if fmt == "dpkg" else "apk") and up["pendingCount"] >= 0)
finally:
    for n in created:
        subprocess.run(["docker", "rm", "-f", n], capture_output=True)
# parsers on fixed text (no docker needed)
p = sa.parse_perf("##load\n3.00 2.0 1.0\n##cpus\n2\n##mem\nMemTotal: 1000 kB\nMemAvailable: 50 kB\n##uptime\n10.5 3\n##disk\n/dev/x 100 95 5 95% /\n##procs\n1 2048 init\n")
check("findings: load, memory and disk thresholds", {f["severity"] for f in p["findings"]} == {"Warning", "Critical"} and len(p["findings"]) == 3)
u = sa.parse_updates("##pm\napt\n##pending\nlibc6\t2.36-1\t2.36-2\n##end\n")
check("pending updates parsed", u["pending"] == [{"name": "libc6", "installed": "2.36-1", "available": "2.36-2"}])
print("PASS")
