#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from textwrap import wrap


PAGE_W = 612
PAGE_H = 792
MARGIN = 40


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def fmt(num: float) -> str:
    if abs(num - round(num)) < 1e-6:
        return str(int(round(num)))
    return f"{num:.2f}".rstrip("0").rstrip(".")


class PDFBuilder:
    def __init__(self) -> None:
        self.objects: list[bytes | None] = []

    def reserve(self) -> int:
        self.objects.append(None)
        return len(self.objects)

    def set_object(self, obj_id: int, data: bytes) -> None:
        self.objects[obj_id - 1] = data

    def build(self, path: Path) -> None:
        offsets: list[int] = []
        out = bytearray()
        out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        for i, obj in enumerate(self.objects, start=1):
            offsets.append(len(out))
            out.extend(f"{i} 0 obj\n".encode("ascii"))
            out.extend(obj or b"<<>>")
            out.extend(b"\nendobj\n")

        xref_pos = len(out)
        out.extend(f"xref\n0 {len(self.objects) + 1}\n".encode("ascii"))
        out.extend(b"0000000000 65535 f \n")
        for off in offsets:
            out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
        out.extend(
            (
                "trailer\n"
                f"<< /Size {len(self.objects) + 1} /Root {len(self.objects)} 0 R >>\n"
                "startxref\n"
                f"{xref_pos}\n"
                "%%EOF\n"
            ).encode("ascii")
        )
        path.write_bytes(out)


class Page:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def text(self, x: float, y: float, text: str, size: int = 11, font: str = "F1") -> None:
        self.parts.append(f"BT /{font} {size} Tf {fmt(x)} {fmt(y)} Td ({esc(text)}) Tj ET")

    def paragraph(self, x: float, y: float, text: str, size: int = 11, width: int = 88, leading: int | None = None, font: str = "F1") -> float:
        leading = leading or int(size * 1.35)
        lines = wrap(text, width=width) if text else [""]
        cur_y = y
        for i, line in enumerate(lines):
            self.text(x, cur_y, line, size=size, font=font)
            cur_y -= leading
        return cur_y

    def bullets(self, x: float, y: float, items: list[str], size: int = 11, width: int = 84, leading: int | None = None) -> float:
        leading = leading or int(size * 1.35)
        cur_y = y
        for item in items:
            lines = wrap(item, width=width)
            self.text(x, cur_y, f"- {lines[0]}", size=size)
            cur_y -= leading
            for cont in lines[1:]:
                self.text(x + 12, cur_y, cont, size=size)
                cur_y -= leading
            cur_y -= 2
        return cur_y

    def box(self, x: float, y: float, w: float, h: float, title: str, body: list[str], fill=(0.96, 0.97, 0.99), stroke=(0.25, 0.32, 0.42)) -> None:
        self.parts.append(
            f"q {fmt(fill[0])} {fmt(fill[1])} {fmt(fill[2])} rg {fmt(stroke[0])} {fmt(stroke[1])} {fmt(stroke[2])} RG "
            f"{fmt(x)} {fmt(y)} {fmt(w)} {fmt(h)} re B Q"
        )
        self.text(x + 8, y + h - 15, title, size=10, font="F2")
        cy = y + h - 29
        for line in body:
            for seg in wrap(line, width=max(18, int(w / 5.0))):
                if cy < y + 10:
                    break
                self.text(x + 8, cy, seg, size=8)
                cy -= 10

    def header(self, title: str, subtitle: str = "") -> None:
        self.text(MARGIN, PAGE_H - 48, title, size=20, font="F2")
        if subtitle:
            self.text(MARGIN, PAGE_H - 68, subtitle, size=10)
        self.parts.append(f"q 0.70 0.74 0.80 rg {MARGIN} {PAGE_H - 78} {PAGE_W - 2 * MARGIN} 1.2 re f Q")

    def footer(self, page_no: int) -> None:
        self.parts.append(f"q 0.82 0.82 0.82 rg {MARGIN} 28 {PAGE_W - 2 * MARGIN} 0.8 re f Q")
        self.text(MARGIN, 16, "CloudLearn Full Architecture", size=9)
        self.text(PAGE_W - MARGIN - 46, 16, f"Page {page_no}", size=9)

    def content(self) -> bytes:
        return ("\n".join(self.parts) + "\n").encode("ascii")


