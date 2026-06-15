# Contributing to Vyomi

Thanks for your interest in making Vyomi better.

## Before you open a pull request

Vyomi is released under the **Business Source License 1.1** (see [`LICENSE`](LICENSE)). When you submit a contribution to this repository — code, docs, configuration, or otherwise — you agree that:

1. You authored the contribution yourself (or have the right to submit it on behalf of your employer).
2. You grant Vyomi a perpetual, worldwide, royalty-free, irrevocable license to use, modify, and relicense your contribution under the same BSL 1.1 terms as the rest of the project, and under the future Change License (Apache 2.0) when the change date passes.
3. You understand the project is **source-available, not open source** in the OSI sense, and that contributions become part of the same source-available codebase.

This avoids the need for a separate Contributor License Agreement (CLA) sign-off on every PR. It also gives Vyomi the flexibility to ship paid hosted offerings without each contributor having to be re-approached.

## How to contribute

| Type | Where to start |
|---|---|
| Bug report | Open an issue with a minimal repro |
| Feature request | Open an issue describing the use case before writing code |
| Documentation fix | PR directly — these are always welcome |
| Code fix | Open an issue first if it touches license/tier enforcement, security, or persistence; otherwise PR directly |
| Brand assets / website | Email design@vyomi.cloud |

## Code style

- Match the style of the file you're editing. Vyomi's Python uses standard library + FastAPI; bash uses `set -euo pipefail`; HTML stays vanilla.
- Tests live next to the code they exercise — add a test for the new path or the bug you're fixing.
- Commits squashed before merge; PR descriptions explain the WHY.

## Security

Found a vulnerability? Please email **security@vyomi.cloud** privately rather than opening a public issue. We'll respond within 72 hours.
