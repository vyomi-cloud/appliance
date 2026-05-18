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

    def raw(self, s: str) -> None:
        self.parts.append(s)

    def text(self, x: float, y: float, text: str, size: int = 11, font: str = "F1") -> None:
        self.parts.append(
            f"BT /{font} {size} Tf {fmt(x)} {fmt(y)} Td ({esc(text)}) Tj ET"
        )

    def multiline(
        self,
        x: float,
        y: float,
        text: str,
        size: int = 11,
        leading: int | None = None,
        font: str = "F1",
        width: int = 90,
    ) -> None:
        leading = leading or int(size * 1.35)
        lines = wrap(text, width=width) if text else [""]
        self.parts.append(f"BT /{font} {size} Tf {fmt(x)} {fmt(y)} Td")
        for idx, line in enumerate(lines):
            if idx == 0:
                self.parts.append(f"({esc(line)}) Tj")
            else:
                self.parts.append(f"T* ({esc(line)}) Tj")
        self.parts.append("ET")

    def bullet_list(
        self,
        x: float,
        y: float,
        items: list[str],
        size: int = 11,
        leading: int | None = None,
        width: int = 85,
    ) -> None:
        leading = leading or int(size * 1.35)
        cur_y = y
        for item in items:
            lines = wrap(item, width=width)
            self.text(x, cur_y, f"- {lines[0]}", size=size)
            cur_y -= leading
            for cont in lines[1:]:
                self.text(x + 14, cur_y, cont, size=size)
                cur_y -= leading
        return

    def box(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        body: list[str],
        fill: tuple[float, float, float] = (0.965, 0.975, 0.985),
        stroke: tuple[float, float, float] = (0.30, 0.35, 0.42),
        title_fill: tuple[float, float, float] = (0.16, 0.21, 0.28),
    ) -> None:
        self.parts.append(
            f"q {fmt(fill[0])} {fmt(fill[1])} {fmt(fill[2])} rg {fmt(stroke[0])} {fmt(stroke[1])} {fmt(stroke[2])} RG "
            f"{fmt(x)} {fmt(y)} {fmt(w)} {fmt(h)} re B Q"
        )
        self.text(x + 8, y + h - 16, title, size=10, font="F2")
        cy = y + h - 30
        for line in body:
            wrapped = wrap(line, width=max(18, int(w / 4.8)))
            for seg in wrapped:
                if cy < y + 10:
                    break
                self.text(x + 8, cy, seg, size=8)
                cy -= 10

    def arrow(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.parts.append(f"q 0.25 w {fmt(x1)} {fmt(y1)} m {fmt(x2)} {fmt(y2)} l S Q")
        dx = x2 - x1
        dy = y2 - y1
        length = (dx * dx + dy * dy) ** 0.5 or 1.0
        ux = dx / length
        uy = dy / length
        left_x = x2 - 8 * ux + 4 * uy
        left_y = y2 - 8 * uy - 4 * ux
        right_x = x2 - 8 * ux - 4 * uy
        right_y = y2 - 8 * uy + 4 * ux
        self.parts.append(
            f"q 0.25 w {fmt(x2)} {fmt(y2)} m {fmt(left_x)} {fmt(left_y)} l S "
            f"{fmt(x2)} {fmt(y2)} m {fmt(right_x)} {fmt(right_y)} l S Q"
        )

    def header(self, title: str, subtitle: str = "") -> None:
        self.text(MARGIN, PAGE_H - 48, title, size=20, font="F2")
        if subtitle:
            self.text(MARGIN, PAGE_H - 68, subtitle, size=10)
        self.parts.append(
            f"q 0.70 0.74 0.80 rg {MARGIN} {PAGE_H - 78} {PAGE_W - 2 * MARGIN} 1.2 re f Q"
        )

    def footer(self, page_no: int) -> None:
        self.parts.append(
            f"q 0.82 0.82 0.82 rg {MARGIN} 28 {PAGE_W - 2 * MARGIN} 0.8 re f Q"
        )
        self.text(MARGIN, 16, "CloudLearn LLD", size=9)
        self.text(PAGE_W - MARGIN - 46, 16, f"Page {page_no}", size=9)

    def content(self) -> bytes:
        return ("\n".join(self.parts) + "\n").encode("ascii")


def make_pdf(path: Path) -> None:
    pages: list[Page] = []

    # Page 1: objective and design principles
    p = Page()
    p.header(
        "CloudLearn Simulator - Low Level Design",
        "Local-first cloud simulator with AWS-compatible workflows and pluggable runtime bundles",
    )
    p.text(MARGIN, 700, "1. Objective", size=14, font="F2")
    p.multiline(
        MARGIN,
        680,
        (
            "CloudLearn is a local-first cloud simulator that gives users an AWS-like "
            "experience for learning, app validation, and workflow practice without "
            "cloud hosting or cloud licenses."
        ),
        size=11,
        width=92,
    )
    p.text(MARGIN, 612, "2. Design Principles", size=14, font="F2")
    p.bullet_list(
        MARGIN,
        592,
        [
            "Simulate the workflow, not the internal AWS implementation.",
            "Keep the core provider-neutral so Azure and GCP can be added later.",
            "Prefer lightweight local implementations over heavy emulation.",
            "Persist state locally so simulator restarts preserve workflows.",
            "Expose AWS compatibility at the adapter boundary.",
            "Treat runtime environments as pluggable bundles.",
        ],
        size=11,
        width=86,
    )
    p.text(MARGIN, 420, "3. What the product must do", size=14, font="F2")
    p.bullet_list(
        MARGIN,
        400,
        [
            "Run entirely on the user's machine.",
            "Expose AWS-compatible APIs for common workflows.",
            "Provide lightweight runtime environments for Java, .NET, Go, PHP, and Python.",
            "Support local start, stop, and resume with durable state.",
            "Allow optional validation against real AWS.",
            "Export and import desired state through Terraform later.",
        ],
        size=11,
        width=86,
    )
    p.footer(1)
    pages.append(p)

    # Page 2: architecture diagram
    p = Page()
    p.header("4. Logical Architecture", "The control plane is local. The cloud behavior is simulated through adapters and runtime bundles.")
    p.box(36, 610, 110, 66, "User Entry", ["Console", "CLI", "AWS SDK"], fill=(0.96, 0.96, 0.92))
    p.box(164, 610, 120, 66, "API Gateway", ["AWS-style routing", "SigV4 acceptance", "Error translation"], fill=(0.93, 0.96, 0.99))
    p.box(302, 600, 128, 76, "Simulation Kernel", ["Resource lifecycle", "Workflow engine", "Failure and latency model"], fill=(0.91, 0.95, 0.93))
    p.box(450, 610, 120, 66, "Local State", ["SQLite", "Artifacts", "Event log"], fill=(0.98, 0.95, 0.94))
    p.box(164, 470, 120, 66, "Service Adapters", ["S3", "IAM", "Compute", "Network", "RDS", "Lambda"], fill=(0.95, 0.94, 0.99))
    p.box(302, 470, 128, 66, "Runtime Manager", ["Start/stop workloads", "Inject env vars", "Health and logs"], fill=(0.95, 0.98, 0.95))
    p.box(450, 470, 120, 66, "Validation Mode", ["Optional real AWS", "Parity checks", "Workflow compare"], fill=(0.98, 0.98, 0.92))
    p.box(302, 330, 128, 66, "Runtime Bundles", ["Java", ".NET", "Go", "PHP", "Python"], fill=(0.94, 0.97, 0.98))
    p.box(450, 330, 120, 66, "Local Workloads", ["App containers", "Sandboxed processes"], fill=(0.95, 0.94, 0.97))
    p.box(302, 190, 268, 76, "Terraform Bridge", ["Import simulator state into desired infrastructure", "Export simulator model to Terraform for real cloud rollout"], fill=(0.96, 0.96, 0.99))
    p.arrow(146, 643, 164, 643)
    p.arrow(284, 643, 302, 643)
    p.arrow(430, 643, 450, 643)
    p.arrow(366, 600, 366, 536)
    p.arrow(224, 470, 224, 536)
    p.arrow(366, 470, 366, 396)
    p.arrow(510, 470, 510, 396)
    p.arrow(366, 330, 366, 266)
    p.arrow(450, 330, 510, 330)
    p.arrow(302, 230, 302, 230)
    p.multiline(
        MARGIN,
        146,
        (
            "The kernel is the source of truth. Adapters translate AWS-like requests "
            "into simulator state changes. Runtime bundles are plugged into the runtime "
            "manager and provide language-specific execution templates."
        ),
        size=10,
        width=100,
    )
    p.footer(2)
    pages.append(p)

    # Page 3: workflows
    p = Page()
    p.header("5. Core Workflows", "Each workflow is stateful and restartable because state is persisted locally.")
    y = 702
    workflow_blocks = [
        (
            "Create Bucket",
            [
                "1. User invokes console, CLI, or SDK action.",
                "2. Gateway normalizes request and region.",
                "3. Kernel validates policy and naming rules.",
                "4. S3 adapter updates local state.",
                "5. State is flushed to SQLite and event log.",
            ],
        ),
        (
            "Deploy Lightweight App",
            [
                "1. User selects a runtime bundle.",
                "2. Runtime manager resolves the bundle.",
                "3. Code is mounted or packaged locally.",
                "4. Workload starts in a local sandbox or container.",
                "5. Simulated endpoints and env vars are injected.",
            ],
        ),
        (
            "Stop and Resume Simulator",
            [
                "1. Simulator stop signal arrives.",
                "2. Kernel persists state and artifacts.",
                "3. Runtime manager stops active workloads.",
                "4. Restart reloads state from local storage.",
                "5. UI reconnects to the existing workflow state.",
            ],
        ),
        (
            "Validate Against Real AWS",
            [
                "1. Enable validation mode.",
                "2. Run the same workflow against simulator and AWS.",
                "3. Compare responses, errors, and state transitions.",
                "4. Surface mismatches for training or verification.",
            ],
        ),
        (
            "Export to Terraform",
            [
                "1. Kernel serializes the desired resource graph.",
                "2. Bridge maps simulator resources to IaC.",
                "3. Exported Terraform can be applied to real AWS later.",
                "4. Import can also recreate simulator state from IaC.",
            ],
        ),
    ]
    for title, lines in workflow_blocks:
        p.box(36, y - 94, 540, 84, title, lines, fill=(0.98, 0.99, 0.99))
        y -= 100
    p.footer(3)
    pages.append(p)

    # Page 4: data model and runtime bundles
    p = Page()
    p.header("6. Data Model and Runtime Contracts", "Persistence and execution are modeled explicitly so that restart and bundle selection stay deterministic.")
    p.text(MARGIN, 702, "6.1 Core Tables", size=14, font="F2")
    p.bullet_list(
        MARGIN,
        682,
        [
            "accounts",
            "regions",
            "resources",
            "resource_versions",
            "workflow_runs",
            "workflow_steps",
            "runtime_instances",
            "runtime_bundles",
            "events",
            "artifacts",
            "validation_runs",
            "terraform_exports",
        ],
        size=11,
        width=20,
    )
    p.text(230, 702, "6.2 Resource Graph", size=14, font="F2")
    p.box(224, 620, 140, 62, "Resource Graph", ["bucket -> objects", "role -> policy attachments", "instance -> subnet -> vpc"], fill=(0.94, 0.98, 0.94))
    p.box(384, 620, 150, 62, "Internal Contract", ["create", "update", "delete", "query", "emit event", "persist snapshot"], fill=(0.94, 0.97, 0.99))
    p.box(224, 530, 140, 62, "Runtime Bundle API", ["supports()", "prepare()", "start()", "stop()", "health()", "logs()"], fill=(0.99, 0.97, 0.94))
    p.box(384, 530, 150, 62, "Language Bundles", ["Java", ".NET", "Go", "PHP", "Python"], fill=(0.97, 0.94, 0.98))
    p.arrow(364, 651, 384, 651)
    p.arrow(294, 620, 294, 592)
    p.arrow(459, 620, 459, 592)
    p.text(MARGIN, 424, "6.3 Runtime Bundle Contract", size=14, font="F2")
    p.bullet_list(
        MARGIN,
        404,
        [
            "Each bundle declares supported languages and frameworks.",
            "Bundles encapsulate startup templates and health checks.",
            "Bundles keep language-specific behavior out of the kernel.",
            "The runtime manager treats all bundles through the same interface.",
        ],
        size=11,
        width=78,
    )
    p.footer(4)
    pages.append(p)

    # Page 5: deployment and expansion path
    p = Page()
    p.header("7. Deployment and Expansion Path", "Start local, keep the product offline-capable, and expand provider coverage later.")
    p.box(36, 610, 168, 76, "Local Host", ["Console", "Kernel", "State store", "Runtime manager", "Terraform bridge"], fill=(0.95, 0.95, 0.98))
    p.box(224, 610, 160, 76, "Runtime Plane", ["Container sandbox", "Language bundles", "Local workloads"], fill=(0.95, 0.98, 0.95))
    p.box(404, 610, 168, 76, "Validation / Export", ["Compare with AWS", "Generate Terraform", "Import IaC"], fill=(0.98, 0.95, 0.95))
    p.arrow(204, 648, 224, 648)
    p.arrow(384, 648, 404, 648)
    p.text(MARGIN, 520, "Recommended v1 stack", size=14, font="F2")
    p.bullet_list(
        MARGIN,
        500,
        [
            "Backend: Python or Java depending on the current implementation path.",
            "Persistence: SQLite plus local files.",
            "Runtime layer: containers or sandboxes.",
            "UI: React console.",
            "Compatibility: AWS-style adapters per service.",
            "Terraform: bidirectional export/import translator.",
        ],
        size=11,
        width=88,
    )
    p.text(MARGIN, 332, "Expansion path", size=14, font="F2")
    p.bullet_list(
        MARGIN,
        312,
        [
            "AWS-first simulator with S3, IAM, compute, and runtime bundles.",
            "Add validation mode against real AWS.",
            "Add Terraform export/import parity.",
            "Add Azure provider profile.",
            "Add GCP provider profile.",
        ],
        size=11,
        width=88,
    )
    p.text(300, 332, "Non-goals", size=14, font="F2")
    p.bullet_list(
        300,
        312,
        [
            "Recreating every AWS internal behavior.",
            "Building a distributed cloud control plane on day one.",
            "Simulating hardware-level VM behavior when a container is enough.",
        ],
        size=11,
        width=42,
    )
    p.footer(5)
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
        builder.set_object(
            content_id,
            b"<< /Length "
            + str(len(page.content())).encode("ascii")
            + b" >>\nstream\n"
            + page.content()
            + b"endstream",
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
    builder.set_object(
        pages_id,
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii"),
    )
    builder.set_object(catalog_id, f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))

    builder.build(path)


if __name__ == "__main__":
    out = Path("CLOUDLEARN_LLD.pdf")
    make_pdf(out)
    print(out.resolve())
