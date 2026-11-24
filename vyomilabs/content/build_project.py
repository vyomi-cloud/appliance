"""Generate the real GitHub project behind Vyomi Labs: projects/vyomi-labs-facilities-agent/<cloud>/.
The files in app/ are the lab code blocks BYTE FOR BYTE (read from wasm/labs/data/<cloud>.json, which build_courses.py makes from the same source),
so what the course shows, what Deploy runs and what is on GitHub are one and the same. `python -m vyomilabs.content.build_project` regenerates it;
tests compare the files to the blocks."""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "projects" / "vyomi-labs-facilities-agent"
REPO = "vyomi-cloud/vyomi-labs-facilities-agent"
PKGS = {"aws": ["boto3"], "gcp": ["google-cloud-firestore", "google-cloud-storage", "google-auth", "requests", "functions-framework", "langgraph", "pyyaml", "cryptography"],
        "azure": ["azure-identity", "azure-mgmt-cognitiveservices", "azure-storage-blob", "azure-data-tables", "azure-servicebus", "azure-search-documents", "openai", "requests", "fastapi", "uvicorn", "langgraph", "pyjwt", "cryptography", "opentelemetry-sdk"]}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def build(cloud):
    d = json.loads((ROOT / "wasm" / "labs" / "data" / f"{cloud}.json").read_text())
    base = OUT / cloud
    (base / "app").mkdir(parents=True, exist_ok=True); (base / "chapters").mkdir(exist_ok=True); (base / ".devcontainer").mkdir(exist_ok=True)
    env, runs, toc = {}, [], []
    for l in d["layers"]:
        steps = []
        for b in l.get("lab") or []:
            (base / "app" / b["file"]).write_text(b["code"])
            for m in re.findall(r'os\.environ(?:\.get)?\(?\[?["\'](\w+)', b["code"]): env[m] = 1
            steps.append(b)
            if b.get("run"): runs.append((l["order"], l["title"], b["run"]))
        name = f"{l['order']:02d}-{slug(l['title'])}"
        md = [f"# Chapter {l['order']}: {l['title']}", "", f"_{l['outcome']}_", "", f"**What you build:** {l['objective']}", "", "## Code, in order", ""]
        for i, b in enumerate(steps, 1):
            md += [f"### {i}. {b['title']}", "", b["text"].rstrip(".") + ".", "", f"- File: [`app/{b['file']}`](../app/{b['file']})"]
            if b.get("run"): md.append(f"- Run: `cd app && {b['run']}`")
            if b.get("expect"): md.append(f"- You should see: `{b['expect']}`")
            md.append("")
        md += ["## It works when", ""] + [f"- {c}" for c in l["checks"]] + [""]
        (base / "chapters" / f"{name}.md").write_text("\n".join(md))
        toc.append((l["order"], l["title"], name, len(steps)))
    (base / "requirements.txt").write_text("\n".join(PKGS[cloud]) + "\n")
    (base / ".env.example").write_text("# Point the SDK at your Vyomi simulator (Nano tunnel, Mesh or appliance). See the README.\n" + "".join(f"{k}=\n" for k in sorted(env)))
    (base / "run_all.sh").write_text("#!/usr/bin/env bash\n# Runs every chapter's commands in course order against your simulator.\nset -euo pipefail\ncd \"$(dirname \"$0\")/app\"\n" + "".join(f"echo '== Chapter {o}: {t}'\n{r}\n" for o, t, r in runs))
    (base / "run_all.sh").chmod(0o755)
    (base / ".devcontainer" / "devcontainer.json").write_text(json.dumps({"name": f"Vyomi Labs: Facilities agent ({d['cloud_name']})", "image": "mcr.microsoft.com/devcontainers/python:3.12",
        "postCreateCommand": "pip install -r requirements.txt", "workspaceFolder": f"/workspaces/${{localWorkspaceFolderBasename}}/{cloud}",
        "customizations": {"vscode": {"extensions": ["ms-python.python"], "settings": {"python.defaultInterpreterPath": "/usr/local/bin/python"}}}}, indent=2) + "\n")
    rd = [f"# Facilities agent on {d['cloud_name']}", "", f"The finished project from the Vyomi Labs course **{d['title']}**: an enterprise agentic AI application, built in 13 layers and run against the Vyomi {d['cloud_name']} simulator at no cloud cost.", "",
          "Every file in [`app/`](app) is the exact code the course shows and deploys, in the same order.", "", "## Run it", "", "1. Start your Vyomi simulator (Nano with the tunnel, a Mesh, or the appliance) and copy its endpoint settings into `.env` (see `.env.example`).",
          "2. `pip install -r requirements.txt`", "3. `./run_all.sh` for every chapter, or follow one chapter at a time:", "", "| Chapter | Layer | Steps |", "|---|---|---|"]
    rd += [f"| {o} | [{t}](chapters/{n}.md) | {k} |" for o, t, n, k in toc]
    (base / "README.md").write_text("\n".join(rd) + "\n")
    return len(list((base / "app").iterdir()))


if __name__ == "__main__":
    for c in ("aws", "gcp", "azure"): print(c, build(c), "files")
    (OUT / "README.md").write_text("# Vyomi Labs: Facilities agent\n\nThe full project behind the Vyomi Labs course, one folder per cloud: [`aws/`](aws), [`gcp/`](gcp), [`azure/`](azure). Each is a working, layer-by-layer enterprise agentic AI application that runs against the Vyomi simulator.\n")
