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
  sha256 "REPLACE_WITH_TARBALL_SHA256_AT_RELEASE"
  license "MIT"

  depends_on "node"

  def install
    system "npm", "install", *std_npm_args
    bin.install_symlink Dir["#{libexec}/bin/*"]
  end

  test do
    port = free_port
    pid = spawn({ "RELAY_PORT" => port.to_s }, bin/"vyomi-tunnel")
    sleep 2
    begin
      out = shell_output("curl -s http://127.0.0.1:#{port}/health")
      assert_match "\"relay\":\"vyomi-local\"", out
    ensure
      Process.kill("TERM", pid)
    end
  end
end
