# Install-count telemetry — under-counting (to revisit)

Status: **DIAGNOSED, fix not yet implemented** · Opened 2026-07-15

## Symptom
~225 installs reported, but the portal install funnel shows **1**.

## Verdict: the portal is NOT the bug
The portal frontend + backend logic are **correct**. The count faithfully reports
the number of distinct `install_id`s that registered:
- `POST /api/install/register` (`portal/app/installs.py`) is an **idempotent upsert
  keyed on `install_id`** (the primary key) — one row per distinct install, by design.
- The admin count (`GET /api/admin/installs`) is a straight `count(install_id)` per
  state — no over-collapsing `DISTINCT`, no hidden filter.
- The frontend just renders the returned number.

So "225 → 1" means **only one distinct `install_id` ever reached the portal.** The
problem is entirely **upstream** — in how installs generate/report their id.

## Root causes (upstream)

### #1 — winget/MSI installs never phone home
- scoop / brew / deb / rpm run `packaging/common/phone-home.{ps1,sh}` on install →
  they register a `DOWNLOADED` event with a **unique per-machine id**.
- The **Windows MSI has no phone-home** — there is **no custom action** in
  `packaging/windows/cloudlearn.wxs`. So a winget/MSI install is **invisible** to the
  portal until the user actually runs `vyomi up` and the appliance registers itself.
- Net: N downloads/installs but few boots → the portal only sees the boots.

### #2 — Windows/Max path: the appliance `install_id` can collapse
- The appliance id comes from `core/license_remote.get_or_create_install_id(state)`:
  1. `STATE['install_id']` if already set,
  2. `$VYOMI_INSTALL_ID` env (forwarded from the package-manager id),
  3. fallback `SHA-256(hostname | /data-inode | uuid.getnode()-MAC)[:24]`.
- The **bash launcher** (`scripts/cloud-learn`) forwards `$VYOMI_INSTALL_ID` from
  `~/.vyomi/install_id`, **but the Windows PowerShell launcher AND the new Go
  launcher (`cmd/vyomi/`) do NOT forward it** into the VM/appliance container.
  (The Windows path is `vyomi.exe → multipass exec … bash cloud-learn up`, and the
  host's id is never synced into the VM.)
- So on Windows/Max the appliance falls to the **hardware-hash fallback**, whose
  inputs (container hostname / a fresh `/data` volume inode / docker-assigned MAC) can
  be **identical across cloned/standardized appliance containers** → multiple real
  machines share one `install_id` → they merge into a single portal row.

## Proposed fix (ships in the same `vyomi.exe` / MSI)
1. **Make `vyomi.exe` phone home itself** — compiled (winget-safe, no script):
   generate + persist a unique id at first run and `POST /api/install/register`
   (state `DOWNLOADED`/`INSTALLED`). Closes gap #1 so MSI/winget installs count.
2. **Forward the id into the appliance** — pass `VYOMI_INSTALL_ID` through the
   `multipass exec … cloud-learn up` invocation (and the PS1 launcher, for parity with
   the bash one) so DOWNLOADED→INSTALLED link and each machine stays distinct.
3. **Harden the fallback** — in `get_or_create_install_id`, replace the collapsing
   hardware hash with a **persisted random UUID** (stable across restarts via the
   `/data` state, unique per install) so distinct installs can never merge.

## To do when we revisit
- [ ] Implement fixes 1–3 above.
- [ ] Reset the portal `applianceinstall` table for a clean baseline (backup first —
      `CREATE TABLE applianceinstall_backup_<date> AS TABLE applianceinstall;` then
      `DELETE FROM applianceinstall;` via the Render `cloudlearn-data` DB console).
- [ ] Re-observe: each real install (MSI/winget included) should now produce a
      distinct row; downloads-that-never-boot become visible as `DOWNLOADED`.

## Evidence / file refs
- Portal register + count: `portal/app/installs.py` (`register_install`, `admin_installs`).
- Portal model (PK `install_id`): `portal/app/models.py` (`ApplianceInstall`).
- Appliance id: `appliance/core/license_remote.py:482` (`get_or_create_install_id`).
- Phone-home client (has unique id; not run by MSI): `packaging/common/phone-home.ps1`.
- MSI (no phone-home custom action): `packaging/windows/cloudlearn.wxs`.
- Launcher id-forwarding present in bash only: `scripts/cloud-learn` (~L142–196);
  absent in `scripts/cloud-learn.ps1` and `cmd/vyomi/`.
