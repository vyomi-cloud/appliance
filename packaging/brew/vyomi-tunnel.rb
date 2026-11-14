# Homebrew formula for the Vyomi-Nano local tunnel.
#
# Ship this in the tap repo `vyomi-cloud/homebrew-tap` so users can:
#     brew install vyomi-cloud/tap/vyomi-tunnel
#     vyomi-tunnel
#
# At release: publish `packaging/tunnel` to npm (`npm publish`) so the tarball
# URL below resolves, then fill in the sha256:
#     curl -sL https://registry.npmjs.org/vyomi-tunnel/-/vyomi-tunnel-<VER>.tgz | shasum -a 256
# (Or point `url` at a GitHub release asset built from packaging/tunnel.)
class VyomiTunnel < Formula
  desc "Local reverse-tunnel to reach the in-browser Vyomi-Nano cloud sim from any SDK/CLI"
  homepage "https://vyomi.cloud"
  url "https://registry.npmjs.org/vyomi-tunnel/-/vyomi-tunnel-1.0.0.tgz"
  sha256 "2f6773b0371077f7f46cb71249e3c6de32c19145210f0c86c51c8359af542297"
  license "MIT"

  depends_on "node"

  def install
    system "npm", "install", *std_npm_args
    bin.install_symlink Dir["#{libexec}/bin/*"]
  end

  test do
    # The relay itself needs a Vyomi access key (gated since 1.2.x), which `brew test` does not have.
    # Test what works without one: the version, and the bundled MCP server answering an initialize.
    assert_match version.to_s, shell_output("#{bin}/vyomi-tunnel --version")
    init = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18",' \
           '"capabilities":{},"clientInfo":{"name":"brew-test","version":"0"}}}'
    out = pipe_output("#{bin}/vyomi-tunnel mcp 2>/dev/null", "#{init}\n")
    assert_match "\"serverInfo\":{", out
    assert_match "\"name\":\"vyomi\"", out
  end
end
