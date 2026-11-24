"""Generate the real GitHub project behind Vyomi Labs: courses/vyomi-labs-facilities-agent/<cloud>/.
The files in each NN-layer/ folder are the lab code blocks BYTE FOR BYTE (read from wasm/labs/data/<cloud>.json, which build_courses.py makes from the same source),
so what the course shows, what Deploy runs and what is on GitHub are one and the same. `python -m vyomilabs.content.build_project` regenerates it;
tests compare the files to the blocks."""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COURSE = "vyomi-labs-facilities-agent"
OUT = ROOT / "courses" / COURSE          # GUIDELINE: every course and its python project lives under <appliance>/courses/<course-slug>/<cloud>/
REPO = "vyomi-cloud/" + COURSE     # standalone mirror repo: the editor opens ONLY this course, never the appliance (see scripts/sync_course_repo.sh)
PATH = ""                          # the mirror has the cloud folders at its root
PKGS = {"aws": ["boto3"], "gcp": ["google-cloud-firestore", "google-cloud-storage", "google-auth", "requests", "functions-framework", "langgraph", "pyyaml", "cryptography"],
        "azure": ["azure-identity", "azure-mgmt-cognitiveservices", "azure-storage-blob", "azure-data-tables", "azure-servicebus", "azure-search-documents", "openai", "requests", "fastapi", "uvicorn", "langgraph", "pyjwt", "cryptography", "opentelemetry-sdk"]}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def layer_dir(l):
    return f"{l['order']:02d}-{slug(l['title'])}"


def build(cloud):
    import shutil
    d = json.loads((ROOT / "wasm" / "labs" / "data" / f"{cloud}.json").read_text())
    base = OUT / cloud
    for old in ("app", "chapters"): shutil.rmtree(base / old, ignore_errors=True)       # the earlier flat layout
    for old in base.glob("[0-9][0-9]-*"): shutil.rmtree(old)
    base.mkdir(parents=True, exist_ok=True); (base / ".devcontainer").mkdir(exist_ok=True)
    env, runs, toc = {}, [], []
    for l in d["layers"]:
        name = layer_dir(l); (base / name).mkdir()
        steps = []
        for b in l.get("lab") or []:
            (base / name / b["file"]).write_text(b["code"])
            for m in re.findall(r'os\.environ(?:\.get)?\(?\[?["\'](\w+)', b["code"]): env[m] = 1
            steps.append(b)
            if b.get("run"): runs.append((l["order"], l["title"], name, b["run"]))
        md = [f"# Layer {l['order']}: {l['title']}", "", f"_{l['outcome']}_", "", f"**What you build:** {l['objective']}", "", "## Code, in order", ""]
        for i, b in enumerate(steps, 1):
            md += [f"### {i}. {b['title']}", "", b["text"].rstrip(".") + ".", "", f"- File: [`{b['file']}`](./{b['file']})"]
            if b.get("run"): md.append(f"- Run: `{b['run']}` (or `./run_all.sh {l['order']}` from the project root)")
            if b.get("expect"): md.append(f"- You should see: `{b['expect']}`")
            md.append("")
        md += ["## It works when", ""] + [f"- {c}" for c in l["checks"]] + [""]
        (base / name / "README.md").write_text("\n".join(md))
        toc.append((l["order"], l["title"], name, len(steps)))
    (base / "requirements.txt").write_text("\n".join(PKGS[cloud]) + "\n")
    (base / ".env.example").write_text("# Point the SDK at your Vyomi simulator (Nano tunnel, Mesh or appliance). See the README.\n" + "".join(f"{k}=\n" for k in sorted(env)))
    (base / ".gitignore").write_text(".workspace/\n.env\n__pycache__/\n")
    sh = ['#!/usr/bin/env bash', '# Runs the layers\' commands in course order against your simulator. ./run_all.sh runs every layer; ./run_all.sh 3 7 runs only those.',
          '# Layers import each other\'s files, so the files are first assembled side by side in .workspace/ (the same flat layout the course deploys from).',
          'set -euo pipefail', 'root="$(cd "$(dirname "$0")" && pwd)"', 'rm -rf "$root/.workspace" && mkdir "$root/.workspace"', 'for d in "$root"/[0-9][0-9]-*/; do for f in "$d"*; do case "$f" in */README.md) ;; *) cp "$f" "$root/.workspace/";; esac; done; done',
          '[ -f "$root/.env" ] && set -a && . "$root/.env" && set +a', 'cd "$root/.workspace"', 'want=" $* "']
    for o, t, n, r in runs: sh.append(f"if [ \"$want\" = \"  \" ] || [[ \"$want\" == *\" {o} \"* ]]; then echo '== Layer {o}: {t}'; {r}; fi")   # a failing step stops the run (set -e)
    (base / "run_all.sh").write_text("\n".join(sh) + "\n")
    (base / "run_all.sh").chmod(0o755)
    (base / ".devcontainer" / "devcontainer.json").write_text(json.dumps({"name": f"Vyomi Labs: Facilities agent ({d['cloud_name']})", "image": "mcr.microsoft.com/devcontainers/python:3.12",
        "postCreateCommand": "pip install -r requirements.txt", "workspaceFolder": f"/workspaces/${{localWorkspaceFolderBasename}}/{cloud}",
        "customizations": {"vscode": {"extensions": ["ms-python.python"], "settings": {"python.defaultInterpreterPath": "/usr/local/bin/python"}}}}, indent=2) + "\n")
    rd = [f"# Facilities agent on {d['cloud_name']}", "", f"The finished project from the Vyomi Labs course **{d['title']}**: an enterprise agentic AI application, built in 13 layers and run against the Vyomi {d['cloud_name']} simulator at no cloud cost.", "",
          "Each layer has its own folder with the exact code the course shows and deploys, and a README that explains it.", "", "## Run it", "", "1. Start your Vyomi simulator (Nano with the tunnel, a Mesh, or the appliance) and copy its endpoint settings into `.env` (see `.env.example`).",
          "2. `pip install -r requirements.txt`", "3. `./run_all.sh` for every layer, or `./run_all.sh 7` for one layer.", "", "| Layer | Folder | Steps |", "|---|---|---|"]
    rd += [f"| {o}. {t} | [{n}/]({n}) | {k} |" for o, t, n, k in toc]
    (base / "README.md").write_text("\n".join(rd) + "\n")
    files = {str(f.relative_to(base)): f.read_text() for f in sorted(base.rglob("*")) if f.is_file() and "__pycache__" not in f.parts and ".workspace" not in f.parts}
    out = ROOT / "wasm" / "labs" / "project"; out.mkdir(exist_ok=True)       # the same files, for the in-course editor (works with no GitHub)
    (out / f"{cloud}.json").write_text(json.dumps({"name": f"{COURSE}-{cloud}", "files": files}, separators=(",", ":")))
    return sum(1 for f in base.glob("[0-9][0-9]-*/*") if f.name != "README.md")


if __name__ == "__main__":
    for c in ("aws", "gcp", "azure"): print(c, build(c), "files")
    (OUT / "README.md").write_text("# Vyomi Labs: Facilities agent\n\nThe full project behind the Vyomi Labs course, one folder per cloud: [`aws/`](aws), [`gcp/`](gcp), [`azure/`](azure). Each is a working, layer-by-layer enterprise agentic AI application that runs against the Vyomi simulator.\n")
