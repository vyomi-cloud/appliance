# Homebrew formula for vyomi-docker — the Docker-substrate launcher for the
# Free / Lite / Pro tiers. Installs only the `vyomi` wrapper + the pull-only
# docker-compose.cloudlite.yml; `vyomi up` = `docker compose up`. NO Multipass.
#
#   brew tap vyomi-cloud/tap
#   brew install vyomi-docker
#
# For real VMs (Max tier) use the `cloud-learn` formula instead — the two
# conflict (both install a `vyomi` binary).
#
# Auto-updated by .github/workflows/release.yml (url + sha256 + version bumped
# to the release tarball, committed to vyomi-cloud/homebrew-tap).
class VyomiDocker < Formula
  desc "Vyomi (Docker) — Free/Lite/Pro: docker compose up, no Multipass"
  homepage "https://vyomi.cloud"
  url "https://github.com/vyomi-cloud/appliance/releases/download/v2.2.1/cloud-learn-2.2.1.tar.gz"
  sha256 "REPLACED_BY_RELEASE_WORKFLOW"
  license :cannot_represent  # BSL 1.1 — not in SPDX simple form
  version "2.2.1"

  conflicts_with "cloud-learn", because: "both install a `vyomi` launcher"

  def install
    # Minimal: the thin Docker wrapper + the pull-only compose file. The
    # wrapper resolves the compose path relative to itself, so the Homebrew
    # share/ layout works without extra config.
    bin.install "packaging/docker/vyomi" => "vyomi"
    (share/"vyomi-docker").install "docker-compose.cloudlite.yml"
  end

  def caveats
    <<~EOS
      vyomi-docker runs the simulator via Docker. Install Docker Desktop first:
        brew install --cask docker

      Then:
        vyomi up      # docker compose up → http://localhost:9000
        vyomi down

      Free/Lite = full API/SDK conformance (no compute); Pro unlocks EC2-on-Docker
      with SSH. For real VMs (Max tier), use the `cloud-learn` formula.
    EOS
  end

  test do
    assert_match "Docker substrate", shell_output("#{bin}/vyomi --help")
  end
end
