# v4/mesh-drawer-align

**What:** the Vyomi Mesh drawer's content (welcome alert, video + Global Mesh cards) lines up with each console's own content column.

**Design:** `#vy-md .md-body` is `max-width: calc(--md-cw + 2 * --md-px)` with `--md-px` side padding. Each cloud sets `--md-cw` (widest content) and `--md-px` (inset): AWS 1280 / 24 (20 below 688px), Azure 1052 / 24, GCP 996 / 72 (40 at 600-899px, 24 below 600px). The tab button stays centred.

**Verified (real Chrome, 1440-390px, open and closed):** alert edges equal the console content edges to 0px on all three clouds.

**Open:** the consoles themselves scroll sideways below ~800px with the Nano backend not booted; that is not caused by the drawer.
