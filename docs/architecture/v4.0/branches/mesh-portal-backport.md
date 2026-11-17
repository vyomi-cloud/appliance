# v4/mesh-portal-backport

**Why:** `wasm/` is the canonical Nano bundle; the portal copy is overwritten by `vendor_to_portal.py --apply`. Four Mesh UI edits were made directly in the portal (`portal/mesh-quota-message`) and would have been reverted by the next vendor.

**Changes (ported byte-for-byte from the portal commits b891fa1..cc3333d):** `mesh-link.js` (status chip shows the failure reason; toast length scales with the message), `mesh-widget.js` and `vyomi-appbar.js` (Mesh hours USED of the allowance; last run length + why it ended), `nano-mesh-drawer.js` (the drawer tab is a cloud-native button). The v4 console `index.html` cache-bust hashes were regenerated because they hash `mesh-link.js`.

**Not ported (portal-only, server side):** `app/mesh_session.py` (quota error mapping, `last_session`), which the appliance does not contain.

**Open:** none known; UI not exercised with a real Mesh session.
