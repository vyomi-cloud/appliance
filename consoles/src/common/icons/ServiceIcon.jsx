/* <ServiceIcon cloud="aws"|"azure" id size /> — Vyomi's own (original, non-vendor) service icon
 * set, inline SVG only (no external assets, works offline and in Nano). The GCP lens uses
 * Material outline icons from its registry instead. iconDataUri() gives the same icon as a
 * data: URI for APIs that only take an image URL (e.g. Cloudscape SideNavigation logo). */
import { awsIconMarkup } from "./aws.js";
import { azureIconMarkup } from "./azure.js";

export function iconMarkup(cloud, id, category) {
  return cloud === "aws" ? awsIconMarkup(id, category) : azureIconMarkup(id);
}

export function iconDataUri(cloud, id, category) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">${iconMarkup(cloud, id, category)}</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

export default function ServiceIcon({ cloud, id, category, size = 20, title, style, className }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" focusable="false"
      role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}
      style={{ flex: "none", display: "inline-block", verticalAlign: "middle", ...style }}
      data-vyomi-icon={`${cloud}:${id}`}
      dangerouslySetInnerHTML={{ __html: iconMarkup(cloud, id, category) }} />
  );
}
