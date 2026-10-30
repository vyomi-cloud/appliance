/* The "Services" mega-menu (category list → services) and the unified search box. */
import { useMemo, useState } from "react";
import Autosuggest from "@cloudscape-design/components/autosuggest";
import Box from "@cloudscape-design/components/box";
import Grid from "@cloudscape-design/components/grid";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { CATEGORIES, SERVICES } from "../services/registry.js";
import { follow } from "../../common/router.js";

export default function ServicesMenu({ onClose }) {
  const [cat, setCat] = useState("All services");
  const list = cat === "All services" ? SERVICES : SERVICES.filter((s) => s.category === cat);
  return (
    <div role="dialog" aria-label="Services" style={{ background: "var(--color-background-container-content-z1fmhj, #fff)", borderBottom: "1px solid #d1d5db", boxShadow: "0 4px 12px rgba(0,0,0,.15)", maxHeight: "70vh", overflow: "auto" }}>
      <Box padding="l">
        <Grid gridDefinition={[{ colspan: 3 }, { colspan: 9 }]}>
          <SpaceBetween size="xs">
            {["All services", ...CATEGORIES].map((c) => (
              <Button key={c} variant={c === cat ? "primary" : "link"} onClick={() => setCat(c)}>{c}</Button>
            ))}
          </SpaceBetween>
          <SpaceBetween size="m">
            <Box variant="h2">{cat}</Box>
            <Grid gridDefinition={list.map(() => ({ colspan: { default: 12, s: 6 } }))}>
              {list.map((s) => (
                <div key={s.id}>
                  <Link href={`#/${s.id}`} onFollow={(e) => { follow(e); onClose(); }} fontSize="heading-s">{s.title}</Link>
                  <Box variant="small" display="block" color="text-body-secondary" margin={{ top: "xxxs" }}>{s.description}</Box>
                </div>
              ))}
            </Grid>
          </SpaceBetween>
        </Grid>
      </Box>
    </div>
  );
}

ServicesMenu.Search = function Search() {
  const [value, setValue] = useState("");
  const options = useMemo(() => SERVICES.map((s) => ({ value: s.id, label: s.title, description: s.description })), []);
  return (
    <Autosuggest
      value={value}
      options={options}
      placeholder="Search"
      ariaLabel="Search services"
      enteredTextLabel={(v) => `Search for "${v}"`}
      empty="No matching services"
      filteringType="auto"
      onChange={({ detail }) => setValue(detail.value)}
      onSelect={({ detail }) => { if (detail.value) location.hash = `/${detail.value}`; setValue(""); }}
    />
  );
};
