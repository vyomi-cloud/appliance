"""Generates the course "Vyomi Labs: Build Your First Agent (Nano)":
  wasm/labs/data/aws-agent-nano.json   the course data, same schema as aws-nano.json (labs.js renders it)
  wasm/labs/data/courses.json          the listing the Labs page uses to show the courses side by side
  wasm/labs/project/aws-agent-nano.json  the project for the in-course editor
  courses/vyomi-labs-nano-agent/aws/   the project folder (code byte for byte from the blocks)
Run: python -m vyomilabs.content.nano_agent.build_agent_course. It never touches aws.json, aws-nano.json or the Facilities project."""
import datetime
import json
import re
import shutil
from pathlib import Path

from .chapters import CH, COURSE

ROOT = Path(__file__).resolve().parents[3]
FILES = Path(__file__).resolve().parent / "files"
DATA = ROOT / "wasm" / "labs" / "data"
OUT = ROOT / "courses" / COURSE["slug"]
REPO = "vyomi-cloud/" + COURSE["slug"]
DOC_TITLES = {"bedrock": "Amazon Bedrock", "s3": "S3", "dynamodb": "DynamoDB", "sqs": "Simple Queue Service", "lambda": "Lambda"}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def layer_dir(l):
    return "%02d-%s" % (l["order"], slug(l["title"]))


