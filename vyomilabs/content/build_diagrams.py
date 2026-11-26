"""Draws the 14-layer enterprise agentic AI reference diagram for each cloud (wasm/labs/img/{aws,gcp,azure}.svg) as our OWN artwork:
own icons (simple stroke glyphs), own palette and layout, that cloud's native service names. The structure (layers, flows, legend) follows the
published layer model the course is built on; no third-party artwork is embedded. Hotspots come from here (panel rectangles) so the page and the
diagram can never drift apart.  Run: python -m vyomilabs.content.build_diagrams"""
import json
import os
import textwrap
from xml.sax.saxutils import escape

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "wasm", "labs")
W, H = 1800, 1270
COL = dict(purple="#7c3aed", blue="#2563eb", red="#dc2626", teal="#0f766e", orange="#ea580c", green="#15803d", ink="#111827", mute="#4b5563")
LAYER_COLOR = {1: "purple", 2: "blue", 3: "blue", 4: "purple", 5: "red", 6: "blue", 7: "teal", 8: "orange", 9: "blue", 10: "purple", 11: "teal", 12: "green", 13: "purple", 14: "green"}

# ---- panels (x1, y1, x2, y2) in diagram units; also the click hotspots
CX = [10, 208, 406, 744, 967, 1210, 1408, 1606]
CW = [180, 180, 320, 205, 225, 180, 180, 184]
TOP = 124
BOT = {1: 850, 2: 770, 3: 850, 4: 850, 5: 850, 6: 800, 7: 850, 8: 850}
R2T, R2B, GT, GB = 888, 1092, 1116, 1256
PANEL = {i + 1: (CX[i], TOP, CX[i] + CW[i], BOT[i + 1]) for i in range(8)}
PANEL.update({10: (10, R2T, 480, R2B), 9: (498, R2T, 900, R2B), 11: (918, R2T, 1196, R2B), 12: (1214, R2T, 1790, R2B), 13: (10, GT, 1450, GB)})
PANEL[14] = (PANEL[12][0] + 20, PANEL[12][1] + 178, PANEL[12][2] - 20, PANEL[12][3] - 6)       # a slim strip at the foot of the pipeline panel: the design the pipeline and search build to
HOTSPOTS = {k: list(v) for k, v in PANEL.items()}
HOTSPOTS[12] = [PANEL[12][0], PANEL[12][1], PANEL[12][2], PANEL[12][1] + 174]              # so the strip is clickable on its own

# ---- cloud-native vocabulary (what the reference app really uses per cloud)
T = {
 "aws": dict(name="AWS", authn=("Amazon Cognito", "user authentication"), edge=("Amazon API Gateway", "front door for tools"), waf=("AWS WAF", "rate-based rules"), idp="Cognito",
             runtime="AgentCore Runtime", fw=("Strands", "LangGraph"), gw="AgentCore Gateway", policy="Cedar policy", guard="Bedrock Guardrails",
             approval=("Durable approval state", "Step Functions · waitForTaskToken"), ledger="DynamoDB approval ledger", search=("Bedrock Knowledge Bases", "OpenSearch vector store"), rerank="Bedrock Rerank",
             tools="Tools (AWS Lambda)", telem=("Amazon CloudWatch", "X-Ray · metrics · logs"), models=("Bedrock Runtime", "Nano / Mesh models"), mem="AgentCore Memory",
             pipe=[("Amazon S3", "source docs"), ("Extraction", "+ guardrails scan"), ("Chunking", "& parsing"), ("Embeddings", "hosted embedding model"), ("Vector store", "OpenSearch")],
             gov=[("Identity & access", "IAM · Cognito"), ("Encryption", "AWS KMS"), ("Audit logs", "CloudTrail"), ("Safety & policy", "Guardrails"), ("Data governance", "lineage · retention"), ("Policy controls", "access reviews"), ("Cost tracking", "& optimisation")],
             eval_="AgentCore Evaluations", short_mem="AgentCore Memory"),
 "gcp": dict(name="Google Cloud", authn=("Identity Platform", "user sign-in"), edge=("API Gateway", "front door for tools"), waf=("Cloud Armor", "WAF security policy"), idp="Identity Platform",
             runtime="Vertex AI Agent Engine", fw=("Agent Dev Kit", "LangGraph"), gw="Agent Gateway", policy="Cedar agent policy", guard="Model Armor",
             approval=("Durable approval state", "Pub/Sub + Cloud Run function"), ledger="Firestore approval ledger", search=("Vertex AI RAG Engine", "retrieveContexts"), rerank="Vertex AI ranking",
             tools="Tools (Cloud Run functions)", telem=("Cloud Operations", "Trace · Logging · Monitoring"), models=("Model Garden", "Nano / Mesh models"), mem="Sessions + Memory Bank",
             pipe=[("Cloud Storage", "source docs"), ("Eventarc", "+ function"), ("Chunking", "& parsing"), ("Embeddings", "hosted embedding model"), ("Vector store", "RAG Engine corpus")],
             gov=[("Identity & access", "IAM · Identity Platform"), ("Encryption", "Cloud KMS"), ("Audit logs", "Cloud Audit Logs"), ("Safety & policy", "Model Armor"), ("Data governance", "lineage · retention"), ("Policy controls", "access reviews"), ("Cost tracking", "& optimisation")],
             eval_="Agent evaluation", short_mem="Sessions + Memory Bank"),
 "azure": dict(name="Microsoft Azure", authn=("Microsoft Entra ID", "user sign-in"), edge=("API Management", "validate-jwt policy"), waf=("Front Door WAF", "managed rules"), idp="Entra ID",
               runtime="Foundry Agents + Container Apps", fw=("Foundry Agents SDK", "LangGraph"), gw="API Management gateway", policy="APIM policy expressions", guard="AI Content Safety",
               approval=("Durable approval state", "Service Bus + Function App"), ledger="Azure Table approval ledger", search=("Azure AI Search", "BM25 · vector · hybrid"), rerank="Semantic ranker",
               tools="Tools (Azure Functions)", telem=("Azure Monitor", "App Insights · Log Analytics"), models=("Azure OpenAI deployments", "Nano / Mesh models"), mem="Threads + app-level memory",
               pipe=[("Blob Storage", "source docs"), ("Event Grid", "+ function"), ("Indexer", "chunking"), ("Embeddings", "hosted embedding model"), ("Search index", "AI Search")],
               gov=[("Identity & access", "Entra RBAC"), ("Encryption", "Key Vault"), ("Audit logs", "Activity Log"), ("Safety & policy", "Content Safety"), ("Data governance", "lineage · retention"), ("Policy controls", "access reviews"), ("Cost tracking", "& optimisation")],
               eval_="Foundry evaluations", short_mem="Threads + app-level memory"),
}

