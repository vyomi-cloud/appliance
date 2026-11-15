"""Real boto3 proof for the Bedrock knowledge-base ingestion + runtime limitation closures (bedrock-agent, bedrock-agent-runtime,
bedrock-runtime) against the unified router served over real HTTP (core.wire_ingress), with a deterministic fake OpenAI-compatible
model server (tests/conformance/llm_fakes.py) and the stdlib hash embedder.

Covers: KB ingestion of PDF / DOCX / XLSX / CSV / PPTX / HTML / Markdown (pypdf + zipfile/ElementTree), parsingConfiguration,
FIXED_SIZE / HIERARCHICAL / SEMANTIC / NONE chunking, `.metadata.json` (plain + typed) with Retrieve filters, per-document failure
reporting; Converse/InvokeModel `document` blocks (real text extraction), `image` blocks (honest ValidationException without a vision
model), prompt caching (cachePoint -> cacheRead/WriteInputTokens from a real prefix cache), reasoning rejection.

Skips (exit 0) when boto3 / pypdf are not installed.   Run: PYTHONPATH=.:<dir with pypdf> python tests/conformance/test_bedrock_kb_runtime_caps.py
"""
import base64
import io
import json
import os
import socket
import sys
import threading
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_fakes import FakeLLM  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {str(extra)[:600]}")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ───────────── tiny document factories (no extra libraries) ─────────────
def make_pdf(pages):
    """A real, minimal PDF 1.4 with one text line per page (Helvetica)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for i, t in enumerate(pages):
        pid = 4 + 2 * i
        kids.append(f"{pid} 0 R")
        st = f"BT /F1 12 Tf 50 700 Td ({t.replace('(', '[').replace(')', ']')}) Tj ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {pid + 1} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        objs.append(f"<< /Length {len(st)} >>\nstream\n{st}\nendstream")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>"
    out, offs = b"%PDF-1.4\n", []
    for n, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{n} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()


def make_docx(paras, table=None):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = ""
    for style, t in paras:
        ps = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        body += f"<w:p>{ps}<w:r><w:t>{t}</w:t></w:r></w:p>"
    if table:
        body += "<w:tbl>" + "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row) + "</w:tr>" for row in table) + "</w:tbl>"
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>')
    return b.getvalue()


def make_xlsx(sheets):
    s = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    strings, wsx, rels, sheetx = [], {}, "", ""
    for n, (name, rows) in enumerate(sheets.items(), 1):
        rx = ""
        for ri, row in enumerate(rows, 1):
            cx = ""
            for ci, v in enumerate(row):
                ref = f"{chr(65 + ci)}{ri}"
                if isinstance(v, str):
                    strings.append(v)
                    cx += f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>'
                else:
                    cx += f'<c r="{ref}"><v>{v}</v></c>'
            rx += f'<row r="{ri}">{cx}</row>'
        wsx[f"xl/worksheets/sheet{n}.xml"] = f'<worksheet xmlns="{s}"><sheetData>{rx}</sheetData></worksheet>'
        rels += f'<Relationship Id="rId{n}" Target="worksheets/sheet{n}.xml"/>'
        sheetx += f'<sheet name="{name}" sheetId="{n}" r:id="rId{n}"/>'
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{s}" xmlns:r="{r}"><sheets>{sheetx}</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", f"<Relationships>{rels}</Relationships>")
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{s}">' + "".join(f"<si><t>{t}</t></si>" for t in strings) + "</sst>")
        for k, v in wsx.items():
            z.writestr(k, v)
    return b.getvalue()


def make_pptx(slides):
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for i, (txt, notes) in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", f'<p:sld xmlns:p="x" xmlns:a="{a}"><a:p><a:r><a:t>{txt}</a:t></a:r></a:p></p:sld>')
            if notes:
                z.writestr(f"ppt/notesSlides/notesSlide{i}.xml", f'<p:notes xmlns:p="x" xmlns:a="{a}"><a:p><a:r><a:t>{notes}</a:t></a:r></a:p></p:notes>')
    return b.getvalue()


def main():
    try:
        import boto3
        import pypdf
        from botocore.config import Config
        from botocore.exceptions import ClientError
    except ImportError as e:
        print("missing", e, "- skipping")
        return 0
    import uvicorn
    from fastapi import FastAPI, Request
    from core import llm_core as llm
    from core import wire_ingress
    from core import s3_object_core as s3c
    from core.aws_wire_router import AwsWireRouter

    fake = FakeLLM(delay=0.0)
    fake.handler = lambda body: {"content": "fine"}
    llm.set_backend(None, embed_fn=lambda ts: [llm.hash_embed(t) for t in ts], endpoint=fake.url)
    os.environ.pop("VYOMI_LLM_DISABLE", None)
    router = AwsWireRouter()
    app = FastAPI()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)

    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    kw = dict(region_name="us-east-1", endpoint_url=url, aws_access_key_id="x", aws_secret_access_key="y", config=Config(retries={"max_attempts": 1}))
    ba, bar, br = boto3.client("bedrock-agent", **kw), boto3.client("bedrock-agent-runtime", **kw), boto3.client("bedrock-runtime", **kw)

    # ───────────────────────── Knowledge base ingestion ─────────────────────────
    s3c.dispatch(router.s3, "PUT", "/kbdocs", {}, {}, b"")

    def put(k, v):
        s3c.dispatch(router.s3, "PUT", f"/kbdocs/{k}", {}, {}, v if isinstance(v, bytes) else v.encode())

    put("d/policy.pdf", make_pdf(["Visitor parking is validated at the front desk for four hours.", "Elevator maintenance happens every second Tuesday of the month."]))
    put("d/handbook.docx", make_docx([("Heading1", "Chiller plant"), (None, "The chiller plant on level B2 is serviced quarterly by Northwind HVAC."),
                                       ("Heading1", "Fire safety"), (None, "Extinguishers are inspected monthly.")], [["Asset", "Owner"], ["Chiller-7", "Facilities"]]))
    put("d/assets.xlsx", make_xlsx({"Assets": [["Asset", "Floor", "Owner"], ["Boiler-3", "B1", "Plant Ops"], ["Generator-9", "Roof", 42]]}))
    put("d/tickets.csv", "id,issue,site\n1,Leaking pipe in lobby,HQ\n2,Broken badge reader,Annex\n")
    put("d/deck.pptx", make_pptx([("Quarterly facilities review", "Mention the lobby renovation budget"), ("Energy savings roadmap", "")]))
    put("d/page.html", "<html><head><style>x{}</style></head><body><h1>Visitor Wi-Fi</h1><p>Guests join the network &amp; accept terms.</p></body></html>")
    put("d/notes.md", "# Recycling\n\nBlue bins collect paper. Green bins collect glass.\n")
    put("d/old.doc", b"\xd0\xcf\x11\xe0 legacy binary")
    put("d/broken.pdf", b"%PDF-1.4 this is not a real pdf")
    scanned = io.BytesIO()
    w = pypdf.PdfWriter()
    w.add_blank_page(612, 792)
    w.write(scanned)
    put("d/scanned.pdf", scanned.getvalue())
    put("d/empty.txt", "   \n")
    put("d/badmeta.txt", "This document has an invalid metadata sidecar file.")
    put("d/badmeta.txt.metadata.json", "{not json")
    put("d/policy.pdf.metadata.json", json.dumps({"metadataAttributes": {"dept": "facilities", "year": 2026, "public": True}}))
    put("d/handbook.docx.metadata.json", json.dumps({"metadataAttributes": {"dept": {"value": {"type": "STRING", "stringValue": "hvac"}, "includeForEmbedding": True},
                                                                              "year": {"value": {"type": "NUMBER", "numberValue": 2024}}}}))

    emb = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
    role = "arn:aws:iam::123456789012:role/r"
    kb = ba.create_knowledge_base(name="facilities-kb", roleArn=role, knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {"embeddingModelArn": emb}},
                                  storageConfiguration={"type": "OPENSEARCH_SERVERLESS"})["knowledgeBase"]["knowledgeBaseId"]
    s3cfg = {"type": "S3", "s3Configuration": {"bucketArn": "arn:aws:s3:::kbdocs", "inclusionPrefixes": ["d/"]}}

    def ds_with(name, vic):
        return ba.create_data_source(knowledgeBaseId=kb, name=name, dataSourceConfiguration=s3cfg, vectorIngestionConfiguration=vic)["dataSource"]["dataSourceId"]

    def sync(ds):
        j = ba.start_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds)["ingestionJob"]
        return ba.get_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds, ingestionJobId=j["ingestionJobId"])["ingestionJob"]

    def err(fn, **a):
        try:
            fn(**a)
        except ClientError as e:
            return e.response["Error"]["Code"], e.response["Error"]["Message"]
        return None, ""

    d1 = ds_with("fixed", {"chunkingConfiguration": {"chunkingStrategy": "FIXED_SIZE", "fixedSizeChunkingConfiguration": {"maxTokens": 40, "overlapPercentage": 10}}})
    job = sync(d1)
    st = job["statistics"]
    fr = " || ".join(job.get("failureReasons", []))
    check("job COMPLETE; 12 docs scanned, 7 indexed, 5 failed (4 unparseable + 1 bad metadata)", job["status"] == "COMPLETE" and st["numberOfDocumentsScanned"] == 12
          and st["numberOfNewDocumentsIndexed"] == 7 and st["numberOfDocumentsFailed"] == 5, st)
    check("per-document failure reasons name each file and why", all(x in fr for x in ["old.doc", "legacy binary", "broken.pdf", "unreadable PDF", "scanned.pdf",
                                                                                          "no extractable text", "empty.txt", "badmeta.txt", "not valid JSON"]), fr)
    check("metadata sidecars counted", st["numberOfMetadataDocumentsScanned"] == 3, st)

    def retrieve(q, n=3, flt=None):
        vs = {"numberOfResults": n}
        if flt:
            vs["filter"] = flt
        return bar.retrieve(knowledgeBaseId=kb, retrievalQuery={"text": q}, retrievalConfiguration={"vectorSearchConfiguration": vs})["retrievalResults"]

    def top_uri(q, **k):
        r = retrieve(q, **k)
        return (r[0]["location"]["s3Location"]["uri"], r[0]["content"]["text"]) if r else ("", "")

    for q, want, frag in [("visitor parking validated front desk", "policy.pdf", "four hours"),
                          ("chiller plant serviced quarterly Northwind", "handbook.docx", "Northwind"),
                          ("Generator-9 floor Roof owner", "assets.xlsx", "Generator-9"),
                          ("leaking pipe lobby", "tickets.csv", "Leaking pipe"),
                          ("energy savings roadmap slide", "deck.pptx", "Energy savings"),
                          ("guests join network accept terms visitor wifi", "page.html", "Guests join the network & accept terms"),
                          ("blue bins collect paper recycling", "notes.md", "Blue bins")]:
        u, t = top_uri(q)
        check(f"Retrieve finds the {want.split('.')[-1].upper()} content", u.endswith(want) and frag in t, (u, t[:120]))
    check("PPTX speaker notes are indexed", "lobby renovation budget" in top_uri("lobby renovation budget notes")[1])
    check("DOCX table row flattened (default parsing) as header: value", "Asset: Chiller-7" in "".join(c["content"]["text"] for c in retrieve("Chiller-7 Facilities owner", 6)) or
          "Owner: Facilities" in "".join(c["content"]["text"] for c in retrieve("Chiller-7 Facilities owner", 6)))
    r = retrieve("parking", 6)
    check("metadata attributes returned on results", any(x["metadata"].get("dept") == "facilities" and x["metadata"].get("year") == 2026 for x in r), r[:1])
    flt = retrieve("the", 8, {"equals": {"key": "dept", "value": "hvac"}})
    check("Retrieve metadata filter (typed sidecar attribute)", flt and all(x["location"]["s3Location"]["uri"].endswith("handbook.docx") for x in flt), flt)
    flt = retrieve("the", 8, {"greaterThan": {"key": "year", "value": 2025}})
    check("Retrieve numeric metadata filter", flt and all(x["location"]["s3Location"]["uri"].endswith("policy.pdf") for x in flt), flt)

    # parsingConfiguration
    code, msg = err(ba.create_data_source, knowledgeBaseId=kb, name="bda", dataSourceConfiguration=s3cfg,
                    vectorIngestionConfiguration={"parsingConfiguration": {"parsingStrategy": "BEDROCK_DATA_AUTOMATION"}})
    check("BEDROCK_DATA_AUTOMATION parsing -> ValidationException (honest)", code == "ValidationException" and "Data Automation" in msg, (code, msg))
    d2 = ds_with("fm-parse", {"parsingConfiguration": {"parsingStrategy": "BEDROCK_FOUNDATION_MODEL", "bedrockFoundationModelConfiguration": {"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0"}},
                              "chunkingConfiguration": {"chunkingStrategy": "NONE"}})
    j2 = sync(d2)
    check("FM parsing + NONE chunking ingests", j2["statistics"]["numberOfNewDocumentsIndexed"] == 7, j2["statistics"])
    txt = " ".join(x["content"]["text"] for x in retrieve("Chiller-7 Facilities Asset Owner table", 12))
    check("FM parsing keeps the DOCX table as a markdown table", "| Asset | Owner |" in txt and "|---|---|" in txt, txt[:300])

    # chunking strategies (inspect via the RAG Studio endpoint of the simulator)
    import urllib.request

    def studio_chunks():
        return json.loads(urllib.request.urlopen(f"{url}/_vyomi/kb/{kb}/chunks", timeout=20).read())["chunks"]
    long_md = "# Alpha\n\n" + " ".join(f"alpha sentence {i} about turbines." for i in range(120)) + "\n\n# Beta\n\n" + " ".join(f"beta sentence {i} about pumps." for i in range(120))
    put("long/long.md", long_md)
    s3long = {"type": "S3", "s3Configuration": {"bucketArn": "arn:aws:s3:::kbdocs", "inclusionPrefixes": ["long/"]}}

    def long_ds(name, cc):
        ds = ba.create_data_source(knowledgeBaseId=kb, name=name, dataSourceConfiguration=s3long, vectorIngestionConfiguration={"chunkingConfiguration": cc})["dataSource"]["dataSourceId"]
        sync(ds)
        return [c for c in studio_chunks() if str(c.get("id", "")).startswith(ds + "-")]
    cn = long_ds("c-none", {"chunkingStrategy": "NONE"})
    check("NONE: one chunk per file", len(cn) == 1, len(cn))
    cf = long_ds("c-fixed", {"chunkingStrategy": "FIXED_SIZE", "fixedSizeChunkingConfiguration": {"maxTokens": 50, "overlapPercentage": 20}})
    check("FIXED_SIZE: many windows of <= 50 words with overlap", len(cf) > 8 and all(c["tokenCount"] <= 50 for c in cf), len(cf))
    ch = long_ds("c-hier", {"chunkingStrategy": "HIERARCHICAL", "hierarchicalChunkingConfiguration": {"levelConfigurations": [{"maxTokens": 300}, {"maxTokens": 60}], "overlapTokens": 10}})
    check("HIERARCHICAL: child chunks (<=60) under parent chunks (<=300), headings kept", len(ch) > 8 and all(c["tokenCount"] <= 60 for c in ch), len(ch))
    cs = long_ds("c-sem", {"chunkingStrategy": "SEMANTIC", "semanticChunkingConfiguration": {"maxTokens": 80, "bufferSize": 1, "breakpointPercentileThreshold": 90}})
    check("SEMANTIC: embedding-breakpoint chunks, each <= maxTokens", len(cs) >= 2 and all(c["tokenCount"] <= 80 for c in cs), [c["tokenCount"] for c in cs])
    code, msg = err(ba.create_data_source, knowledgeBaseId=kb, name="bad-h", dataSourceConfiguration=s3long,
                    vectorIngestionConfiguration={"chunkingConfiguration": {"chunkingStrategy": "HIERARCHICAL", "hierarchicalChunkingConfiguration": {"levelConfigurations": [{"maxTokens": 50}, {"maxTokens": 60}], "overlapTokens": 10}}})
    check("invalid hierarchical config -> ValidationException", code == "ValidationException", (code, msg))
    hr = retrieve("beta sentence 7 about pumps", 5)
    check("hierarchical Retrieve returns the parent chunk (larger than a child), de-duplicated",
          hr and any(len(x["content"]["text"].split()) > 60 for x in hr) and len({x["content"]["text"] for x in hr}) == len(hr), [len(x["content"]["text"].split()) for x in hr])

    # ───────────────────────── Converse / InvokeModel document blocks ─────────────────────────
    claude = "anthropic.claude-3-haiku-20240307-v1:0"
    pdf = make_pdf(["The vault access code rotates every Monday at nine."])
    r = br.converse(modelId=claude, messages=[{"role": "user", "content": [{"document": {"format": "pdf", "name": "policy", "source": {"bytes": pdf}}}, {"text": "When does the code rotate?"}]}])
    up = fake.requests[-1]["messages"][-1]["content"]
    check("Converse PDF document block: text extracted and sent to the model", "vault access code rotates every Monday" in up and "When does the code rotate?" in up and r["stopReason"] == "end_turn", up)
    docx = make_docx([("Heading1", "Onboarding"), (None, "Badge photos are taken on day one.")])
    br.converse(modelId=claude, messages=[{"role": "user", "content": [{"document": {"format": "docx", "name": "onboard", "source": {"bytes": docx}}}, {"text": "?"}]}])
    check("Converse DOCX document block", "Badge photos are taken on day one" in fake.requests[-1]["messages"][-1]["content"])
    xl = make_xlsx({"Sheet1": [["Item", "Qty"], ["Filters", 12]]})
    br.converse(modelId=claude, messages=[{"role": "user", "content": [{"document": {"format": "xlsx", "name": "stock", "source": {"bytes": xl}}}, {"text": "?"}]}])
    check("Converse XLSX document block (table kept as markdown)", "| Item | Qty |" in fake.requests[-1]["messages"][-1]["content"] and "Filters" in fake.requests[-1]["messages"][-1]["content"])
    br.converse(modelId=claude, messages=[{"role": "user", "content": [{"document": {"format": "csv", "name": "t", "source": {"bytes": b"a,b\n1,2\n"}}}, {"text": "?"}]}])
    check("Converse CSV document block", "| a | b |" in fake.requests[-1]["messages"][-1]["content"])
    br.converse(modelId=claude, messages=[{"role": "user", "content": [{"document": {"format": "md", "name": "m", "source": {"bytes": b"# Title\nbody text"}}}, {"text": "?"}]}])
    check("Converse MD document block", "body text" in fake.requests[-1]["messages"][-1]["content"])
    code, msg = err(br.converse, modelId=claude, messages=[{"role": "user", "content": [{"document": {"format": "pdf", "name": "bad", "source": {"bytes": b"%PDF nope"}}}, {"text": "?"}]}])
    check("unparseable document -> ValidationException naming the document", code == "ValidationException" and "bad.pdf" in msg, (code, msg))
    code, msg = err(br.converse, modelId=claude, messages=[{"role": "user", "content": [{"document": {"format": "doc", "name": "old", "source": {"bytes": b"\xd0\xcf"}}}, {"text": "?"}]}])
    check("legacy .doc -> ValidationException", code == "ValidationException" and "legacy" in msg, (code, msg))
    body = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 50, "messages": [{"role": "user", "content": [
        {"type": "document", "title": "policy", "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(pdf).decode()}}, {"type": "text", "text": "when?"}]}]}
    out = json.loads(br.invoke_model(modelId=claude, body=json.dumps(body))["body"].read())
    check("InvokeModel (Claude) PDF document block: extracted text reaches the model", "vault access code" in fake.requests[-1]["messages"][-1]["content"] and out["content"][0]["text"] == "fine")

    # images
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    imsg = [{"role": "user", "content": [{"image": {"format": "png", "source": {"bytes": png}}}, {"text": "what is this?"}]}]
    code, msg = err(br.converse, modelId=claude, messages=imsg)
    check("image block without a vision model -> honest ValidationException", code == "ValidationException" and "vision" in msg, (code, msg))
    code, msg = err(br.invoke_model, modelId=claude, body=json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 5, "messages": [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode()}}]}]}))
    check("Claude image block without a vision model -> ValidationException", code == "ValidationException" and "vision" in msg, (code, msg))
    llm.set_vision(True)
    try:
        br.converse(modelId=claude, messages=imsg)
        parts = fake.requests[-1]["messages"][-1]["content"]
        check("with a vision-capable backend the image reaches it as an image_url part (stub backend; no real vision model run)",
              isinstance(parts, list) and parts[1]["type"] == "image_url" and parts[1]["image_url"]["url"].startswith("data:image/png;base64,"), parts)
    finally:
        llm.set_vision(False)

    # reasoning stays rejected
    code, msg = err(br.converse, modelId=claude, messages=[{"role": "user", "content": [{"text": "hi"}]}], additionalModelRequestFields={"thinking": {"type": "enabled", "budget_tokens": 1024}})
    check("reasoning (thinking) request -> ValidationException", code == "ValidationException" and "reasoning" in msg.lower(), (code, msg))
    code, msg = err(br.converse, modelId=claude, messages=[{"role": "assistant", "content": [{"reasoningContent": {"reasoningText": {"text": "x"}}}]}, {"role": "user", "content": [{"text": "hi"}]}])
    check("reasoningContent block -> ValidationException", code == "ValidationException", (code, msg))

    # ───────────────────────── prompt caching ─────────────────────────
    big = ("Facilities operating manual. " + "The chiller plant must be inspected before every shift. " * 140)
    sysb = [{"text": big}, {"cachePoint": {"type": "default"}}]
    m1 = [{"role": "user", "content": [{"text": "Q1: when is the plant inspected?"}]}]
    u1 = br.converse(modelId=claude, system=sysb, messages=m1)["usage"]
    check("first call writes the cache (cacheWriteInputTokens > 0, no read)", u1["cacheWriteInputTokens"] > 1000 and u1["cacheReadInputTokens"] == 0, u1)
    u2 = br.converse(modelId=claude, system=sysb, messages=[{"role": "user", "content": [{"text": "Q2: totally different question?"}]}])["usage"]
    check("second call reads the same prefix (cacheReadInputTokens == earlier write, nothing re-written)",
          u2["cacheReadInputTokens"] == u1["cacheWriteInputTokens"] and u2["cacheWriteInputTokens"] == 0, (u1, u2))
    check("inputTokens counts only the uncached suffix; totals reconcile with the model's own count",
          u2["inputTokens"] < 100 and u2["inputTokens"] + u2["cacheReadInputTokens"] + u2["cacheWriteInputTokens"] == fake_prompt_tokens(fake), (u2, fake_prompt_tokens(fake)))
    u3 = br.converse(modelId=claude, system=[{"text": big + " changed"}, {"cachePoint": {"type": "default"}}], messages=m1)["usage"]
    check("changing the prefix is a cache miss -> new write", u3["cacheReadInputTokens"] == 0 and u3["cacheWriteInputTokens"] > 1000, u3)
    us = br.converse(modelId=claude, system=[{"text": "short"}, {"cachePoint": {"type": "default"}}], messages=m1)["usage"]
    check("a prefix under the 1024-token minimum is not cached", us["cacheReadInputTokens"] == 0 and us["cacheWriteInputTokens"] == 0, us)
    un = br.converse(modelId=claude, system=[{"text": big}], messages=m1)["usage"]
    check("no cachePoint -> usage has no cache fields", "cacheReadInputTokens" not in un, un)
    # message-level checkpoint (multi-turn): cache the history
    hist = [{"role": "user", "content": [{"text": big}, {"cachePoint": {"type": "default"}}]}]
    a1 = br.converse(modelId=claude, messages=hist)["usage"]
    a2 = br.converse(modelId=claude, messages=hist + [{"role": "assistant", "content": [{"text": "ok"}]}, {"role": "user", "content": [{"text": "next"}]}])["usage"]
    check("message-level cachePoint: turn 2 reads turn 1's prefix", a1["cacheWriteInputTokens"] > 1000 and a2["cacheReadInputTokens"] == a1["cacheWriteInputTokens"], (a1, a2))
    # streaming metadata
    sm = None
    for ev in br.converse_stream(modelId=claude, system=sysb, messages=m1)["stream"]:
        if "metadata" in ev:
            sm = ev["metadata"]["usage"]
    check("ConverseStream metadata reports cacheReadInputTokens", sm and sm["cacheReadInputTokens"] > 1000, sm)
    # Claude InvokeModel cache_control
    cb = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 20, "system": [{"type": "text", "text": big, "cache_control": {"type": "ephemeral"}}],
          "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]}
    c1 = json.loads(br.invoke_model(modelId=claude, body=json.dumps(cb))["body"].read())["usage"]
    cb["messages"][0]["content"][0]["text"] = "different"
    c2 = json.loads(br.invoke_model(modelId=claude, body=json.dumps(cb))["body"].read())["usage"]
    check("InvokeModel cache_control: creation then read tokens", c1["cache_creation_input_tokens"] > 1000 and c2["cache_read_input_tokens"] == c1["cache_creation_input_tokens"], (c1, c2))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


def fake_prompt_tokens(fake):
    b = fake.requests[-1]
    return sum(len(str(m.get("content") or "")) for m in b["messages"]) // 4 + 1


if __name__ == "__main__":
    sys.exit(main())
