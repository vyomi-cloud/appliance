// Vyomi console-next — boot entry.
//
// Resolves the asset/API base (set by index.html), injects the design tokens as a
// global stylesheet (so they inherit into every Shadow root), then imports the
// component tree. NO substrate branching lives here — the app reads the capability
// manifest at runtime (§15.2).

const ASSET_BASE = window.__VY_ASSET_BASE || '/console-next-assets/';
const API_BASE = window.__VY_API_BASE || '/';

// Inject the design tokens globally. Custom properties are inherited, so they
// pierce Shadow DOM boundaries and theme every component.
(function injectTokens() {
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = ASSET_BASE + 'tokens.css';
  document.head.appendChild(link);
})();

// Boot the app after the component module registers <vyomi-console>.
import(ASSET_BASE + 'app.js')
  .then(() => {
    const msg = document.getElementById('boot-msg');
    if (msg) msg.remove();
  })
  .catch((err) => {
    const msg = document.getElementById('boot-msg');
    if (msg) msg.textContent = 'Failed to load console: ' + err;
    // eslint-disable-next-line no-console
    console.error('[console-next] boot failed', err);
  });

// Export bases for the api module (imported via a well-known global).
window.__VY = { ASSET_BASE, API_BASE };
