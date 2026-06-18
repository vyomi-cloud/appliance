"""Real SPA Playwright helpers.

This is the layer the old `tests/conformance/ui/_helpers.py` did NOT have —
actual browser clicks, wizard field-fill by type, DOM assertions on the
rendered list. The old tests asserted the API contract; THESE tests
assert what the user actually sees in their browser.

Catches bugs the API-only tests can't:
  * Envelope parser misses (the db_instances bug — shipped today)
  * Auto-refresh wiping selections (the EC2 Stop bug — shipped today)
  * "Create resource" button → submit didn't fire (any future JS regression)
  * Toast errors firing silently with success-looking responses
  * Tab-validate-then-submit logic in multi-tab wizards
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any

import requests
from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")

# Match the navigation timing the SPA actually does. The SPA's render
# pipeline is < 200ms after a navigate() call, so we don't need long
# waits — but the 30s auto-refresh interval CAN clobber a slow assert,
# so we never wait longer than 25s for any list assertion.
_NAV_TIMEOUT_MS = 10_000
_LIST_ASSERT_TIMEOUT_MS = 15_000


# ── Catalog reader (re-used from the API tests) ────────────────────────────

def fetch_catalog(provider: str) -> dict[str, dict]:
    """Returns {service_key: service_meta} for the provider."""
    resp = requests.get(f"{BASE_URL}/api/{provider}/catalog", timeout=5)
    resp.raise_for_status()
    cat = resp.json()
    svcs = cat.get("services") or cat.get("catalog", {})
    if isinstance(svcs, list):
        svcs = {s.get("key", ""): s for s in svcs}
    return svcs or {}


def wizard_fields(svc_meta: dict) -> list[dict]:
    """Flat list of every field across every wizard tab."""
    fields = []
    for tab in (svc_meta.get("wizard") or {}).get("tabs") or []:
        for sec in tab.get("sections") or []:
            for f in sec.get("fields") or []:
                fields.append(f)
    return fields


def wizard_tabs_with_fields(svc_meta: dict) -> list[list[dict]]:
    """Same data grouped by tab. v2.0.4: the SPA's wizard only mounts
    ONE tab's <input> elements at a time — fields in tab 2 don't exist
    in the DOM while tab 1 is showing. So the test has to fill each tab
    in sequence, not all at once."""
    out = []
    for tab in (svc_meta.get("wizard") or {}).get("tabs") or []:
        tab_fields = []
        for sec in tab.get("sections") or []:
            for f in sec.get("fields") or []:
                tab_fields.append(f)
        if tab_fields:
            out.append(tab_fields)
    return out


# ── Navigation ─────────────────────────────────────────────────────────────

def navigate_to_console(page: Page, provider: str) -> None:
    """Open /console/<provider> and wait for the SPA shell to settle.

    Each provider's console gates on the active space matching the
    provider (the `requireAwsSpace` / `requireGcpSpace` / `requireAzureSpace`
    pattern shipped with the native consoles). If the active space
    doesn't match, the page redirects to /clouds. We therefore SWITCH
    to a matching space via the API before loading the console.

    All three consoles also use different rail / main-content selectors:
       aws:   <main id="main"> inside <aside class="service-rail">
       gcp:   <main id="main"> + <aside #rail>
       azure: <nav id="rail">

    Wait for ANY of them after networkidle.
    """
    space_id = {
        "aws":   "space-legacy",       # AWS workspace
        "gcp":   "space-gcp-default",  # GCP workspace
        "azure": "space-azure-default",
    }.get(provider)
    if space_id:
        try:
            requests.post(
                f"{BASE_URL}/api/spaces/{space_id}/switch",
                timeout=3,
            )
        except Exception:
            pass  # Best-effort; the goto below will catch redirect
    page.goto(
        f"{BASE_URL}/console/{provider}",
        wait_until="networkidle",
        timeout=_NAV_TIMEOUT_MS,
    )
    # If we landed on /clouds, the workspace switch didn't take. Skip
    # rather than time out on a selector that doesn't exist.
    if "/clouds" in page.url:
        raise RuntimeError(
            f"console/{provider} redirected to {page.url} — workspace "
            f"context didn't match. POST /api/spaces/{space_id}/switch "
            f"may have failed."
        )
    page.wait_for_selector(
        "#main, main, .main-content, .content",
        timeout=_NAV_TIMEOUT_MS,
        state="attached",
    )


def navigate_to_service(page: Page, provider: str, service_key: str) -> None:
    """Click into a service's list view via the rail. Each provider's
    SPA exposes a different global function for service navigation:

       aws/gcp:  navigate({view:'list', service: KEY})
       azure:    selectService(KEY)

    We call the right one. Both code paths fire the same DOM update
    that a rail-item click would trigger, so the test exercises the
    real user flow.
    """
    if provider == "azure":
        page.evaluate(
            "(svc) => { if (typeof selectService === 'function') "
            "selectService(svc); }",
            service_key,
        )
        # Azure's list header is .toolbar with the service label;
        # wait for any toolbar to appear.
        page.wait_for_selector(
            ".tbtn, .toolbar, .azure-list, [data-service='{service_key}']".format(
                service_key=service_key
            ),
            timeout=_NAV_TIMEOUT_MS,
        )
    else:
        page.evaluate(
            "(svc) => { if (typeof navigate === 'function') "
            "navigate({view:'list', service: svc, item: null}); }",
            service_key,
        )
        # Each console's list view has a different header marker:
        #   AWS: <h1 class="page-h">       (matches h1.page-h)
        #   GCP: <h1> inside .page-head    (no class on h1 → use container)
        # Plus .actions-bar exists in both consoles' list views, contains
        # the Create button, and is always visible — covers any service
        # without one of the above headers.
        # The original selector `.count` matched a span that GCP renders
        # empty + hidden, causing all 9 GCP services to skip with a
        # "not visible" timeout.
        page.wait_for_selector(
            f"h1.page-h, "
            f".page-head h1, "
            f".actions-bar button.primary, "
            f"[data-service='{service_key}']",
            timeout=_NAV_TIMEOUT_MS,
        )


# ── Wizard fill ────────────────────────────────────────────────────────────

def fill_wizard_field(page: Page, field: dict, value: Any) -> bool:
    """Find the input for `field` and set its value. Returns True if
    the field was found + set, False if it was missing or non-fillable.

    The SPA renders fields inside `.field` containers with a child
    <label> + <input>/<select>/<textarea>. We locate the input by the
    label text (the visible name the user reads), not by the field's
    internal `name` attribute — that gives us a more user-faithful
    test (closer to "Playwright clicks where a user clicks").
    """
    name = field.get("name") or ""
    label = field.get("label") or name
    ftype = field.get("type") or "text"

    if not name or ftype in ("info", "divider", "help"):
        return False
    # Synthetic `__*` fields are normally synth_map-driven (no real input),
    # but some are rendered as real inputs whose required-validation must
    # pass before submit (e.g. GCP API Gateway's __serviceAccount__).
    # Skip only the ones that have NO label OR are info-only — those are
    # never rendered as fillable inputs.
    if name.startswith("__") and not field.get("required"):
        return False

    # Strategy: find the input via its label, fall back to the field name
    # attribute, fall back to the placeholder.
    #
    # Each provider's wizard uses a different container class:
    #   AWS / GCP: <div class="field">    <label>X</label> <input/></div>
    #   Azure:     <div class="wiz-field"><label>X</label> <input/></div>
    # The Azure block was missing from the original candidates — that's
    # why all 7 Azure tests submitted with default values (e.g. VM name
    # stayed "vm-demo" instead of the test's "realtest-vm-XYZ"), then
    # the post-submit list assertion failed to find the test identifier.
    candidates = [
        f".field:has(label:has-text(\"{label}\")) input",
        f".field:has(label:has-text(\"{label}\")) select",
        f".field:has(label:has-text(\"{label}\")) textarea",
        f".wiz-field:has(label:has-text(\"{label}\")) input",
        f".wiz-field:has(label:has-text(\"{label}\")) select",
        f".wiz-field:has(label:has-text(\"{label}\")) textarea",
        f"input[name=\"{name}\"]",
        f"select[name=\"{name}\"]",
        f"textarea[name=\"{name}\"]",
    ]
    locator = None
    for c in candidates:
        loc = page.locator(c).first
        if loc.count() > 0:
            locator = loc
            break
    if locator is None or locator.count() == 0:
        return False

    try:
        if ftype in ("select", "radio"):
            # Use the first available option or the catalog-provided value
            opts = field.get("options") or []
            if opts:
                v = str(value if value is not None else opts[0].get("value", ""))
                locator.select_option(v) if locator.evaluate("e => e.tagName") == "SELECT" \
                    else locator.fill(v)
            return True
        if ftype in ("checkbox", "boolean"):
            should_check = bool(value)
            if should_check:
                locator.check()
            else:
                locator.uncheck()
            return True
        # Default: fill as text
        locator.fill(str(value))
        return True
    except Exception:
        return False


def make_value(field: dict, identifier: str) -> Any:
    """Type-appropriate sensible value for a wizard field. Mirrors the
    SPA submit handler's defaults so we don't trigger unnecessary
    validation errors."""
    name = field.get("name") or ""
    ftype = field.get("type") or "text"
    if name in ("name", "Name") or "identifier" in name.lower():
        return identifier
    if name.endswith("_name") or name.endswith("Name"):
        return identifier
    if "default" in field and field["default"] not in (None, ""):
        return field["default"]
    # Identifier-shaped synthetic fields (e.g. GCP API Gateway's
    # __serviceAccount__) have type=None — treat as a plausible email,
    # because GCP rejects bare strings on service-account fields.
    nl = name.lower()
    if "email" in nl or "serviceaccount" in nl or "service_account" in nl:
        return "tester@cloudlearn.local.gserviceaccount.com"
    if ftype in ("number", "integer"):
        return 1
    if ftype in ("password", "secret"):
        return "UiTest-Pw!23"
    if ftype in ("text", "string"):
        return f"uirealtest-{uuid.uuid4().hex[:6]}"
    if ftype == "select":
        opts = field.get("options") or [{}]
        return opts[0].get("value", "")
    if ftype == "radio":
        opts = field.get("options") or [{}]
        return opts[0].get("value", False)
    if ftype in ("checkbox", "boolean"):
        return False
    if ftype == "tagsEditor":
        return {"env": "ui-real-test"}
    # Untyped fields (catalog ftype=None) are most commonly free-text
    # inputs — fall through to a text-shaped value rather than empty
    # string, which would fail any "required" validation downstream.
    return f"uirealtest-{uuid.uuid4().hex[:6]}"


def fill_all_wizard_fields(page: Page, fields: list[dict], identifier: str,
                            overrides: dict | None = None) -> dict[str, Any]:
    """Walk every field, fill it. Returns the values we set so the test
    can assert downstream."""
    overrides = overrides or {}
    set_values: dict[str, Any] = {}
    for f in fields:
        name = f.get("name", "")
        if name in overrides:
            v = overrides[name]
        else:
            v = make_value(f, identifier)
        ok = fill_wizard_field(page, f, v)
        if ok:
            set_values[name] = v
    return set_values


# ── Clicks for create flow ─────────────────────────────────────────────────

def click_create(page: Page) -> None:
    """Click the primary "Create" / "Launch instance" button to open
    the wizard. Each provider uses different class names:

       aws/gcp:  .actions-bar button.primary   (toolbar)
       azure:    .tbtn:has-text("Create")      (toolbar button)

    Combined into one selector with `,` so Playwright matches whichever
    is present + actually waits for it to appear (count()-based polling
    gave up immediately, causing all tests to skip).
    """
    combined_sel = (
        ".actions-bar button.primary, "
        ".actions-bar .btn.primary, "
        ".tbtn:has-text('Create'), "
        "button.tbtn:has-text('Create')"
    )
    primary = page.locator(combined_sel).first
    try:
        primary.wait_for(timeout=_NAV_TIMEOUT_MS, state="visible")
    except Exception as e:
        raise RuntimeError(
            f"Could not find a Create button on the list view: {e}"
        )
    primary.click()
    page.wait_for_selector(
        ".wizard-grid, .wizard-main, .wizard-footer, .blade, .wizard, .btn-primary",
        timeout=_NAV_TIMEOUT_MS,
    )


def walk_wizard_and_submit(page: Page, tabs: list[list[dict]],
                            identifier: str, overrides: dict | None = None) -> dict:
    """Tab-aware wizard fill + submit.

    Walks each tab in order:
      1. Fill the fields visible on the CURRENT tab
      2. If not last tab → click "Next" / "Review and create"
      3. If last tab → click submit ("Create" / "Launch instance" / etc.)

    Returns the values we set (across all tabs). Raises if no submit
    button is found on the last tab.

    Why this isn't fold the old fill_all_wizard_fields into submit_wizard:
    the SPA's wizard mounts ONE tab's DOM at a time. Trying to fill a
    field that lives on tab 5 while tab 1 is showing returns count()==0
    and the field is silently skipped — that's exactly what failed our
    first RDS test (DB instance identifier was on tab 3 but we tried to
    fill from tab 1, so the wizard kept the default `database-1`).
    """
    overrides = overrides or {}
    all_set: dict[str, Any] = {}
    n = len(tabs)

    # Azure wizard has a STEPPER with directly-clickable steps — bypassing
    # the Next-click chain avoids the rerender-timing race that lost field
    # writes on the previous run. Detect Azure by the `.wiz-stepper`
    # presence at start; if found, use stepper navigation instead of
    # Next chaining. AWS/GCP wizards don't have `.wiz-stepper` so they
    # fall through to the original Next-button path.
    is_azure_blade = page.locator(".wiz-stepper").count() > 0

    if is_azure_blade:
        # Walk each catalog tab by clicking its stepper button directly.
        # The Azure wizard's `gotoTab(i)` runs validateTab() on ALL tabs,
        # so submit gating still respects required-field rules.
        steps = page.locator(".wiz-stepper .wiz-step")
        for i, tab_fields in enumerate(tabs):
            if i > 0:
                # Click the i'th stepper button (catalog idx == stepper idx
                # because the synthesized Review tab is at the END).
                steps.nth(i).click()
                page.wait_for_timeout(200)  # let tab DOM swap
            set_on_tab = fill_all_wizard_fields(
                page, tab_fields, identifier, overrides=overrides,
            )
            all_set.update(set_on_tab)
        # Now jump to the synthesized Review tab (last stepper button)
        # and click Create. The synth review tab is steps[n] (0-indexed
        # past the n catalog tabs).
        total_steps = steps.count()
        if total_steps > n:
            steps.nth(total_steps - 1).click()
            page.wait_for_timeout(300)
        # Click Create on the Review tab.
        create_btn = page.locator(
            ".wiz-actions button.btn-primary:has-text('Create')"
        ).first
        if create_btn.count() > 0:
            create_btn.scroll_into_view_if_needed()
            create_btn.click()
            # Give the SPA the round-trip + closeBlade() + selectService()
            # chain time to finish before the caller asserts on the list.
            page.wait_for_timeout(800)
            return all_set
        raise RuntimeError(
            "Azure wizard: no Create button found on synth Review tab"
        )

    # === AWS / GCP path (original Next-chain) ===
    for i, tab_fields in enumerate(tabs):
        # Fill this tab's fields
        page.wait_for_timeout(150)  # let the tab DOM settle
        set_on_tab = fill_all_wizard_fields(
            page, tab_fields, identifier, overrides=overrides,
        )
        all_set.update(set_on_tab)
        # Move to next tab or submit
        if i < n - 1:
            next_btn = page.locator(
                ".wizard-footer button.primary:has-text('Next'), "
                ".wizard-footer button.primary:has-text('Review')"
            ).first
            if next_btn.count() == 0:
                # Wizard collapsed to fewer tabs than catalog declares
                # (some tabs are conditional). Try submit early.
                break
            next_btn.click()
    # Submit. Each provider uses a DIFFERENT selector for the wizard's
    # primary submit button. We try them in order. All fire the same
    # submitWizard() / submit() handler downstream.
    #
    #   AWS:    aside.wizard-summary button.primary   (sidebar
    #           "Create resource" — has explicit wizard-summary class)
    #   GCP:    <aside> > .cta > button.btn.primary   (bare aside, no
    #           wizard-summary class; sidebar has a .cta wrapper)

    candidates = [
        "aside.wizard-summary button.primary",   # AWS sidebar
        ".wizard-summary button.primary",
        ".cta button.primary",                   # GCP sidebar CTA
        "aside button.primary",                  # GCP fallback (bare aside)
        ".btn-primary:has-text('Create')",       # Azure body fallback
        "button.btn-primary",
    ]
    for sel in candidates:
        btn = page.locator(sel).first
        if btn.count() > 0:
            btn.scroll_into_view_if_needed()
            btn.click()
            return all_set
    # Last-ditch — footer button matched by text label
    submit_labels = ("Launch instance", "Create bucket", "Create database",
                      "Create")
    for label in submit_labels:
        btn = page.locator(
            f".wizard-footer button.primary:has-text('{label}'), "
            f".wizard-footer .btn-primary:has-text('{label}')"
        ).first
        if btn.count() > 0:
            btn.scroll_into_view_if_needed()
            btn.click()
            return all_set
    raise RuntimeError(
        "Could not find any submit button on the last wizard tab. "
        "Tried sidebar primary + .btn-primary + footer text labels."
    )


def submit_wizard(page: Page) -> None:
    """Legacy entry — kept for one-tab wizards. New callers should use
    walk_wizard_and_submit() which fills each tab in turn."""
    for _ in range(10):
        next_btn = page.locator(
            ".wizard-footer button.primary:has-text('Next'), "
            ".wizard-footer button.primary:has-text('Review')"
        ).first
        if next_btn.count() == 0:
            break
        next_btn.click()
        page.wait_for_timeout(100)
    submit_labels = ("Create", "Launch instance", "Create bucket",
                      "Create database", "Create resource")
    for label in submit_labels:
        btn = page.locator(
            f".wizard-footer button.primary:has-text('{label}')"
        ).first
        if btn.count() > 0:
            btn.click()
            return
    sidebar_btn = page.locator(
        ".wizard-summary button.primary, aside.wizard-summary button.primary"
    ).first
    if sidebar_btn.count() > 0:
        sidebar_btn.click()
        return
    raise RuntimeError("Could not find any submit button in the wizard")


# ── Assertions on rendered DOM ─────────────────────────────────────────────

def assert_list_contains(page: Page, identifier: str) -> None:
    """The killer assertion the old API tests didn't do: the rendered
    list view actually shows a row containing the identifier. This is
    what would have caught today's `db_instances` envelope bug — the
    backend returned the resource, but the SPA's `data.instances ||
    data.databases || ...` envelope parser didn't know about `db_instances`,
    so renderTable received an empty array and the user saw an empty page.
    """
    # Give the SPA a moment for the post-submit navigate() → render
    # pipeline (POST → toast → navigate({view:'list'}) → fetch → render).
    page.wait_for_timeout(500)
    # The actual row could be in <table> or in a card grid; the identifier
    # text appears either way.
    locator = page.locator(f"table tr:has-text('{identifier}'), "
                            f".empty:has-text('{identifier}'), "
                            f".card:has-text('{identifier}')")
    try:
        expect(locator.first).to_be_visible(timeout=_LIST_ASSERT_TIMEOUT_MS)
    except Exception as e:
        # Capture the empty-list state to make triage actionable.
        empty_msg = page.locator(".empty").first
        if empty_msg.count() > 0:
            txt = empty_msg.inner_text()
            raise AssertionError(
                f"List view rendered EMPTY after create — backend likely "
                f"returned the resource but SPA's envelope parser missed it. "
                f"Empty-state message: {txt!r}. Original: {e}"
            )
        raise


def assert_no_error_toast(page: Page) -> None:
    """No `.toast.err` should be visible. The SPA shows error toasts for
    "Create failed (422)" — the test should fail if one fires."""
    err_toast = page.locator(".toast.err, .toast.error, [class*='toast'][class*='err']")
    if err_toast.count() > 0:
        # Capture the text for triage.
        try:
            text = err_toast.first.inner_text()
        except Exception:
            text = "(could not read toast text)"
        raise AssertionError(f"Error toast fired during create: {text!r}")
