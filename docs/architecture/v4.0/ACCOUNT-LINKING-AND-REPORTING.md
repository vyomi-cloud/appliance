# Account linking and account reporting (discussion draft)

Status: DRAFT for discussion, nothing built. Written 2026-11-14 after a real failure (below).
Scope: portal sign-in, tunnel access keys, the console's tunnel strip and install dialog.

## 1. What happened

The owner signed in with GitHub, later with Google, and (earlier) possibly LinkedIn. Each sign-in created a separate Vyomi account.
Symptoms that looked unrelated:

- The console strip said "Your tunnel is signed in to a different account": the tunnel's key belonged to account A, the browser was signed in as account B.
- Reinstall failed with "HTTP 409: You already have 2 access keys". The 2 keys belonged to account B; the key the tunnel actually used belonged to account A, so the key list on the page never showed it.
- The Mesh "health check" returned HTTP 401, possibly for a similar reason (not confirmed).

Nothing told the user which account was which. The system behaved as designed; the user had no way to see it.

## 2. Why it happens (verified in code, portal repo)

- `app/models.py` `User.email` is the unique identity. There is no provider id, no alias table.
- `app/oauth.py` (callback, around lines 318-347): the email returned by the provider is looked up in `User`; if missing, a new `User` is created. GitHub falls back to `/user/emails` primary+verified.
- Same person, different provider, different email (or a GitHub private/no-reply email) means a different `User` row.
- Everything keys off that email: `TunnelAccessKey.user_email`, `TunnelPairing.user_email`, subscriptions, trials, wallet (by `user_id`), Mesh GitHub connection (`MeshGithubConnection.user_email`).
- Access keys are capped at 2 active per account (`MAX_ACTIVE_KEYS`). The installer only replaces keys it created itself (label starts with `installer`), so a user's own keys are never revoked silently.

So "map all logins to one access/secret" needs account linking. But most of the pain in this incident was not knowing, which is a reporting problem.

## 3. Two separable pieces

### A. Reporting (small, no data-model change)

Make the account relationship visible wherever it matters.

| Where | Today | Proposed |
|---|---|---|
| Install dialog | Shows only the command | "Installing for: s***@gmail.com" before the command (the account the code is bound to) |
| Installer output | Prints `account: <email>` after pairing | Keep; also print the masked email before pairing |
| Tunnel strip | "Different account" | "Tunnel belongs to s***@gmail.com. You are signed in as g***@gmail.com." |
| Where the tunnel learns its account | n/a | `POST /api/tunnel/session` returns a masked `account` (the tunnel is authenticated with its own key, so this exposes nothing about other accounts) |
| 2-key limit (409) | Plain error | List the account's keys (id, label, created, last used) with one-click revoke, in the install dialog |
| Access Key page | Shows keys | Also show "Signed in as" and the linked sign-in methods |
| Mesh health check 401 | "HTTP 401" | Shows the simulator's reason code (done: `HTTP 401 (reason)`, commit e140a833e) |

Rule: never reveal anything about an account other than the caller's own, except a masked email for the key the caller authenticated with.

### B. Account linking (data-model change, security-sensitive)

Goal: Google, LinkedIn and GitHub sign-ins that belong to one person resolve to one account, hence one set of keys, one plan.

Sketch:

- New table `UserIdentity(provider, provider_user_id, email, user_id)`; the OAuth callback resolves `(provider, provider_user_id)` first, then email, instead of email only.
- "Link another login" in the account menu: while signed in, start OAuth for another provider with a `link` flag; on callback attach that identity to the current user. Both identities must be proven in the same flow (signed in as the main account AND completed the other provider's sign-in), so nobody can claim an account they do not control.
- Unlink is allowed while at least one identity remains.
- Auto-link on identical verified email stays as it is today.

Open design problem: existing duplicate accounts. Two options:

| Option | Effect | Risk |
|---|---|---|
| Link going forward only | Future sign-ins resolve to the main account; the other accounts' keys, plans and trials stay on those accounts | User must revoke or reuse keys there once |
| Merge existing data | Move keys, subscriptions, trials, wallet rows into the main account | Billing, wallet and subscription collisions; hard to undo |

## 4. Recommendation (for discussion)

1. Do A first (reporting). It would have solved this incident, needs no migration, and is low risk.
2. Treat B as a separate decision. It is a larger, security-sensitive change and needs the duplicate-account policy decided first.
3. If B goes ahead: link going forward only; merge only the owner's own accounts, by hand, as a one-off.

## 5. Open questions

- Which sign-in should be the "main" account for the owner's three existing accounts?
- Are enterprise (GitHub org) accounts allowed to be linked to personal ones? (Enterprise status comes from GitHub org membership, so probably not.)
- Should the Access Key page let a user hold keys from linked identities together, or just one set per account? (With linking, one set per account.)
- Is there an existing support flow for "I have two accounts"? If so, linking could replace it.
- Do we need an audit log entry for link/unlink and for tunnel resets?

## 6. Related, not part of this document

- Tunnel 1.2.3: `vyomi-tunnel reset <code>`, `/reset` re-point from the real vyomi.cloud origin, "Reinstall tunnel" icon.
- Same-machine key replace on reinstall (the installer sends the key id from the local credentials file; the portal replaces it if it is active and belongs to the same account). Useful but does not help when the key is on another account.
