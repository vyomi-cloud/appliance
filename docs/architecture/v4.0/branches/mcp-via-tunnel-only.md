# v4/mcp-via-tunnel-only

**Why:** owner decision — the MCP becomes a binary *inside* vyomi-tunnel instead of a separate distribution.

**Changes:** `release.yml` no longer builds `vyomi-mcp` or publishes the five `vyomi-mcp-<ver>-<os>-<arch>` release assets; the deb/rpm builder and the `vyomi-docker` Homebrew formula stop shipping it (caveat now says `claude mcp add --scope user vyomi -- vyomi-tunnel mcp`); the `vyomi mcp` launchers (`packaging/docker/vyomi`, `scripts/cloud-learn`) print where to get it and exit 1 (`VYOMI_MCP_BIN` override kept). `cmd/vyomi` Go code is unchanged: the tunnel still builds it via `scripts/build_tunnel_mcp.sh`.

**Not changed:** `mcp-knowledge-drift` job (still compares against the npm tunnel); the Windows MSI (`vyomi.exe mcp`); `.gitignore` entry for `packaging/docker/mcp/` (harmless).

**Open:** the offline MSI/deb/rpm packages still build (Mesh-only pipeline change is separate); existing users of `vyomi mcp` from brew/deb/rpm must move to `vyomi-tunnel mcp`; `.github/workflows/release.yml` is under the owner's workflow-permission rule.