# ---- own icon set: 24x24 stroke glyphs
ICON = {
 "user": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 3.6-7 8-7s8 3 8 7",
 "users": "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2.5 20c0-3.3 2.9-5.5 6.5-5.5s6.5 2.2 6.5 5.5M16 11a2.6 2.6 0 1 0 0-5.2M18 14.8c2.2.5 3.7 2.2 3.7 5.2",
 "shield": "M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6l8-3zM8.5 12l2.5 2.5 4.5-5",
 "gear": "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12l2-1-1.5-3-2.2.6-1.6-1.6.6-2.2-3-1.5-1 2h-2.6l-1-2-3 1.5.6 2.2L4.7 8.6 2.5 8 1 11l2 1v2l-2 1 1.5 3 2.2-.6 1.6 1.6-.6 2.2 3 1.5 1-2h2.6l1 2 3-1.5-.6-2.2 1.6-1.6 2.2.6L22 15l-2-1v-2z",
 "db": "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
 "doc": "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
 "cloud": "M7 18a4.5 4.5 0 0 1-.6-9A6 6 0 0 1 18 9.5 4 4 0 0 1 17.5 18z",
 "lock": "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3M12 14.5v2.5",
 "search": "M10.5 18a7.5 7.5 0 1 0 0-15 7.5 7.5 0 0 0 0 15zM16 16l5 5",
 "chart": "M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-7",
 "wrench": "M14.5 6a4 4 0 0 0 4.7 5.2l-8.7 8.7a2.2 2.2 0 0 1-3.1-3.1l8.7-8.7A4 4 0 0 0 14.5 6z",
 "building": "M5 21V4h9v17M14 9h5v12M8 8h3M8 12h3M8 16h3M3 21h18",
 "monitor": "M3 5h18v11H3zM9 20h6M12 16v4",
 "phone": "M8 2h8a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1zM11 19h2",
 "chat": "M4 5h16v11H9l-5 4zM8 10h.01M12 10h.01M16 10h.01",
 "code": "M9 7l-5 5 5 5M15 7l5 5-5 5M13 5l-2 14",
 "mail": "M3 6h18v12H3zM3 7l9 7 9-7",
 "graph": "M6 6a2 2 0 1 0 0-.01M18 5a2 2 0 1 0 0-.01M18 19a2 2 0 1 0 0-.01M6 12a2 2 0 1 0 0-.01M8 11l8-5M8 13l8 5",
 "check": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM8 12l3 3 5-6",
 "play": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM10 8.5v7l6-3.5z",
 "refresh": "M20 11a8 8 0 0 0-14-4L4 9M4 4v5h5M4 13a8 8 0 0 0 14 4l2-2M20 20v-5h-5",
 "warn": "M12 3l10 18H2zM12 10v5M12 18h.01",
 "timer": "M12 21a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM12 9v4l2.5 2M9.5 2h5",
 "cube": "M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12L4 7.5M12 12v9",
 "pin": "M12 21s7-6 7-11a7 7 0 1 0-14 0c0 5 7 11 7 11zM12 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
 "thumb": "M7 11v9H4v-9zM7 11l4-8c1.5 0 2.5 1 2.2 2.6L12.5 9H19a2 2 0 0 1 2 2.4l-1.2 6A2 2 0 0 1 17.8 19H7",
 "dollar": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM14.5 9.2C14 8.4 13.2 8 12 8c-1.5 0-2.5.7-2.5 1.8 0 3 5 1.4 5 4.2 0 1.1-1 1.9-2.5 1.9-1.3 0-2.2-.5-2.7-1.4M12 6.5V8M12 16v1.5",
 "bucket": "M5 7c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3zM5 7l1.5 12c.2 1 2.6 2 5.5 2s5.3-1 5.5-2L19 7",
 "chip": "M7 7h10v10H7zM10 10h4v4h-4zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4",
 "scan": "M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M8 12h8",
 "func": "M14 4c-2.5 0-3 1.5-3.4 4L10 13c-.4 2.5-1 4-3.5 4M8 10h7M10 20l5-8",
 "key": "M8 14a4 4 0 1 1 3.9-4.9L21 9v3h-2v2h-2v2h-3l-1.6-1.6A4 4 0 0 1 8 14z",
 "list": "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01",
 "clip": "M8 4h8v3H8zM6 5h12v16H6zM9 12h6M9 16h6",
 "eye": "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
 "brain": "M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 2.8A3 3 0 0 0 5 13a3.2 3.2 0 0 0 3 4.5A3 3 0 0 0 12 20V4a3 3 0 0 0-3 0zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 2.8A3 3 0 0 1 19 13a3.2 3.2 0 0 1-3 4.5A3 3 0 0 1 12 20",
 "bolt": "M13 2L4 14h7l-1 8 9-12h-7z",
 "layers": "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5",
 "route": "M6 19a2 2 0 1 0 0-.01M18 5a2 2 0 1 0 0-.01M8 19h6a4 4 0 0 0 0-8h-4a4 4 0 0 1 0-8h6",
}


