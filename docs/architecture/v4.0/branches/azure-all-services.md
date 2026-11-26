# v4/azure-all-services

Azure console "All services" rebuilt to mirror the real portal's All services blade (captured read-only from portal.azure.com, 1200x828).

## What changed (consoles/src/azure only)
- `pages/AllServices.jsx`: left list (All / Favorites / Recents / Categories with the 18 real categories), `Filter services` (live, list layout with bold match, Enter opens the first hit, empty state), Service providers / Release Status pills (functional menus), Detail view toggle, featured row, per-category headings with counts and collapse, real subcategory groups (e.g. Compute: IaaS / PaaS / Serverless / HPC; Networking link groups), cards with favorite star, Create (dropdown chevron where the portal has one), View, PREVIEW / PARTNER tags. Category deep links: `#/allservices?cat=Compute`.
- `services/allServicesCatalog.js`: names, descriptions, ordering, groups (text only, generated from the capture).
- `kit/allServicesModel.js`, `kit/portalFavorites.js`: catalog entry -> registry service resolution; favorites in localStorage (per viewer).
- `kit/PortalMenu.jsx`: hamburger flyout (Create a resource, Home, Dashboard, All services, FAVORITES = the same favorites list). `App.jsx` only swaps the old inline menu for it and hides the breadcrumb on this page (the real blade has none).
- Services Vyomi does not simulate stay listed (as in the real portal) with a "Not simulated" tag and open `#/allservices/<slug>`, an honest not-simulated page. Simulated ones open their v4 blade; Create goes to `#/<svc>/create` where that route exists.
- Test: `consoles/tests/smoke-azure-all-services.mjs`.

## Remaining differences (honest list)
- Icons: Vyomi's own glyphs (registry rule: no Microsoft service icons); catalog-only services share a generic glyph. Real portal uses Microsoft's per-service artwork.
- Fonts render in the browser's Segoe UI fallback; sub-pixel and 2-3 px vertical offsets remain (cards ~1px taller/shorter).
- Featured row shows the 5 tiles the real portal shows at 1200 px wide; the real portal's wider breakpoints (8 tiles) are not replicated.
- Filter searches names only; the real portal also matches keywords / resource types, shows "Keywords:" sublines, and has a global-search dropdown (that is the top search box, untouched).
- Real search ordering is relevance-ranked server-side; ours is starts-with first, then catalog order.
- Service providers / Release Status values are derived (PARTNER / PREVIEW tags); the real values come from the portal's catalog metadata.
- Favorites default to the real portal's default list; the real portal stores them per Entra user. Recents reads Vyomi's recent-resources list (real portal recents are server-side).
- No "Give feedback" section at the bottom of the blade; Recents/Favorites empty states are our own wording (real empty states were not captured).
- Card Create menus (dropdown items such as Application gateway > Application gateway / Application gateway for containers) open the service's list/create page instead of a dropdown.
- Catalog reflects the signed-in tenant's view captured 2026-11-25; the real list changes over time.
- The Detail-view-off (compact list) layout was not captured from the real portal (the toggle did not respond to the automated click); ours uses the same row style the real filter-results view uses.

## Scope update (2026-11-26, v4/azure-all-services-scope)
Owner: the All services list shows only the services in scope. A catalog entry is listed only when the registry simulates it (`entry(name).simulated`): this applies to the All view, category views, filter results, favorites (and the hamburger favorites), the featured row, and the left category list (a category with nothing in scope is hidden). The "Not simulated" cards are gone; a deep link `#/allservices/<slug>` still opens the honest not-simulated page. The captured real-portal catalog (services/allServicesCatalog.js) is kept as the source of names/descriptions/order.
