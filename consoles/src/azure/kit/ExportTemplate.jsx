/* Export template blade body shared by every Azure resource blade. The ARM / Bicep / Terraform
 * tabs are produced by the real ARM exportTemplate action (core/azure_templates_core.py):
 *   POST /subscriptions/{sub}/resourcegroups/{rg}/exportTemplate  {resources:[id]|["*"]}
 * so the same template an SDK/CLI export returns is what the console shows. */
import { useState } from "react";
import { Checkbox, Tab, TabList, Textarea, ToolbarButton } from "@fluentui/react-components";
import { ArrowDownload20Regular, Copy20Regular } from "@fluentui/react-icons";
import { restJson } from "../../common/wire.js";
import { useAsync } from "../../common/useAsync.js";
import { getSubscription } from "./arm.js";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, Loading } from "./common.jsx";

const EXT = { arm: ["json", "application/json"], bicep: ["bicep", "text/plain"], terraform: ["tf", "text/plain"] };

export default function ExportTemplate({ id, name, resourceGroup, all = false, title }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const rg = resourceGroup || (id || "").split("/").filter(Boolean)[3];
  const { data, loading, error } = useAsync(() => restJson("POST", `/subscriptions/${getSubscription()}/resourcegroups/${encodeURIComponent(rg)}/exportTemplate`,
    { query: { "api-version": "2021-04-01" }, body: { resources: all ? ["*"] : [id], options: "IncludeParameterDefaultValue", vyomiIncludeParameters: params } }), [id, rg, params, all]);
  const text = !data ? "" : tab === "arm" ? JSON.stringify(data.template, null, 2) : tab === "bicep" ? data.bicep : data.terraform;
  const [ext, mime] = EXT[tab];
  const download = () => {
    const el = document.createElement("a");
    el.href = URL.createObjectURL(new Blob([text], { type: mime }));
    el.download = `${name || rg}.${ext}`;
    document.body.appendChild(el); el.click(); el.remove();
    setTimeout(() => URL.revokeObjectURL(el.href), 1000);
  };
  return (
    <>
      <div className="vy-panel-title">{title || `${name} | Export template`}</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Export template commands">
        <ToolbarButton icon={<ArrowDownload20Regular />} disabled={!data} onClick={download}>Download</ToolbarButton>
        <ToolbarButton icon={<Copy20Regular />} disabled={!data} onClick={() => navigator.clipboard?.writeText(text)}>Copy</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Export template tabs">
        <Tab value="arm">ARM Template</Tab>
        <Tab value="bicep">Bicep</Tab>
        <Tab value="terraform">Terraform</Tab>
      </TabList>
      <CapabilityContainer id="azure.common.export_template" title="Template">
        <Checkbox label="Include parameters" checked={params} onChange={(_, d) => setParams(!!d.checked)} />
        <ErrorBar error={error} title="Failed to export the template" />
        {loading ? <Loading /> : <Textarea readOnly aria-label={`${tab} template`} data-testid="export-text" value={text} style={{ width: "100%", minHeight: 320, fontFamily: "monospace" }} />}
      </CapabilityContainer>
    </>
  );
}