class D:
    def __init__(self):
        self.o = []

    def add(self, s):
        self.o.append(s)

    def rect(self, x1, y1, x2, y2, stroke, fill="#fff", r=10, sw=2, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def text(self, x, y, s, fs=14, weight=400, fill=None, anchor="start", italic=False):
        fill = fill or COL["ink"]
        st = ' font-style="italic"' if italic else ""
        self.add(f'<text x="{x}" y="{y}" font-size="{fs}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{st}>{escape(s)}</text>')

    def lines(self, x, y, s, w, fs=13, weight=400, fill=None, lh=None, anchor="start", maxl=4):
        lh = lh or fs * 1.28
        n = max(6, int(w / (fs * (0.60 if weight >= 700 else 0.545))))
        k = 0
        for ln in textwrap.wrap(s, n)[:maxl]:
            self.text(x, y + k * lh, ln, fs, weight, fill, anchor); k += 1
        return y + k * lh

    def icon(self, name, x, y, s=24, color="#111", sw=1.7):
        k = s / 24.0
        self.add(f'<g transform="translate({x},{y}) scale({k})" fill="none" stroke="{color}" stroke-width="{sw / k if k else sw}" stroke-linecap="round" stroke-linejoin="round"><path d="{ICON[name]}"/></g>')

    def badge(self, x, y, n, color):
        self.add(f'<circle cx="{x}" cy="{y}" r="19" fill="{COL[color]}"/><text x="{x}" y="{y+6}" font-size="18" font-weight="800" fill="#fff" text-anchor="middle">{n}</text>')

    def arrow(self, pts, color="blue", dash=None, width=2.4):
        d = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(pts))
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<path d="{d}" fill="none" stroke="{COL[color]}" stroke-width="{width}"{da} marker-end="url(#ah-{color})" stroke-linejoin="round"/>')

    def panel(self, lid, title, sub=None, tfs=17):
        x1, y1, x2, y2 = PANEL[lid]
        c = COL[LAYER_COLOR[lid]]
        self.add(f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" rx="12" fill="{c}0d" stroke="{c}" stroke-width="2.4"/>')
        cx = (x1 + x2) / 2
        if lid in (9, 10, 11, 12):   # bottom row: badge left, title beside it
            self.badge(x1 + 30, y1 + 30, lid, LAYER_COLOR[lid])
            self.text(x1 + 58, y1 + 36, title, 18, 800, c)
            if sub: self.text(x1 + 58 + len(title) * 9.8 + 8, y1 + 36, sub, 12.5, 400, COL["mute"])
        else:
            self.badge(cx, y1, lid, LAYER_COLOR[lid])
            ty = y1 + 46
            for ln in textwrap.wrap(title, max(8, int((x2 - x1 - 16) / (tfs * 0.56))))[:2]:
                self.text(cx, ty, ln, tfs, 800, c, "middle"); ty += tfs * 1.2
            if sub: self.text(cx, ty, sub, 12, 400, COL["mute"], "middle")

    def card(self, x1, y1, x2, y2, c, icon, title, sub=None, tfs=13.5, ifs=26, sfs=11):
        self.rect(x1, y1, x2, y2, COL[c] + "66", "#fff", 9, 1.6)
        cy = (y1 + y2) / 2
        self.add(f'<rect x="{x1+8}" y="{cy-19}" width="38" height="38" rx="9" fill="{COL[c]}14"/>')
        self.icon(icon, x1 + 14, cy - 13, ifs, COL[c])
        w = x2 - x1 - 60
        tl = textwrap.wrap(title, max(6, int(w / (tfs * 0.60)))); sl = textwrap.wrap(sub, max(6, int(w / (sfs * 0.545)))) if sub else []
        tot = len(tl) * tfs * 1.25 + len(sl) * sfs * 1.25
        y = cy - tot / 2 + tfs
        for ln in tl: self.text(x1 + 54, y, ln, tfs, 700); y += tfs * 1.25
        y += 1
        for ln in sl: self.text(x1 + 54, y - 3, ln, sfs, 400, COL["mute"]); y += sfs * 1.25


def draw(cloud):
    t = T[cloud]
    d = D()
    d.add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Inter,\'Segoe UI\',system-ui,-apple-system,Roboto,Arial,sans-serif" role="img" aria-label="Building an agentic AI solution on {t["name"]}: reference architecture, 13 layers">')
    d.add("<defs>" + "".join(f'<marker id="ah-{k}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M1 1L9 5L1 9z" fill="{v}"/></marker>' for k, v in COL.items() if k in ("blue", "purple", "green", "red")) + "</defs>")
    d.add(f'<rect width="{W}" height="{H}" fill="#fff"/>')
    d.text(W / 2, 44, f"Building an Agentic AI Solution on {t['name']}", 34, 800, COL["ink"], "middle")
    d.text(W / 2, 72, "A reference architecture: 14 layers, built one at a time on the Vyomi simulator", 16, 400, COL["mute"], "middle")
    # telemetry line
    d.add(f'<path d="M{PANEL[3][0]+160},100 H{PANEL[8][0]+92}" stroke="{COL["purple"]}" stroke-width="2" stroke-dasharray="7 5" fill="none"/>')
    d.add('<rect x="1040" y="88" width="310" height="22" fill="#fff"/>')
    d.text(1195, 105, "Send agent traces, metrics and logs", 13, 600, COL["purple"], "middle")
    d.arrow([(PANEL[3][0] + 160, 100), (PANEL[3][0] + 160, TOP - 18)], "purple", "7 5", 2); d.arrow([(PANEL[8][0] + 92, 100), (PANEL[8][0] + 92, TOP - 18)], "purple", "7 5", 2)

    # 1 Access
    x1, y1, x2, y2 = PANEL[1]; d.panel(1, "Access & Perimeter Security")
    for i, (ic, a, b) in enumerate((("user", *t["authn"]), ("route", *t["edge"]), ("shield", *t["waf"]))):
        d.card(x1 + 10, y1 + 78 + i * 78, x2 - 10, y1 + 78 + i * 78 + 70, "purple", ic, a, b)
    uy = y1 + 322
    d.rect(x1 + 10, uy, x2 - 10, uy + 190, COL["ink"] + "55", "#fff", 10, 1.8)
    d.icon("users", (x1 + x2) / 2 - 18, uy + 12, 36, COL["ink"]); d.text((x1 + x2) / 2, uy + 70, "Facilities Users", 15, 800, COL["ink"], "middle")
    for i, s in enumerate(("Facility managers", "Maintenance engineers", "Operations team", "Web / mobile / chat")):
        d.text(x1 + 24, uy + 98 + i * 22, "• " + s, 12.5, 400, COL["mute"])
    d.arrow([((x1 + x2) / 2, y1 + 78 + 3 * 78 - 6), ((x1 + x2) / 2, uy - 2)], "blue")
    d.arrow([((x1 + x2) / 2, uy + 190), ((x1 + x2) / 2, R2T - 6)], "blue"); d.text((x1 + x2) / 2 + 8, R2T - 22, f"user identity & token ({t['idp']})", 11.5, 400, COL["mute"])

    # 2 Channels
    x1, y1, x2, y2 = PANEL[2]; d.panel(2, "Channels & Interface")
    for i, (ic, s) in enumerate((("monitor", "Web UI"), ("phone", "Mobile app"), ("chat", "Chatbot"), ("code", "API"))):
        d.card(x1 + 10, y1 + 78 + i * 52, x2 - 10, y1 + 78 + i * 52 + 46, "blue", ic, s)
    d.rect(x1 + 10, y1 + 296, x2 - 10, y1 + 402, COL["blue"] + "66", "#fff", 9, 1.6)
    d.icon("shield", x1 + 18, y1 + 306, 26, COL["blue"]); d.text(x1 + 52, y1 + 326, "Input guardrails", 13.5, 700)
    d.text(x1 + 20, y1 + 352, "• Prompt filtering", 12, 400, COL["mute"]); d.text(x1 + 20, y1 + 372, "• Threat protection", 12, 400, COL["mute"]); d.text(x1 + 20, y1 + 392, "• " + t["guard"], 12, 400, COL["mute"])
    d.rect(x1 + 10, y1 + 414, x2 - 10, y1 + 506, COL["blue"] + "66", "#fff", 9, 1.6)
    d.icon("mail", x1 + 18, y1 + 424, 26, COL["blue"]); d.text(x1 + 52, y1 + 444, "Approver inbox", 13.5, 700)
    d.lines(x1 + 20, y1 + 470, "Notifications for pending approvals", x2 - x1 - 36, 12, 400, COL["mute"], maxl=2)
    d.arrow([(PANEL[1][2], 255), (PANEL[2][0], 255)], "blue"); d.arrow([(PANEL[2][2], 255), (PANEL[3][0], 255)], "blue")

    # 3 Runtime
    x1, y1, x2, y2 = PANEL[3]; d.panel(3, t["runtime"], "session-isolated", 17)
    d.rect(x1 + 14, y1 + 84, x2 - 14, y1 + 134, COL["ink"] + "99", "#fff", 9, 1.8); d.icon("user", x1 + 26, y1 + 96, 26, COL["ink"])
    d.text(x1 + 64, y1 + 108, "Supervisor agent", 15, 800); d.text(x1 + 64, y1 + 126, "Orchestrator: plan · route · synthesise", 11.5, 400, COL["mute"])
    aw = (x2 - x1 - 28 - 16) / 3
    for i, (ic, a, b) in enumerate((("building", "Facilities agent", "sites, space & access"), ("wrench", "Maintenance agent", "work orders & assets"), ("chart", "Analytics agent", "KPIs & insights"))):
        ax = x1 + 14 + i * (aw + 8)
        d.rect(ax, y1 + 160, ax + aw, y1 + 290, COL["blue"] + "77", "#fff", 9, 1.6); d.icon(ic, ax + aw / 2 - 15, y1 + 170, 30, COL["blue"])
        d.lines(ax + aw / 2, y1 + 220, a, aw - 8, 12.5, 700, anchor="middle", maxl=2); d.lines(ax + aw / 2, y1 + 252, b, aw - 8, 10.5, 400, COL["mute"], anchor="middle", maxl=2)
        d.arrow([(ax + aw / 2, y1 + 134), (ax + aw / 2, y1 + 158)], "blue", None, 1.8)
    d.rect(x1 + 14, y1 + 312, x2 - 14, y1 + 462, COL["blue"] + "99", "#fff", 10, 1.8, "6 4"); d.text((x1 + x2) / 2, y1 + 336, "Agent harness", 15, 800, COL["blue"], "middle")
    for i, (ic, a) in enumerate((("db", "Step · token · cost budgets"), ("doc", "Checkpoints"), ("timer", "Timeouts & kill switch"))):
        ax = x1 + 24 + i * (aw + 3)
        d.icon(ic, ax + aw / 2 - 14, y1 + 348, 28, COL["blue"]); d.lines(ax + aw / 2, y1 + 402, a, aw - 4, 11.5, 600, anchor="middle", maxl=3)
    d.rect(x1 + 14, y1 + 488, x2 - 14, y1 + 570, COL["blue"] + "77", "#fff", 10, 1.8); d.text((x1 + x2) / 2, y1 + 514, "Agent framework", 15, 800, COL["ink"], "middle")
    d.icon("graph", x1 + 30, y1 + 524, 30, COL["blue"]); d.text(x1 + 74, y1 + 548, f"{t['fw'][0]}  |  {t['fw'][1]}", 14, 600)
    d.arrow([((x1 + x2) / 2, y1 + 486), ((x1 + x2) / 2, y1 + 464)], "blue", None, 1.8)
    d.arrow([((x1 + x2) / 2, y1 + 570), ((x1 + x2) / 2, R2T - 6)], "blue")

    # 4 Gateway
    x1, y1, x2, y2 = PANEL[4]; d.panel(4, t["gw"])
    rows = (("user", "On-behalf-of identity", "preserve the user identity"), ("shield", "Central policy check", "every tool call · " + t["policy"]), ("search", "Tool catalogue", "+ shared knowledge_search()"),
            ("check", "Schema validation", None), ("lock", "Access control & policies", None), ("route", "Request routing & throttling", None), ("list", "Audit & tracing", "with the user identity"))
    for i, (ic, a, b) in enumerate(rows):
        yy = y1 + 76 + i * 78
        d.icon(ic, x1 + 14, yy + 8, 28, COL["purple"]); e = d.lines(x1 + 54, yy + 18, a, x2 - x1 - 62, 12.8, 700, maxl=3)
        if b: d.lines(x1 + 54, e - 1, b, x2 - x1 - 62, 11, 400, COL["mute"], maxl=3)
    gy = y1 + 76 + 7 * 78 + 2
    d.rect(x1 + 10, gy, x2 - 10, y2 - 12, COL["purple"] + "77", "#fff", 9, 1.6); d.text(x1 + 20, gy + 22, "Tool & RAG output guardrails", 11.5, 800)
    for i, s in enumerate((t["guard"], "Prompt-injection scan", "PII & schema checks")): d.text(x1 + 22, gy + 42 + i * 17, "• " + s, 11.5, 400, COL["mute"])
    d.arrow([(PANEL[3][2], 330), (PANEL[4][0], 330)], "blue")

    # 5 Approval
    x1, y1, x2, y2 = PANEL[5]; d.panel(5, "Actions & Approval")
    def step(yy, h, ic, a, b=None, c="red"):
        d.rect(x1 + 10, yy, x2 - 10, yy + h, COL[c] + "88", "#fff", 8, 1.5); d.icon(ic, x1 + 18, yy + h / 2 - 12, 24, COL[c])
        w = x2 - x1 - 66; tl = textwrap.wrap(a, int(w / (12.5 * 0.60))); sl = textwrap.wrap(b, int(w / (10.5 * 0.545))) if b else []
        y = yy + h / 2 - (len(tl) * 15.6 + len(sl) * 13.2) / 2 + 12
        for ln in tl: d.text(x1 + 52, y, ln, 12.5, 700); y += 15.6
        for ln in sl: d.text(x1 + 52, y - 2, ln, 10.5, 400, COL["mute"]); y += 13.2
    step(y1 + 72, 48, "search", "Classify operation & risk", "intent · impact · data"); step(y1 + 126, 36, "doc", "Preview proposed change")
    ry = y1 + 172
    d.add(f'<path d="M{x1+30},{ry+42} l24,-27 l24,27 l-24,27 z" fill="#fff" stroke="{COL["red"]}" stroke-width="1.6"/>'); d.text(x1 + 54, ry + 46, "Risk?", 10.5, 700, COL["red"], "middle")
    for i, (lv, lab, c) in enumerate((("Low", "Auto-approve", "green"), ("Medium", "Human approval", "orange"), ("High", "Human approval", "red"))):
        yy = ry + i * 32
        d.rect(x1 + 90, yy, x2 - 10, yy + 28, COL[c] + "99", "#fff", 6, 1.3); d.text(x1 + 96, yy + 19, lv, 11, 800, COL[c]); d.text(x1 + 148, yy + 19, lab, 10.5, 600, COL["ink"])
    step(y1 + 276, 48, "user", "Human approval", "for writes · authorised user")
    step(y1 + 330, 72, "gear", t["approval"][0], t["approval"][1])
    step(y1 + 408, 48, "db", t["ledger"], "system of record")
    step(y1 + 462, 48, "key", "Idempotency keys", "per-tool compensation")
    step(y1 + 516, 34, "play", "Execute approved action"); step(y1 + 556, 32, "check", "Validate result"); step(y1 + 594, 46, "refresh", "Rollback / compensation", "when reversible")
    step(y1 + 646, 48, "warn", "Irreversible actions", "two approvers + auto-undo")
    d.arrow([(PANEL[4][2], 330), (PANEL[5][0], 330)], "blue")

    # 6 Knowledge search
    x1, y1, x2, y2 = PANEL[6]; d.panel(6, "Knowledge Search (RAG)")
    d.rect(x1 + 10, y1 + 76, x2 - 10, y1 + 452, COL["blue"] + "77", "#fff", 9, 1.6); d.icon("search", x1 + 18, y1 + 86, 28, COL["blue"]); e = d.lines(x1 + 54, y1 + 100, t["search"][0], x2 - x1 - 66, 12.8, 800, maxl=2)
    d.lines(x1 + 54, e, t["search"][1], x2 - x1 - 66, 11, 400, COL["mute"], maxl=2)
    for i, s in enumerate(("Semantic vector search over SOPs, policies, manuals and past decisions", "Hybrid retrieval (vector + keyword)", "Metadata filtering", "Access-aware search using the user identity")):
        d.lines(x1 + 20, y1 + 178 + i * 68, "• " + s, x2 - x1 - 38, 11.8, 400, COL["mute"], maxl=4)
    d.rect(x1 + 10, y1 + 466, x2 - 10, y1 + 556, COL["blue"] + "77", "#fff", 9, 1.6, "5 4"); d.icon("layers", x1 + 18, y1 + 478, 26, COL["blue"]); d.lines(x1 + 52, y1 + 496, t["rerank"], x2 - x1 - 62, 12.5, 800, maxl=2)
    d.lines(x1 + 20, y1 + 534, "Re-rank for relevance & accuracy", x2 - x1 - 36, 11.5, 400, COL["mute"], maxl=2)
    d.arrow([(PANEL[5][2], 300), (PANEL[6][0], 300)], "blue")

    # 7 Tools
    x1, y1, x2, y2 = PANEL[7]; d.panel(7, t["tools"])
    def group(yy, h, head, items, c="teal"):
        d.rect(x1 + 10, yy, x2 - 10, yy + h, COL[c] + "77", "#fff", 9, 1.5); d.text(x1 + 18, yy + 22, head, 12.3, 800, COL["ink"] if c == "teal" else COL[c])
        for i, (a, b) in enumerate(items):
            y2_ = yy + 40 + i * 52
            d.rect(x1 + 18, y2_, x1 + 44, y2_ + 26, COL[c], COL[c], 6, 0); d.icon("func", x1 + 22, y2_ + 3, 20, "#fff", 1.8)
            d.text(x1 + 52, y2_ + 12, a, 12, 700); d.text(x1 + 52, y2_ + 27, b, 10.3, 400, COL["mute"])
    group(y1 + 76, 150, "Read-only tools", [("kb-search", "knowledge retrieval"), ("asset-status", "reads the assets table")])
    group(y1 + 240, 150, "Approval-gated writes", [("request-approval", "parks it for a human"), ("create-work-order", "runs only after approval")], "red")
    d.rect(x1 + 10, y1 + 404, x2 - 10, y1 + 500, COL["teal"] + "77", "#fff", 9, 1.5); d.text(x1 + 18, y1 + 426, "Operational data", 12.3, 800); d.icon("chip", x1 + 18, y1 + 442, 26, COL["teal"]); d.text(x1 + 52, y1 + 458, "Assets, work orders", 12, 700); d.text(x1 + 52, y1 + 474, "seeded fixture data", 10.3, 400, COL["mute"])
    d.arrow([(PANEL[6][2], 300), (PANEL[7][0], 300)], "blue")

    # 8 AgentOps
    x1, y1, x2, y2 = PANEL[8]; d.panel(8, "AgentOps & Observability")
    d.rect(x1 + 10, y1 + 78, x2 - 10, y1 + 492, COL["orange"] + "77", "#fff", 9, 1.5); d.text(x1 + 18, y1 + 98, "AgentOps lifecycle", 12.5, 800, COL["orange"])
    for i, (ic, s) in enumerate((("thumb", "Ratings & corrections feed an eval set"), ("chart", "Offline evals on golden datasets"), ("gear", "CI gates"), ("cube", "Version registry"), ("pin", "Model pinning"), ("bolt", "Canary with automatic rollback"), ("check", "Runtime runs pinned versions"))):
        yy = y1 + 108 + i * 54; d.icon(ic, x1 + 16, yy + 6, 24, COL["orange"]); d.lines(x1 + 48, yy + 14, s, x2 - x1 - 60, 11.2, 600, maxl=3)
    d.rect(x1 + 10, y1 + 504, x2 - 10, y1 + 716, COL["orange"] + "77", "#fff", 9, 1.5); d.text(x1 + 18, y1 + 524, "Observability", 12.5, 800, COL["orange"])
    d.icon("eye", x1 + 16, y1 + 536, 26, COL["orange"]); d.lines(x1 + 50, y1 + 552, "Traces, logs, metrics, evaluations & quality", x2 - x1 - 62, 11.5, 600, maxl=4)
    d.icon("chart", x1 + 16, y1 + 640, 26, COL["orange"]); e = d.lines(x1 + 50, y1 + 652, t["telem"][0], x2 - x1 - 62, 12, 800, maxl=2); d.lines(x1 + 50, e, t["telem"][1], x2 - x1 - 62, 10.5, 400, COL["mute"], maxl=3)
    d.arrow([(PANEL[7][2], 300), (PANEL[8][0], 300)], "blue")

    # 10 Models
    x1, y1, x2, y2 = PANEL[10]; d.panel(10, "Models", t["name"] if False else None)
    for i, nm in enumerate(t["models"]):
        ax = x1 + 14 + i * 226; d.rect(ax, y1 + 54, ax + 216, y1 + 100, COL["purple"] + "77", "#fff", 9, 1.6); d.icon("brain", ax + 12, y1 + 64, 26, COL["purple"]); d.lines(ax + 48, y1 + 82, nm, 160, 13.5, 800, maxl=2)
    d.rect(x1 + 14, y1 + 112, x2 - 14, y1 + 192, COL["purple"] + "77", "#fff", 9, 1.6); d.icon("route", x1 + 24, y1 + 130, 30, COL["purple"]); d.text(x1 + 70, y1 + 130, "Model router", 14, 800)
    for i, s in enumerate(("Task, cost & latency aware routing", "Quality & availability based", "Automatic fallback")): d.text(x1 + 70, y1 + 148 + i * 15, "• " + s, 11.5, 400, COL["mute"])
    d.arrow([(x2, R2T + 82), (PANEL[9][0], R2T + 82)], "blue")
    # 9 Memory
    x1, y1, x2, y2 = PANEL[9]; d.panel(9, t["mem"] if len(t["mem"]) < 24 else "Agent Memory", None)
    for i, (a, bl) in enumerate((("Short-term memory", ("Session events & context", "User / tenant scoped", "TTL / automatic expiry")), ("Long-term memory", ("User / tenant scoped", "Retention & deletion", "Provenance / poisoning checks")))):
        ax = x1 + 14 + i * 196; d.rect(ax, y1 + 54, ax + 188, y1 + 186, COL["blue"] + "77", "#fff", 9, 1.6); d.icon("brain", ax + 10, y1 + 62, 24, COL["blue"]); d.text(ax + 42, y1 + 80, a, 13, 800)
        for j, s in enumerate(bl): d.text(ax + 14, y1 + 108 + j * 20, "• " + s, 11.3, 400, COL["mute"])
    d.arrow([(x2, R2T + 82), (PANEL[11][0], R2T + 82)], "blue")
    d.arrow([(566, PANEL[3][3] + 24), (566, PANEL[9][1] - 2)], "blue", None, 2)
    # 11 Response
    x1, y1, x2, y2 = PANEL[11]; d.panel(11, "Response", None)
    d.rect(x1 + 12, y1 + 54, x2 - 12, y1 + 186, COL["teal"] + "77", "#fff", 9, 1.6); d.icon("doc", x1 + 22, y1 + 66, 30, COL["teal"]); d.lines(x1 + 62, y1 + 80, "Grounded response with citations", x2 - x1 - 80, 13, 800, maxl=2)
    for i, s in enumerate(("Grounding & citation check", "PII redaction", "Policy filter")): d.text(x1 + 24, y1 + 120 + i * 20, "• " + s, 11.3, 400, COL["mute"])
    d.arrow([(x2, R2T + 82), (PANEL[12][0], R2T + 82)], "blue")
    # 12 Pipeline
    x1, y1, x2, y2 = PANEL[12]; d.panel(12, "Knowledge Processing Pipeline", "event-driven")
    icons = ("bucket", "scan", "list", "chip", "db"); sw = (x2 - x1 - 40) / 5
    for i, ((a, b), ic) in enumerate(zip(t["pipe"], icons)):
        cx = x1 + 20 + sw * i + sw / 2; d.rect(cx - 44, y1 + 62, cx + 44, y1 + 128, COL["green"] + "77", "#fff", 10, 1.6); d.icon(ic, cx - 17, y1 + 70, 34, COL["green"])
        d.text(cx, y1 + 154, a, 12.3, 800, anchor="middle"); d.text(cx, y1 + 171, b, 10.8, 400, COL["mute"], "middle")
        if i < 4: d.arrow([(cx + 46, y1 + 95), (cx + sw - 46, y1 + 95)], "green", None, 2)
    x1, y1, x2, y2 = PANEL[14]
    d.rect(x1, y1, x2, y2, COL["green"] + "88", COL["green"] + "10", 6, 1.4, "5 4")
    d.add(f'<circle cx="{x1+14}" cy="{(y1+y2)/2}" r="9" fill="{COL["green"]}"/><text x="{x1+14}" y="{(y1+y2)/2+4}" font-size="11" font-weight="800" fill="#fff" text-anchor="middle">14</text>')
    d.text(x1 + 32, (y1 + y2) / 2 + 4, "Design the RAG: chunking, embedding, search, rerank, grounding", 11.5, 700, COL["green"])
    d.arrow([(1500, PANEL[7][3] + 2), (1500, PANEL[12][1] - 2)], "green", "6 4", 2)
    d.arrow([(1700, PANEL[12][1] - 2), (1700, PANEL[8][3] + 2)], "purple", "7 5", 2)

    # 13 Governance + legend
    x1, y1, x2, y2 = PANEL[13]; d.rect(x1, y1, x2, y2, COL["purple"], COL["purple"] + "0d", 12, 2.4); d.text(x1 + 18, y1 + 30, "Governance & Security", 18, 800, COL["purple"]); d.text(x1 + 252, y1 + 30, "cross-cutting: applies to every layer", 12.5, 400, COL["mute"])
    gi = ("users", "lock", "cloud", "shield", "db", "clip", "dollar"); gw = (x2 - x1 - 20) / 7
    for i, ((a, b), ic) in enumerate(zip(t["gov"], gi)):
        gx = x1 + 10 + gw * i; d.icon(ic, gx + 8, y1 + 58, 32, COL["purple"]); d.text(gx + 48, y1 + 72, a, 12.5, 800); d.text(gx + 48, y1 + 90, b, 11, 400, COL["mute"])
    lx = 1462; d.rect(lx, y1, 1790, y2, "#94a3b8", "#fff", 10, 1.6, "5 4"); d.text(lx + 16, y1 + 26, "Legend", 14, 800)
    for i, (c, da, s) in enumerate((("blue", None, "Primary flow"), ("purple", "7 5", "Logs / telemetry"), ("green", "6 4", "Cache lookup"))):
        d.add(f'<path d="M{lx+16},{y1+52+i*26} H{lx+70}" stroke="{COL[c]}" stroke-width="2.4" {"stroke-dasharray=%s" % chr(34) + da + chr(34) if da else ""} marker-end="url(#ah-{c})"/>'); d.text(lx + 84, y1 + 57 + i * 26, s, 12.5, 400)
    d.add("</svg>")
    return "".join(d.o)


def hotspots():
    return HOTSPOTS, [W, H]


def main():
    os.makedirs(os.path.join(BASE, "img"), exist_ok=True)
    for c in T:
        with open(os.path.join(BASE, "img", c + ".svg"), "w", encoding="utf-8") as f:
            f.write(draw(c))
        print(c, "diagram written")


if __name__ == "__main__":
    main()
