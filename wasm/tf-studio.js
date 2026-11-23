/* Vyomi Infrastructure Studio — diagram / export / import of the stack as Terraform, rendered INSIDE a console page.
 * VyomiStudio.mount(host, {cloud:"aws"}). Reads the Terraform API of the backend that holds the stack: the appliance or a Mesh
 * (localStorage "vyomi.tf.base", or window.VYOMI_TF_BASE), else this origin. Draws with the host console's own panel/btn styles. */
(function () {
  const NS = "http://www.w3.org/2000/svg", W = 150, H = 44, GAP = 18;
  const COL = { supported: "#1d8102", planned: "#b7791f", not_possible: "#d13212" };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const svg = (n, a, p) => { const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; };
  const LOCAL = /^(127\.0\.0\.1|localhost)$/.test(location.hostname);
  const base = () => { try { return (localStorage.getItem("vyomi.tf.base") || window.VYOMI_TF_BASE || (LOCAL ? "http://127.0.0.1:9101" : "")).replace(/\/$/, ""); } catch (_) { return ""; } };

  function layout(g) {
    const pos = {}, boxes = []; let y = 12;
    for (const grp of g.groups) {
      const ms = g.nodes.filter((n) => n.group === grp.id), cols = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(ms.length)))), rows = Math.ceil(ms.length / cols) || 1;
      const w = cols * (W + GAP) + GAP, h = rows * (H + GAP) + GAP + 22;
      boxes.push({ x: 12, y, w, h, label: "VPC " + grp.label + (grp.cidr ? "  " + grp.cidr : "") });
      ms.forEach((n, i) => (pos[n.id] = { x: 12 + GAP + (i % cols) * (W + GAP), y: y + 26 + Math.floor(i / cols) * (H + GAP) }));
      y += h + GAP;
    }
    const rest = g.nodes.filter((n) => !n.group), svcs = [...new Set(rest.map((n) => n.service))].sort();
    svcs.forEach((s) => {
      const ms = rest.filter((n) => n.service === s);
      boxes.push({ x: 12, y, w: ms.length * (W + GAP) + GAP, h: H + GAP * 2 + 16, label: s, lane: 1 });
      ms.forEach((n, i) => (pos[n.id] = { x: 12 + GAP + i * (W + GAP), y: y + 26 }));
      y += H + GAP * 2 + 30;
    });
    return { pos, boxes, w: Math.max(600, ...boxes.map((b) => b.x + b.w)) + 12, h: y + 8 };
  }

  function mount(host, opts) {
    opts = opts || {}; const cloud = opts.cloud || "aws";
    host.innerHTML = `<style>
      .tfs-lg{display:flex;gap:16px;flex-wrap:wrap;color:var(--sub,#5f6b7a);font-size:12.5px;margin-bottom:8px}.tfs-lg i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
      .tfs-grid{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:16px}@media(max-width:1000px){.tfs-grid{grid-template-columns:minmax(0,1fr)}}
      .tfs-canvas{overflow:auto;padding:12px}.tfs-side .tfs-b{padding:10px 18px;font-size:13px}.tfs-row{padding:7px 0;border-top:1px solid var(--line,#eaeded)}.tfs-row:first-child{border-top:0}
      .tfs-tag{font-size:11px;padding:1px 7px;border-radius:10px;border:1px solid var(--line-d,#d5d9d9);color:var(--sub,#5f6b7a);margin-left:6px}
      .tfs-nd{cursor:pointer}.tfs-nd rect{fill:#fff;stroke-width:2}.tfs-grp{fill:none;stroke:#0972d3;stroke-width:1.5;stroke-dasharray:6 4}.tfs-edge{fill:none;stroke:#8a94a3;stroke-width:1;opacity:.55}.tfs-edge.hi{stroke:#0972d3;opacity:1;stroke-width:2}
      .tfs-tabs{display:flex;gap:4px;border-bottom:1px solid var(--line,#eaeded);margin-bottom:14px}.tfs-tabs button{background:none;border:0;border-bottom:2px solid transparent;padding:9px 14px;cursor:pointer;font:inherit;color:var(--sub,#5f6b7a)}.tfs-tabs button.on{color:#0972d3;border-color:#0972d3;font-weight:600}
      .tfs-src{margin:0;padding:12px 18px;overflow:auto;max-height:360px;font:12px/1.45 ui-monospace,monospace;background:#fafafa}.tfs-drop{border:2px dashed var(--line-d,#d5d9d9);border-radius:8px;padding:30px;text-align:center;color:var(--sub,#5f6b7a)}
      .tfs-err{color:#d13212}.tfs-warn{color:#b7791f}</style>
      <h1 class="page-h">Infrastructure Studio</h1>
      <p style="color:var(--sub,#5f6b7a);margin:4px 0 12px">See your ${cloud.toUpperCase()} stack as a diagram, export it as Terraform, or check a Terraform template before you apply it.</p>
      <div class="tfs-tabs"><button class="on" data-t="export">Export</button><button data-t="import">Import</button>
        <span style="flex:1"></span><label style="font-size:12px;color:var(--sub,#5f6b7a)">Backend <input id="tfsBase" class="btn" style="height:30px;width:210px;text-align:left;cursor:text" placeholder="this page"></label><select id="tfsMode" class="btn" style="height:30px"><option value="sim">Target: Vyomi</option><option value="real">Target: real AWS</option></select>
        <button class="btn" id="tfsRef" style="margin-left:8px">Refresh</button></div>
      <div id="tfsExport" class="tfs-grid"><div>
        <div class="panel"><div class="panel-h">Stack diagram</div><div style="padding:10px 18px 0"><div class="tfs-lg"><span><i style="background:${COL.supported}"></i>Available in Vyomi</span><span><i style="background:${COL.planned}"></i>Planned, not simulated yet</span><span><i style="background:${COL.not_possible}"></i>Not possible in Vyomi</span></div></div>
          <div class="tfs-canvas" id="tfsCanvas">Reading your stack…</div></div>
        <div class="panel"><div class="panel-h">Terraform files <span style="flex:1"></span><select id="tfsFiles" class="btn" style="height:28px"></select><button class="btn primary" id="tfsDl">Download .zip</button></div><pre class="tfs-src" id="tfsSrc"></pre></div></div>
        <div class="tfs-side"><div class="panel"><div class="panel-h">Selected</div><div class="tfs-b" id="tfsSel" style="color:var(--sub,#5f6b7a)">Choose a resource in the diagram.</div></div>
          <div class="panel"><div class="panel-h">Unavailable in Vyomi</div><div class="tfs-b" id="tfsGaps">None.</div></div>
          <div class="panel"><div class="panel-h">Before you apply on real ${cloud.toUpperCase()}</div><div class="tfs-b" id="tfsPort">-</div></div></div></div>
      <div id="tfsImport" style="display:none"><div class="panel"><div class="panel-h">Check a Terraform template</div><div style="padding:16px 18px">
        <div class="tfs-drop" id="tfsDrop">Drop .tf files here or <label style="color:#0972d3;cursor:pointer">choose files<input id="tfsPick" type="file" accept=".tf" multiple hidden></label></div>
        <p style="color:var(--sub,#5f6b7a)">Lists which resource types in your template Vyomi can create. Apply it with OpenTofu or Terraform against this endpoint; applying inside the browser is not available yet.</p><div id="tfsImp"></div></div></div></div>`;
    const $ = (id) => host.querySelector("#" + id); let G = null, B = null;
    const api = (p) => fetch(base() + p).then((r) => { if (!r.ok) throw new Error(p + " → HTTP " + r.status); return r.json(); });

    function draw(g) {
      const c = $("tfsCanvas"); c.innerHTML = "";
      if (!g.nodes.length) { c.textContent = "No resources in this space yet. Apply a Terraform template or create resources, then refresh."; return; }
      const L = layout(g), s = svg("svg", { width: L.w, height: L.h }); c.appendChild(s);
      L.boxes.forEach((b) => { svg("rect", { x: b.x, y: b.y, width: b.w, height: b.h, rx: 8, class: "tfs-grp", style: b.lane ? "stroke:#c9ced6" : "" }, s); svg("text", { x: b.x + 10, y: b.y + 16, style: "font:12px sans-serif;fill:#414d5c" }, s).textContent = b.label; });
      const ed = [];
      g.edges.forEach((e) => { const a = L.pos[e.from], b = L.pos[e.to]; if (!a || !b) return; const x1 = a.x + W / 2, y1 = a.y + H / 2, x2 = b.x + W / 2, y2 = b.y + H / 2;
        ed.push({ p: svg("path", { d: `M${x1} ${y1} C${x1} ${(y1 + y2) / 2},${x2} ${(y1 + y2) / 2},${x2} ${y2}`, class: "tfs-edge" }, s), e }); });
      g.nodes.forEach((n) => { const p = L.pos[n.id]; if (!p) return; const gr = svg("g", { class: "tfs-nd", transform: `translate(${p.x},${p.y})` }, s);
        svg("rect", { width: W, height: H, rx: 6, style: `stroke:${COL[n.status]};${n.status === "planned" ? "stroke-dasharray:5 3" : n.status === "not_possible" ? "stroke-dasharray:2 3" : ""}` }, gr);
        svg("text", { x: 8, y: 18, style: "font:12px sans-serif;fill:#16191f" }, gr).textContent = n.label.length > 22 ? n.label.slice(0, 21) + "…" : n.label;
        const ty = n.type.replace(/^aws_/, ""); svg("text", { x: 8, y: 34, style: "font:11px sans-serif;fill:#5f6b7a" }, gr).textContent = ty.length > 24 ? ty.slice(0, 23) + "…" : ty;
        gr.onclick = () => { ed.forEach(({ p, e }) => p.classList.toggle("hi", e.from === n.id || e.to === n.id)); sel(n, g); }; });
    }
    function sel(n, g) {
      const out = g.edges.filter((e) => e.from === n.id).map((e) => e.to), inn = g.edges.filter((e) => e.to === n.id).map((e) => e.from), v = g.availability[n.type] || {};
      $("tfsSel").innerHTML = `<b>${esc(n.id)}</b><div class="tfs-row">Service: ${esc(n.service)}</div><div class="tfs-row">Status: ${esc(n.status.replace("_", " "))} ${esc(v.reason || "")}</div><div class="tfs-row">Uses: ${out.map(esc).join(", ") || "-"}</div><div class="tfs-row">Used by: ${inn.map(esc).join(", ") || "-"}</div>`;
    }
    function side(g, port) {
      const bad = Object.entries(g.availability).filter(([, v]) => v.status !== "supported");
      $("tfsGaps").innerHTML = bad.length ? bad.map(([t, v]) => `<div class="tfs-row">${esc(t)}<span class="tfs-tag" style="color:${COL[v.status]}">${v.status.replace("_", " ")}</span><div style="color:var(--sub,#5f6b7a)">${esc(v.reason)}</div></div>`).join("") : "None.";
      $("tfsPort").innerHTML = (port || []).map((p) => `<div class="tfs-row"><span class="${p.severity === "error" ? "tfs-err" : p.severity === "warn" ? "tfs-warn" : ""}">${esc(p.severity)}</span> ${esc(p.message)}${p.resource ? `<div style="color:var(--sub,#5f6b7a)">${esc(p.resource)}</div>` : ""}</div>`).join("") || "-";
    }
    const show = () => { $("tfsSrc").textContent = (B && B.files[$("tfsFiles").value]) || ""; };
    async function load() {
      try {
        const [a, b] = await Promise.all([api("/api/terraform/export/graph"), api("/api/terraform/export/bundle?format=json&mode=" + $("tfsMode").value)]);
        G = a; B = b; draw(G); side(G, b.portability); $("tfsFiles").innerHTML = Object.keys(b.files).sort().map((n) => `<option>${esc(n)}</option>`).join(""); show();
      } catch (e) {
        $("tfsCanvas").innerHTML = `<p class="tfs-err">Could not read the stack from ${esc(base() || "this page")}: ${esc(e.message || e)}</p><p style="color:var(--sub,#5f6b7a)">The diagram and export read the Terraform API of the backend that holds your resources (a Vyomi appliance or your Mesh). Connect one, or set its address with localStorage "vyomi.tf.base".</p>`;
      }
    }
    async function imp(files) {
      const types = new Set(); for (const f of files) { const t = await f.text(); for (const m of t.matchAll(/^\s*resource\s+"([a-z0-9_]+)"/gm)) types.add(m[1]); }
      if (!types.size) { $("tfsImp").innerHTML = '<p class="tfs-warn">No resource blocks found.</p>'; return; }
      try {
        const r = await fetch(base() + "/api/terraform/classify", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ types: [...types] }) }).then((x) => x.json());
        const e = Object.entries(r.availability), n = e.filter(([, v]) => v.status !== "supported").length;
        $("tfsImp").innerHTML = `<p>${e.length - n} of ${e.length} resource types can be created in Vyomi.</p>` + e.map(([t, v]) => `<div class="tfs-row"><i style="display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;background:${COL[v.status]}"></i>${esc(t)}<span class="tfs-tag">${v.status.replace("_", " ")}</span>${v.reason ? `<div style="color:var(--sub,#5f6b7a)">${esc(v.reason)}</div>` : ""}</div>`).join("");
      } catch (e) { $("tfsImp").innerHTML = `<p class="tfs-err">Could not check the template: ${esc(e.message || e)}</p>`; }
    }
    host.querySelectorAll(".tfs-tabs button[data-t]").forEach((b) => (b.onclick = () => { host.querySelectorAll(".tfs-tabs button[data-t]").forEach((x) => x.classList.toggle("on", x === b)); $("tfsExport").style.display = b.dataset.t === "export" ? "" : "none"; $("tfsImport").style.display = b.dataset.t === "import" ? "" : "none"; }));
    $("tfsFiles").onchange = show; $("tfsRef").onclick = load; $("tfsMode").onchange = load;
    $("tfsDl").onclick = () => { location.href = base() + "/api/terraform/export/bundle?format=zip&mode=" + $("tfsMode").value; };
    $("tfsPick").onchange = (e) => imp(e.target.files); $("tfsDrop").ondragover = (e) => e.preventDefault(); $("tfsDrop").ondrop = (e) => { e.preventDefault(); imp(e.dataTransfer.files); };
    $("tfsBase").value = base(); $("tfsBase").onchange = () => { try { localStorage.setItem("vyomi.tf.base", $("tfsBase").value.trim()); } catch (_) {} load(); };
    load();
  }
  window.VyomiStudio = { mount };
})();