def build_data():
    base = json.loads((DATA / "aws-nano.json").read_text())
    style = {l["id"]: l for l in base["layers"]}          # icon and colour per theme, borrowed so the two courses look alike
    layers = []
    for c in CH:
        st = style[c["from_layer"]]
        lab = []
        for title, text, save, variant, run, expect in c["blocks"]:
            lab.append(dict(title=title, text=text, file=save, lang="python", code=(FILES / variant).read_text(), run=run, expect=expect,
                            needs_runtime=False, edition=["nano", "mesh"], nano_note="", kind="build", needs_appliance=False))
        setup = [dict(title=t, route=r, do=d, fill=f, service=s, note="", click=False, n=i + 1) for i, (t, r, s, d, f) in enumerate(c["setup"])]
        layers.append(dict(
            id=c["id"], order=c["id"], title=c["title"], short=c["short"], objective=c["objective"], learn=c["learn"], services=c["services"],
            build=[b[0] for b in c["blocks"]], contract=dict(needs=c["needs"], names={}), checks=c["checks"], simplified=c["simplified"], native=None,
            reference="", code=None, checker=False, hotspot=[0, 0, 1, 1], level=c["level"], minutes=c["minutes"], outcome=c["outcome"], lessons=len(lab),
            color=st["color"], about=c["about"], why=c["why"], icon=st["icon"], prereq=c["prereq"], setup=setup, lab=lab, explain=c["explain"], narr=c["narr"],
            docs=[dict(id=d, title=DOC_TITLES[d], f=d + ".json") for d in c["docs"]], ops=[dict(f=f + ".json", n=n) for f, n in c["ops"]],
            validate=[dict(kind=k, what=w, how=h, expect=e) for k, w, h, e in c["validate"]],
            blocks_total=len(lab), blocks_nano=len(lab), blocks_mesh_only=0, mesh_only_titles=[]))
    doc = dict(cloud="aws", cloud_name="AWS", ai_platform="Amazon Bedrock (in your browser)", edition="nano", schema=2, course=COURSE["id"], intro=False,
               title=COURSE["title"], short_title=COURSE["short_title"], blurb=COURSE["blurb"], image=None, repo=REPO, repo_path="", repo_ref="main",
               plan=["Free", "Pro", "Max"], image_size=[1, 1], total_minutes=sum(l["minutes"] for l in layers),
               updated=datetime.date.today().strftime("%B %-d, %Y"), layers=layers)
    (DATA / "aws-agent-nano.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    return doc, base


def build_listing(doc, base):
    listing = dict(schema=1, courses=[
        dict(id="facilities", cloud="aws", file="aws-nano.json", key="vyomi.labs.aws", title=base["title"], level="Advanced", chapters=len(base["layers"]), minutes=base["total_minutes"],
             kicker="Enterprise course", badge="Runs in your browser (Nano) and in a Mesh",
             blurb="Build a complete enterprise agentic application layer by layer: models, runtime, tools, knowledge, memory, gateway, approval, access, observability and governance."),
        dict(id=COURSE["id"], cloud="aws", file="aws-agent-nano.json", key="vyomi.labs.aws." + COURSE["id"], title=COURSE["short_title"] + " (Nano)", level="Beginner", chapters=len(doc["layers"]),
             minutes=doc["total_minutes"], kicker="Start here", badge="Free. Runs entirely in your browser, no Mesh",
             blurb="Build and deploy a working help-desk agent with a small language model in your browser: a loop, a model, three tools, memory, knowledge and guardrails, deployed as a Lambda and evaluated.")])
    (DATA / "courses.json").write_text(json.dumps(listing, indent=1))


def build_project(doc):
    base = OUT / "aws"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    (base / ".devcontainer").mkdir()
    runs, toc = [], []
    for l in doc["layers"]:
        name = layer_dir(l)
        (base / name).mkdir()
        for b in l["lab"]:
            (base / name / b["file"]).write_text(b["code"])
            if b["run"]:
                runs.append((l["order"], l["title"], b["run"]))
        md = ["# Chapter %d: %s" % (l["order"], l["title"]), "", "_%s_" % l["outcome"], "", "**What you build:** " + l["objective"], "", "## Code, in order", ""]
        for i, b in enumerate(l["lab"], 1):
            md += ["### %d. %s" % (i, b["title"]), "", b["text"].rstrip(".") + ".", "", "- File: [`%s`](./%s)" % (b["file"], b["file"])]
            if b["run"]:
                md.append("- Run: `%s`" % b["run"])
            if b["expect"]:
                md.append("- You should see: `%s`" % b["expect"])
            md.append("")
        md += ["## It works when", ""] + ["- " + c for c in l["checks"]] + [""]
        (base / name / "README.md").write_text("\n".join(md))
        toc.append((l["order"], l["title"], name, len(l["lab"])))
    (base / "requirements.txt").write_text("boto3\n")
    (base / ".env.example").write_text("# Point the SDK at your Vyomi simulator (the Nano tunnel, a Mesh or the appliance).\nAWS_ENDPOINT_URL=\nAWS_DEFAULT_REGION=us-east-1\nAWS_ACCESS_KEY_ID=test\nAWS_SECRET_ACCESS_KEY=test\n")
    (base / ".gitignore").write_text(".workspace/\n.env\n__pycache__/\nhandler.py\n")
    sh = ["#!/usr/bin/env bash", "# Runs each chapter's commands in order against your simulator. ./run_all.sh runs all; ./run_all.sh 3 5 runs only those.",
          "# Chapters import each other's files, so they are first assembled side by side in .workspace/ (later chapters replace earlier versions of tools.py and agent.py).",
          "set -euo pipefail", 'root="$(cd "$(dirname "$0")" && pwd)"', 'rm -rf "$root/.workspace" && mkdir "$root/.workspace"',
          'for d in "$root"/[0-9][0-9]-*/; do for f in "$d"*; do case "$f" in */README.md) ;; *) cp "$f" "$root/.workspace/";; esac; done; done',
          '[ -f "$root/.env" ] && set -a && . "$root/.env" && set +a', 'cd "$root/.workspace"', 'want=" $* "']
    # the workspace is assembled from ALL chapters, so a file edited in a later chapter would shadow an earlier one: assemble per chapter instead
    sh = sh[:6] + ['[ -f "$root/.env" ] && set -a && . "$root/.env" && set +a', 'want=" $* "', "run_chapter() { n=\"$1\"; shift; for d in \"$root\"/[0-9][0-9]-*/; do for f in \"$d\"*; do case \"$f\" in */README.md) ;; *) cp \"$f\" \"$root/.workspace/\";; esac; done; [ \"$(basename \"$d\" | cut -c1-2)\" = \"$(printf %02d \"$n\")\" ] && break; done; (cd \"$root/.workspace\" && \"$@\"); }"]
    for o, t, r in runs:
        sh.append("if [ \"$want\" = \"  \" ] || [[ \"$want\" == *\" %d \"* ]]; then echo '== Chapter %d: %s'; run_chapter %d %s; fi" % (o, o, t, o, r))
    (base / "run_all.sh").write_text("\n".join(sh) + "\n")
    (base / "run_all.sh").chmod(0o755)
    (base / ".devcontainer" / "devcontainer.json").write_text(json.dumps({"name": "Vyomi Labs: Build Your First Agent", "image": "mcr.microsoft.com/devcontainers/python:3.12",
        "postCreateCommand": "pip install -r requirements.txt", "workspaceFolder": "/workspaces/${localWorkspaceFolderBasename}/aws",
        "customizations": {"vscode": {"extensions": ["ms-python.python"]}}}, indent=2) + "\n")
    rd = ["# Build Your First Agent (AWS, Nano)", "", "The finished project from the Vyomi Labs course **%s**: a help-desk agent that runs a small language model in your browser, uses three tools "
          "(search a handbook in S3, look up a record in DynamoDB, file a ticket to SQS), remembers, refuses what the documents do not support, and deploys as a Lambda function with a graded evaluation." % COURSE["title"], "",
          "Each chapter has its own folder with the exact code the course shows and deploys. Where a file changes in a later chapter (`tools.py`, `agent.py`), each chapter keeps its own version.", "",
          "## Run it", "", "1. Start Vyomi Nano and load a model (the course tells you when). Copy the endpoint settings into `.env`.", "2. `pip install -r requirements.txt`", "3. `./run_all.sh`, or `./run_all.sh 3` for one chapter.", "",
          "| Chapter | Folder | Steps |", "|---|---|---|"] + ["| %d. %s | [%s/](%s) | %d |" % (o, t, n, n, k) for o, t, n, k in toc]
    rd += ["", "## Next", "", "This course is the free, in-browser path. For hardening an agent for an enterprise (identity, approvals, audit, managed runtimes) continue with the Vyomi Labs Enterprise Facilities agent course."]
    (base / "README.md").write_text("\n".join(rd) + "\n")
    (OUT / "README.md").write_text("# Vyomi Labs: Build Your First Agent (Nano)\n\nThe project behind the free in-browser course, in [`aws/`](aws). It is generated from the course data (`python -m vyomilabs.content.nano_agent.build_agent_course`), never edited by hand.\n")
    files = {str(f.relative_to(base)): f.read_text() for f in sorted(base.rglob("*")) if f.is_file() and "__pycache__" not in f.parts}
    (ROOT / "wasm" / "labs" / "project" / "aws-agent-nano.json").write_text(json.dumps({"name": COURSE["slug"] + "-aws", "files": files}, separators=(",", ":")))
    return len(files)


if __name__ == "__main__":
    d, b = build_data()
    build_listing(d, b)
    print("course:", len(d["layers"]), "chapters,", sum(len(l["lab"]) for l in d["layers"]), "blocks,", sum(1 for l in d["layers"] for x in l["lab"] if x["run"]), "runnable;", build_project(d), "project files")
