/* Internal hash links styled like the console's blue text links. */
import { Link as MuiLink } from "@mui/material";

export const hashHref = (...parts) => "#/" + parts.map((p) => encodeURIComponent(p)).join("/");

export function Link({ to, href, children, ...rest }) {
  return <MuiLink href={href || to} underline="hover" sx={{ fontWeight: 500 }} {...rest}>{children}</MuiLink>;
}
