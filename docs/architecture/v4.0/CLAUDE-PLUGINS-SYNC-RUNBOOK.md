# Runbook: publishing the Claude plugins to vyomi-cloud/claude-plugins

`integrations/claude-plugins/` in this repo is the **source of truth**. The public marketplace
`vyomi-cloud/claude-plugins` is a **mirror** that users and agents install from:

- Claude Code / Copilot CLI: `.claude-plugin/marketplace.json`
- Codex: `.agents/plugins/marketplace.json`
- Cursor and cursor.directory: `.cursor-plugin/marketplace.json`
- the Claude plugin directory: the `plugins/<name>` folder

Never edit the mirror by hand: the next sync overwrites it.

## How it syncs (CI/CD)

Two workflows mirror the folder, both through `scripts/sync_claude_plugins.py`, sharing the concurrency group
`claude-plugins-mirror` so they never push at the same time:

| Workflow | Trigger | Use it for |
|---|---|---|
| `.github/workflows/claude-plugins-sync.yml` | a `claude-plugins-v*` tag | Plugin-only changes (skills, manifests, the hosted `vyomi-cloud` plugin, README) |
| `.github/workflows/tunnel-release.yml`, job `plugin-sync` | a final `tunnel-v*` release | Changes that need a new vyomi-tunnel (the `vyomi` plugin's npx pin moves to the new version) |

Both run the same guards, so a sync can never publish something broken:

1. `check_agent_plugins.py`: every manifest (Claude, Codex, Cursor, Agent Plugins) agrees, the npx pin equals
   `packaging/tunnel/package.json`, and the OpenAI listing limits hold.
2. **Version guard**: changed plugin content needs a higher version, because Claude Code only updates on a new version.
   The same or a lower version with different content is refused. Unchanged content is a no-op.
3. **npm guard**: the `vyomi` plugin runs `npx -y vyomi-tunnel@<pin> mcp`. The sync refuses if npm doesn't serve that
   version yet.
4. `claude plugin validate` on the mirrored marketplace.
5. Push to `main` of `vyomi-cloud/claude-plugins` with `CLAUDE_PLUGINS_TOKEN`.

## Publishing a plugin-only change

1. In a topic PR: change `integrations/claude-plugins/...` and **bump the version** of every plugin whose content
   changed. The version lives in its `plugin.json` files (`.claude-plugin/`, `.codex-plugin/`, `.cursor-plugin/`, root
   `plugin.json`) and in each marketplace file. `python3 scripts/check_agent_plugins.py` tells you what is out of step.
2. Merge into `v4-on-main`.
3. Tag and push (owner; the repo's pre-push hook refuses tags, so use `--no-verify`):

   ```sh
   git fetch -q origin
   git tag claude-plugins-v4.3.0 origin/v4-on-main          # name it after the highest plugin version
   git push --no-verify origin claude-plugins-v4.3.0
   ```

4. Watch **Actions → Claude plugins sync**. The summary says what was pushed, or "unchanged".
5. Check the mirror: `gh api repos/vyomi-cloud/claude-plugins/contents/.claude-plugin/marketplace.json --jq .content | base64 -d`
6. Users pick it up on their next marketplace update. Listings that point at the repo (cursor.directory, the
   Claude directory) re-scan the new commit.

## Dry run

`workflow_dispatch` with `dry_run: true` runs every guard and the validation, and pushes nothing. GitHub only offers
**Run workflow** for workflows on the default branch (`main`), so this button appears after the next promotion of
`v4-on-main` to `main`. Until then, run it locally:

```sh
git clone -q https://github.com/vyomi-cloud/claude-plugins.git /tmp/marketplace
python3 scripts/check_agent_plugins.py
python3 scripts/sync_claude_plugins.py /tmp/marketplace                 # report: changed=..., version=...
python3 scripts/sync_claude_plugins.py /tmp/marketplace --apply --tunnel-version "$(python3 -c 'import json;print(json.load(open("packaging/tunnel/package.json"))["version"])')"
npx -y @anthropic-ai/claude-code plugin validate /tmp/marketplace
```

## Manual fallback (Actions down)

Run the dry run above, then push from `/tmp/marketplace` with an account that can write to the mirror. Use the same
commit message shape (`<versions> (manual; vyomi-tunnel <pin>)`). Never push content the guards refused.

## If something is wrong

| Symptom | Cause | Fix |
|---|---|---|
| `changed content needs a version bump` | Content changed, version didn't | Bump the plugin's version everywhere `check_agent_plugins.py` lists, merge, tag again |
| `pin ... is not on npm` | `packaging/tunnel/package.json` is ahead of npm (an unreleased tunnel bump) | Release the tunnel first (`tunnel-v*`); its `plugin-sync` job publishes the plugins |
| `CLAUDE_PLUGINS_TOKEN missing` / push 403 | The token expired or lost access to the mirror | Renew it (fine-grained, `contents: write` on `vyomi-cloud/claude-plugins`) and update the secret |
| `plugin validate` fails | A manifest the checker doesn't cover is malformed | Fix it in the source folder and tag again; nothing was pushed |
| Summary says "unchanged" | The mirror already has this content | Nothing to do |