def render(path: Path) -> None:
    pages: list[Page] = []

    # Page 1
    p = Page()
    p.header("CloudLearn Full Simulator Architecture", "Local-first cloud learning platform with AWS-like workflows, runtime bundles, certification, and persistent state")
    p.paragraph(
        MARGIN,
        700,
        "CloudLearn is a simulator and training platform that behaves like a cloud provider from the user's point of view while staying lightweight and fully local. It uses a custom simulation core, AWS-compatible adapters, and pluggable runtimes instead of recreating AWS internals.",
        size=11,
        width=92,
    )
    p.text(MARGIN, 622, "Product goals", size=14, font="F2")
    p.bullets(MARGIN, 604, [
        "Run locally on macOS, Windows, and Linux.",
        "Persist workflow state so users can stop and restart.",
        "Expose common AWS APIs and console-style flows.",
        "Drive every UI action through the documented API surface.",
        "Provide turnkey runtimes for Java, .NET, Go, PHP, and Python.",
        "Support certification exercises and scoring.",
        "Export and import infrastructure through Terraform.",
        "Simulate VPC, AZ, and security group behavior with lightweight engines.",
    ], size=11, width=86)
    p.footer(1)
    pages.append(p)

    # Page 2
    p = Page()
    p.header("Top-Level Runtime Stack", "The simulator is a local control plane that orchestrates adapters, persistence, entitlement, and workload runtimes.")
    p.box(36, 610, 118, 66, "User Entry", ["Console", "CLI", "SDK"], fill=(0.97, 0.97, 0.92))
    p.box(168, 610, 130, 66, "API Gateway", ["AWS-style routing", "SigV4 acceptance", "Error translation"], fill=(0.94, 0.96, 0.99))
    p.box(314, 598, 124, 78, "Simulation Kernel", ["Resource graph", "Workflows", "Lifecycle", "Latency / failure"], fill=(0.92, 0.97, 0.93))
    p.box(454, 610, 122, 66, "Local State", ["SQLite", "Files", "Snapshots"], fill=(0.98, 0.95, 0.94))
    p.box(168, 476, 130, 66, "Service Adapters", ["S3, IAM, EC2, VPC", "RDS, Lambda, MQ", "CloudWatch, CFN"], fill=(0.95, 0.94, 0.99))
    p.box(314, 476, 124, 66, "Runtime Manager", ["Launch workloads", "Restart", "Logs", "Health checks"], fill=(0.94, 0.98, 0.95))
    p.box(454, 476, 122, 66, "Entitlements", ["Credits", "Tier gating", "Lockout"], fill=(0.99, 0.98, 0.92))
    p.box(314, 346, 124, 66, "Runtime Bundles", ["Java", ".NET", "Go", "PHP", "Python"], fill=(0.94, 0.97, 0.98))
    p.box(454, 346, 122, 66, "GitHub / TF", ["Deploy source", "Export IaC", "Import IaC"], fill=(0.96, 0.95, 0.98))
    p.footer(2)
    pages.append(p)

    # Page 3
    p = Page()
    p.header("Platform Services", "The control plane adds the product features around the simulator core.")
    p.text(MARGIN, 702, "Control plane responsibilities", size=14, font="F2")
    p.bullets(MARGIN, 684, [
        "Own simulator startup and shutdown.",
        "Route incoming API and UI actions to the right service adapter.",
        "Store all durable state locally.",
        "Issue entitlement and credit decisions.",
        "Track certification attempts and completions.",
        "Connect GitHub sources to runtime bundles.",
        "Keep service implementations thin by reusing shared engines.",
    ], size=11, width=86)
    p.text(308, 702, "Security and licensing", size=14, font="F2")
    p.bullets(308, 684, [
        "Sign licenses, bundles, and exercise packs.",
        "Detect tampering and quarantine the client.",
        "Require cloud-issued unlock for blocked devices.",
        "Cache entitlements offline when allowed.",
        "Keep UI thin; enforce in backend services.",
    ], size=11, width=42)
    p.text(MARGIN, 436, "Persistence model", size=14, font="F2")
    p.bullets(MARGIN, 418, [
        "SQLite for structured state and workflow tables.",
        "Local filesystem for uploads, logs, and artifacts.",
        "Event log for replay and audit.",
        "Snapshots for fast stop/start recovery.",
        "Encrypted token store for licenses and GitHub access.",
    ], size=11, width=86)
    p.footer(3)
    pages.append(p)

    # Page 4
    p = Page()
    p.header("Runtime and Deployment", "The runtime layer turns source code or artifacts into local, cloud-like workloads.")
    p.box(36, 610, 166, 76, "Runtime Manager", ["Select bundle", "Prepare workload", "Start / stop / restart"], fill=(0.94, 0.98, 0.95))
    p.box(224, 610, 166, 76, "Runtime Bundles", ["Language-specific packaging", "Startup templates", "Health checks"], fill=(0.95, 0.97, 0.99))
    p.box(412, 610, 164, 76, "Local Host", ["Container engine or sandbox", "Ports", "Volumes", "Logs"], fill=(0.98, 0.96, 0.94))
    p.text(MARGIN, 514, "Supported runtime bundles", size=14, font="F2")
    p.bullets(MARGIN, 496, [
        "Java bundle: JDK, Maven/Gradle hooks, Spring Boot / Micronaut / Quarkus-friendly startup.",
        ".NET bundle: dotnet run or published artifact startup.",
        "Go bundle: compile to static binary and run minimal container.",
        "PHP bundle: PHP-FPM or built-in server mode.",
        "Python bundle: uv, pip, virtualenv, uvicorn/gunicorn support.",
    ], size=11, width=88)
    p.text(MARGIN, 286, "GitHub deployment", size=14, font="F2")
    p.bullets(MARGIN, 268, [
        "GitHub App or scoped OAuth tokens.",
        "Browse repo, branch, tag, and commit.",
        "Build locally and deploy into the selected runtime.",
        "Track deployment history and rollback.",
    ], size=11, width=88)
    p.footer(4)
    pages.append(p)

    # Page 5
    p = Page()
    p.header("Exercises, Validation, and Portability", "This is where the platform becomes a learning product rather than a raw simulator.")
    p.box(36, 610, 170, 74, "Certification Engine", ["Labs, scoring, hints, time limits", "Local progress tracking", "Hidden validation rules"], fill=(0.94, 0.96, 0.99))
    p.box(222, 610, 170, 74, "AWS Validation Mode", ["Run same workflow against AWS", "Compare responses and state", "Optional and not default"], fill=(0.98, 0.95, 0.95))
    p.box(408, 610, 168, 74, "Terraform Bridge", ["Export simulator state to IaC", "Import IaC into simulator", "Keep desired state aligned"], fill=(0.95, 0.98, 0.94))
    p.text(MARGIN, 512, "Plan / credit gating", size=14, font="F2")
    p.bullets(MARGIN, 494, [
        "Free, Pro, Max, and Enterprise tiers.",
        "Credits unlock advanced services and exercises.",
        "Capability registry decides what is available.",
        "Entitlement changes are enforced in backend services.",
    ], size=11, width=86)
    p.text(MARGIN, 342, "Installer and distribution", size=14, font="F2")
    p.bullets(MARGIN, 324, [
        "Native installers for macOS, Windows, and Linux.",
        "Signed packages and update channels.",
        "Background service or tray app if desired.",
        "Local data directories and state initialization.",
        "Optional Docker Compose stack for fast local launch.",
    ], size=11, width=86)
    p.box(360, 208, 216, 72, "Docker Compose Mode", [
        "Compose brings up the control plane, gateway, runtime manager, and persistence volume.",
        "Use it for demos, onboarding, and restartable local environments.",
        "It is a supported deployment profile alongside native installers.",
    ], fill=(0.95, 0.98, 0.98))
    p.footer(5)
    pages.append(p)

    # Page 6
    p = Page()
    p.header("Service Catalog View", "The simulator should present a catalog of cloud capabilities rather than expose every internal primitive.")
    p.box(36, 620, 168, 62, "Storage", ["S3", "EBS-like volumes", "EFS-like shares"], fill=(0.96, 0.98, 0.95))
    p.box(222, 620, 168, 62, "Compute", ["EC2", "Auto Scaling", "Batch", "Lightsail"], fill=(0.95, 0.97, 0.99))
    p.box(408, 620, 168, 62, "Networking", ["VPC", "Route 53", "API Gateway", "Load balancing"], fill=(0.98, 0.95, 0.96))
    p.box(36, 536, 168, 62, "Identity", ["IAM", "identity personas", "session roles"], fill=(0.97, 0.95, 0.99))
    p.box(222, 536, 168, 62, "Data", ["RDS", "NoSQL", "cache", "snapshots"], fill=(0.95, 0.99, 0.97))
    p.box(408, 536, 168, 62, "Integration", ["Lambda", "SQS", "SNS", "Step Functions"], fill=(0.99, 0.98, 0.94))
    p.box(36, 452, 168, 62, "Observability", ["CloudWatch", "traces", "metrics", "logs"], fill=(0.95, 0.96, 0.99))
    p.box(222, 452, 168, 62, "Infrastructure", ["CloudFormation", "Terraform bridge", "drift checks"], fill=(0.98, 0.96, 0.94))
    p.box(408, 452, 168, 62, "Containers", ["ECR", "ECS", "EKS-aligned flows"], fill=(0.95, 0.98, 0.96))
    p.text(MARGIN, 370, "The service catalog should also attach credit cost, entitlement tier, and certification support to every capability.", size=11)
    p.footer(6)
    pages.append(p)

    # Page 7
    p = Page()
    p.header("Detailed Service Architecture 1", "S3, IAM, and EC2 are the first services that define the simulator's daily workflow.")
    p.box(36, 616, 168, 88, "S3", [
        "Back end: filesystem or embedded object store.",
        "Model: buckets, objects, tags, versions, multipart uploads.",
        "Behaviors: create, upload, download, list, copy, range, delete.",
    ], fill=(0.95, 0.98, 0.95))
    p.box(222, 616, 168, 88, "IAM", [
        "Back end: simplified evaluator.",
        "Model: users, roles, groups, policies, sessions.",
        "Behaviors: allow/deny, personas, role assumption, gating.",
    ], fill=(0.98, 0.95, 0.98))
    p.box(408, 616, 168, 88, "EC2", [
        "Back end: container or sandbox runtime.",
        "Model: instances, metadata, storage, security groups.",
        "Behaviors: pending, running, stopping, stopped, terminated.",
    ], fill=(0.95, 0.97, 0.99))
    p.text(MARGIN, 512, "EC2 runtime mapping", size=14, font="F2")
    p.bullets(MARGIN, 494, [
        "Target OS and runtime stack become a container template.",
        "AMI maps to an image plus startup and metadata config.",
        "EBS maps to local volumes or bind mounts.",
        "Instance metadata service is provided locally.",
        "Console output and boot scripts are surfaced to the UI.",
    ], size=11, width=88)
    p.footer(7)
    pages.append(p)

    # Page 8
    p = Page()
    p.header("Detailed Service Architecture 2", "VPC, RDS, and Lambda cover network isolation, data services, and code execution.")
    p.box(36, 616, 168, 88, "VPC", [
        "Back end: routing and policy simulation.",
        "Model: VPC, subnet, route table, security group, endpoint.",
        "Behaviors: ingress/egress, public/private paths, service attachment.",
    ], fill=(0.95, 0.97, 0.96))
    p.box(222, 616, 168, 88, "RDS", [
        "Back end: local DB or containerized database.",
        "Model: instance, parameter group, subnet group, snapshot.",
        "Behaviors: create, start, stop, connect, snapshot, restore.",
    ], fill=(0.98, 0.96, 0.94))
    p.box(408, 616, 168, 88, "Lambda", [
        "Back end: sandboxed process or container.",
        "Model: function, handler, timeout, memory, triggers.",
        "Behaviors: invoke, log, timeout, error, event trigger.",
    ], fill=(0.96, 0.95, 0.99))
    p.text(MARGIN, 512, "These services should be lightweight but workflow-compatible. The user should recognize the control flow even if the internals are custom.", size=11)
    p.footer(8)
    pages.append(p)

    # Page 9
    p = Page()
    p.header("Detailed Service Architecture 3", "Queues, messages, logs, and template deployment complete the basic cloud workflow loop.")
    p.box(36, 616, 168, 88, "SQS / SNS", [
        "Back end: in-memory or local broker.",
        "Model: queues, topics, subscriptions, messages.",
        "Behaviors: enqueue, receive, publish, fan-out, retries.",
    ], fill=(0.96, 0.99, 0.95))
    p.box(222, 616, 168, 88, "CloudWatch", [
        "Back end: event and metric store.",
        "Model: logs, streams, metrics, alarms, dashboards.",
        "Behaviors: query, publish, alert, display health.",
    ], fill=(0.95, 0.96, 0.99))
    p.box(408, 616, 168, 88, "CloudFormation", [
        "Back end: template parser and resource graph applier.",
        "Model: stacks, changesets, outputs, events.",
        "Behaviors: create, update, rollback, dependency order.",
    ], fill=(0.99, 0.96, 0.94))
    p.text(MARGIN, 512, "These services are the glue for certification labs and app workflows. They should drive state changes in the same kernel, not separate subsystems.", size=11)
    p.footer(9)
    pages.append(p)

    # Page 10
    p = Page()
    p.header("Detailed Service Architecture 4", "Container and edge services support packaged workloads and local routing.")
    p.box(36, 616, 168, 88, "Containers", [
        "Back end: Podman or Docker engine integration.",
        "Model: image, repo, task, service, cluster, deployment.",
        "Behaviors: push, pull, run, update, rolling replace.",
    ], fill=(0.95, 0.98, 0.98))
    p.box(222, 616, 168, 88, "API Gateway / Edge", [
        "Back end: local gateway router.",
        "Model: APIs, routes, stages, custom domains, DNS records.",
        "Behaviors: route traffic, deploy stage, expose endpoints.",
    ], fill=(0.98, 0.95, 0.97))
    p.box(408, 616, 168, 88, "Route 53", [
        "Back end: local name resolution map.",
        "Model: hosted zones, records, aliases.",
        "Behaviors: resolve simulator endpoints to local services.",
    ], fill=(0.97, 0.97, 0.95))
    p.text(MARGIN, 512, "Provider expansion path", size=14, font="F2")
    p.bullets(MARGIN, 494, [
        "AWS first, because the market and training demand are strongest.",
        "Reuse the same kernel for Azure and GCP through provider adapters.",
        "Keep console skins, API facades, and terminology mappings separate from the kernel.",
        "Preserve the same workflow engine and local persistence model.",
    ], size=11, width=88)
    p.text(MARGIN, 330, "Non-goals", size=14, font="F2")
    p.bullets(MARGIN, 312, [
        "Do not recreate every AWS internal implementation detail.",
        "Do not require cloud hosting for the simulator.",
        "Do not make the UI or frontend enforce licensing.",
        "Do not simulate a real hypervisor when a container is enough.",
    ], size=11, width=88)
    p.footer(10)
    pages.append(p)

    # Page 11
    p = Page()
    p.header("Master Layered Architecture", "This page captures the complete stack used for design and implementation decisions.")
    p.box(36, 676, 330, 44, "1. Experience Layer", [
        "Console, CLI, SDK, labs, and certification views all call the same documented cloud actions."
    ], fill=(0.97, 0.97, 0.92))
    p.box(36, 622, 330, 44, "2. API Contract Layer", [
        "Each service exposes request/response shapes, errors, state transitions, and pagination like the official docs."
    ], fill=(0.94, 0.96, 0.99))
    p.box(36, 568, 330, 44, "3. Routing Layer", [
        "Resolves service, region, account, resource, and entitlement context before execution."
    ], fill=(0.95, 0.98, 0.95))
    p.box(36, 514, 330, 44, "4. Simulation Kernel", [
        "Owns the resource graph, workflow engine, lifecycle transitions, event emission, and recovery."
    ], fill=(0.96, 0.95, 0.99))
    p.box(36, 460, 330, 44, "5. Shared Engines", [
        "Resource graph, lifecycle, policy, topology, runtime, event, and persistence engines stay reusable across services."
    ], fill=(0.95, 0.97, 0.99))
    p.box(36, 406, 330, 44, "6. Service Adapter Layer", [
        "S3, IAM, EC2, VPC, RDS, Lambda, SQS/SNS, CloudWatch, CloudFormation, containers, and edge services plug in here."
    ], fill=(0.98, 0.95, 0.96))
    p.box(36, 352, 330, 44, "7. Runtime Bundle Layer", [
        "Java, .NET, Go, PHP, and Python bundles provide turnkey local runtime environments."
    ], fill=(0.95, 0.98, 0.96))
    p.box(36, 298, 330, 44, "8. Local Host Layer", [
        "Containers, sandboxes, ports, volumes, metadata endpoints, and startup hooks run on the user's machine."
    ], fill=(0.96, 0.96, 0.94))
    p.box(36, 244, 330, 44, "9. Persistence Layer", [
        "SQLite, artifacts, encrypted tokens, audit history, event logs, and snapshots survive stop/start cycles."
    ], fill=(0.98, 0.95, 0.94))
    p.box(384, 676, 192, 44, "Governance", [
        "Credits, tiers, lockout, and signed licenses."
    ], fill=(0.99, 0.97, 0.92))
    p.box(384, 622, 192, 44, "Certification", [
        "Scenario packs, grading, hints, and progress."
    ], fill=(0.95, 0.97, 0.99))
    p.box(384, 568, 192, 44, "GitHub Deploy", [
        "Connect repos and deploy source into runtimes."
    ], fill=(0.96, 0.95, 0.98))
    p.box(384, 514, 192, 44, "Terraform", [
        "Import and export desired infrastructure state."
    ], fill=(0.95, 0.98, 0.94))
    p.box(384, 460, 192, 44, "Validation Mode", [
        "Compare simulator behavior with real AWS when enabled."
    ], fill=(0.98, 0.95, 0.95))
    p.box(384, 406, 192, 44, "Security", [
        "Signing, tamper detection, encryption, and cloud-only unlock."
    ], fill=(0.97, 0.95, 0.99))
    p.box(384, 352, 192, 44, "Provider Expansion", [
        "AWS first, then Azure and GCP through the same kernel."
    ], fill=(0.95, 0.96, 0.99))
    p.box(384, 298, 192, 44, "Docker Compose", [
        "Supported local launch path with persistent volumes."
    ], fill=(0.95, 0.98, 0.98))
    p.text(384, 246, "Master rule", size=14, font="F2")
    p.bullets(384, 228, [
        "Keep the user experience cloud-like.",
        "Keep the implementation lightweight.",
        "Keep the core provider-neutral.",
        "Keep state local and restartable.",
        "Keep premium features governed by entitlements.",
    ], size=10, width=36)
    p.footer(11)
    pages.append(p)

    # Page 12
    p = Page()
    p.header("Capability Packs and Lazy Activation", "Capabilities are delivered as signed packs that are downloaded and activated on demand.")
    p.text(MARGIN, 702, "Pack types", size=14, font="F2")
    p.bullets(MARGIN, 684, [
        "Service packs: S3, IAM, EC2, VPC, Lambda, RDS, queues, observability.",
        "Runtime packs: Java, .NET, Go, PHP, Python.",
        "Exercise packs: guided labs, scoring, hidden checks.",
        "Provider packs: AWS first, then Azure and GCP.",
    ], size=11, width=86)
    p.text(308, 702, "Pack lifecycle", size=14, font="F2")
    p.bullets(308, 684, [
        "Discover from a remote registry.",
        "Check entitlement and credits.",
        "Download the signed artifact.",
        "Verify signature and compatibility.",
        "Activate locally and cache for offline reuse.",
        "Update or roll back by version.",
    ], size=11, width=42)
    p.box(36, 364, 540, 116, "Pack structure", [
        "manifest.json, adapter code, API schemas, UI metadata, state model, tests, fixtures, and signature data.",
        "The pack should be versioned and can include optional runtime hooks or container references.",
        "A pack becomes visible in the catalog immediately, but its code only loads when a user or workflow needs it.",
    ], fill=(0.95, 0.98, 0.98))
    p.footer(12)
    pages.append(p)

    # Page 13
    p = Page()
    p.header("Pack Admission and Cloud-Agnostic Design", "A pack must speak the simulator API contract and remain cloud-neutral in its core logic.")
    p.box(36, 620, 540, 84, "Pack admission rules", [
        "A pack must provide documented actions, request schemas, response schemas, error mappings, state transitions, and region behavior where relevant.",
        "Admission checks include signature validation, version compatibility, entitlement validation, API contract validation, schema validation, and optional contract tests.",
    ], fill=(0.98, 0.95, 0.95))
    p.box(36, 512, 540, 84, "Cloud-agnostic pack model", [
        "The core capability logic should be provider-neutral. AWS, Azure, and GCP become provider adapters and profiles layered on top of the same capability model.",
        "The core owns resource behavior, lifecycle, workflow logic, persistence shape, and events. Provider adapters own API names, terminology, and request/response mapping.",
    ], fill=(0.95, 0.96, 0.99))
    p.text(MARGIN, 410, "MVP rule", size=14, font="F2")
    p.bullets(MARGIN, 392, [
        "Reject packs without AWS-like API support.",
        "Reject packs without valid schemas or transitions.",
        "Reject packs that hardcode provider behavior into the core capability logic.",
        "Require AWS first, but define Azure and GCP adapter slots from day one.",
    ], size=11, width=86)
    p.footer(13)
    pages.append(p)

    # Page 14
    p = Page()
    p.header("MVP Scope", "The MVP should be small, fast to install, and still feel like a real cloud workflow simulator.")
    p.box(36, 620, 540, 100, "MVP includes", [
        "Local control plane, AWS-style API-driven actioning, durable local state, Docker Compose deployment, free tier support, signed entitlement flow, capability packs, lazy activation, S3, IAM basics, EC2 basics backed by a local container runtime, VPC basics, one runtime bundle path, GitHub deploy, basic certification exercises, and tier/credit gating.",
    ], fill=(0.95, 0.98, 0.95))
    p.text(MARGIN, 498, "MVP defers", size=14, font="F2")
    p.bullets(MARGIN, 480, [
        "Full service catalog depth.",
        "RDS.",
        "Lambda.",
        "SQS / SNS.",
        "CloudWatch.",
        "CloudFormation.",
        "AWS validation mode.",
        "Terraform import/export at scale.",
        "Azure and GCP provider packs.",
        "Advanced multi-region behavior.",
    ], size=11, width=86)
    p.box(330, 180, 246, 160, "MVP success criteria", [
        "Users can sign up for Free.",
        "Install or start with Docker Compose.",
        "Create and manage S3 buckets.",
        "Launch a simple EC2-like workload locally.",
        "Run a basic lab and resume after restart.",
        "Activate packs lazily on first use.",
    ], fill=(0.98, 0.96, 0.94))
    p.footer(14)
    pages.append(p)

    builder = PDFBuilder()
    font_regular = builder.reserve()
    font_bold = builder.reserve()
    content_ids: list[int] = []
    page_ids: list[int] = []

    for _ in pages:
        content_ids.append(builder.reserve())
        page_ids.append(builder.reserve())

    pages_id = builder.reserve()
    catalog_id = builder.reserve()

    builder.set_object(font_regular, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    builder.set_object(font_bold, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    for page, content_id, page_id in zip(pages, content_ids, page_ids):
        content = page.content()
        builder.set_object(
            content_id,
            b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"endstream",
        )
        builder.set_object(
            page_id,
            (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("ascii"),
        )

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    builder.set_object(pages_id, f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii"))
    builder.set_object(catalog_id, f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))
    builder.build(path)


if __name__ == "__main__":
    out = Path("CLOUDLEARN_FULL_ARCHITECTURE.pdf")
    render(out)
    print(out.resolve())
