# Homebrew formula for Vyomi — the local multi-cloud simulator appliance.
#
# Tap install (recommended):
#   brew tap vyomi-cloud/tap
#   brew install cloud-learn
#
# Direct install (no tap):
#   brew install --HEAD https://github.com/vyomi-cloud/appliance.git
#
# This formula is auto-updated by .github/workflows/release.yml on every
# v*.*.* tag — the url + sha256 are bumped to the tarball published with
# the GitHub Release, then committed to vyomi-cloud/homebrew-tap.

class Vyomi < Formula
  desc "Local multi-cloud simulator (AWS/GCP/Azure) with real backends"
  homepage "https://vyomi.cloud"
  url "https://github.com/vyomi-cloud/appliance/archive/refs/tags/v2.0.7.tar.gz"
  sha256 "REPLACED_BY_RELEASE_WORKFLOW"
  license :cannot_represent  # BSL 1.1 — not in SPDX simple form
  version "2.0.7"

  # v2.0.1 — the launcher uses socat to forward 127.0.0.1:{9000,9443} →
  # VM_IP:{9000,9443} so users always hit https://localhost:9443/ (which
  # browsers universally trust, sidestepping HSTS / Secure DNS / HTTPS-
  # First Mode gotchas). Bash launcher falls back gracefully if socat is
  # missing, but it's the recommended path now.
  depends_on "socat"
  # mkcert provides the locally-trusted CA so the HTTPS cert at
  # ~/.vyomi/tls/ shows a green padlock. The launcher auto-installs it
  # via `brew install mkcert` on first run if missing — but declaring it
  # here means brew pre-fetches it during `brew install vyomi`, so the
  # first `vyomi up` is one prompt shorter.
  depends_on "mkcert"

  # Note: multipass and Docker Desktop ship as casks, not formulae, so we
  # can't `depends_on` them directly from a Formula. They're listed in
  # `caveats` instead — users install them via `brew install --cask`, OR
  # `vyomi up` itself offers to run `brew install --cask multipass`
  # for them on first launch (see maybe_install_multipass in scripts/cloud-learn).

  def install
    # Ship the launcher + the appliance compose + the source the appliance VM
    # syncs in as /workspace/cloud-learn.
    libexec.install Dir["*"]

    # ── Primary binary: vyomi ──────────────────────────────────────────────
    # The actual command users should type going forward. Sets the launcher
    # environment and shells into the bundled bash launcher.
    (bin/"vyomi").write <<~EOS
      #!/usr/bin/env bash
      export CLOUD_LEARN_HOME="#{libexec}"
      export CLOUDLEARN_DISTRIBUTION_MODE="appliance"
      exec bash "#{libexec}/scripts/cloud-learn" "$@"
    EOS
    chmod 0555, bin/"vyomi"

    # ── Legacy shim: cloud-learn → vyomi with deprecation warning ──────────
    # Existing muscle memory keeps working. The warning is brief (one line)
    # and printed on every invocation by default, but can be suppressed via
    # VYOMI_NO_DEPRECATION_WARN=1 for scripts that hit the shim often.
    # Slated for removal in v3.0.
    (bin/"cloud-learn").write <<~EOS
      #!/usr/bin/env bash
      if [ -z "$VYOMI_NO_DEPRECATION_WARN" ] && [ -t 2 ]; then
        printf '\033[33mNote:\033[0m \033[2m`cloud-learn` is deprecated. Use `vyomi` instead. Suppress: VYOMI_NO_DEPRECATION_WARN=1\033[0m\n' >&2
      fi
      exec "#{bin}/vyomi" "$@"
    EOS
    chmod 0555, bin/"cloud-learn"

    # ── Bash completion (for both invocations) ─────────────────────────────
    completion = <<~EOS
      _vyomi() {
        local cur="${COMP_WORDS[COMP_CWORD]}"
        local cmds="up down stop restart status doctor help"
        COMPREPLY=( $(compgen -W "$cmds" -- "$cur") )
      }
      complete -F _vyomi vyomi
      complete -F _vyomi cloud-learn
    EOS
    (bash_completion/"vyomi").write completion
  end

  # ── Install-funnel phone-home ───────────────────────────────────────────
  # Fires a single anonymous POST to https://vyomi.cloud/api/install/register
  # marking this install as DOWNLOADED state, channel=brew. The portal
  # later upgrades the same install_id to INSTALLED on first `vyomi up`,
  # so we can measure brew→activation conversion.
  #
  # No PII: just install_id (random 16-char hex, persisted at
  # ~/.vyomi/install_id), version, host_os, channel.
  #
  # Opt-out: HOMEBREW_NO_ANALYTICS or VYOMI_NO_TELEMETRY env vars suppress
  # the call. Fail-soft — a network error never breaks `brew install`.
  def post_install
    # Honour brew's standard telemetry opt-out as well as ours.
    return if ENV["HOMEBREW_NO_ANALYTICS"].to_s != "" && ENV["HOMEBREW_NO_ANALYTICS"] != "0"
    return if ENV["VYOMI_NO_TELEMETRY"].to_s != "" && ENV["VYOMI_NO_TELEMETRY"] != "0"
    script = "#{libexec}/packaging/common/phone-home.sh"
    return unless File.executable?(script)
    # `system` returns false on non-zero; we ignore the return value because
    # telemetry failures must never propagate. 4s wall-clock cap: 3s curl
    # timeout + ~1s for the rest.
    Process.fork do
      ENV["VYOMI_VERSION"] = version.to_s
      exec("/bin/sh", script, "brew")
    end
  rescue StandardError
    # Swallow anything (no curl, no /bin/sh, no fork) — telemetry is
    # strictly best-effort.
  end

  def caveats
    <<~EOS
      Vyomi ships as an appliance — it starts a single Multipass VM
      and runs the full simulator stack (FastAPI + 8 real backends) inside.

      Prerequisites:
        • Multipass         (brew install --cask multipass)
        • Docker            (auto-installed inside the VM)
        • ~32 GB free disk  (VM image + container layers)

      Get started:
        vyomi up                          # boots VM + simulator (5-10 min first run)
        # Browser opens automatically at https://localhost:9443/ (green padlock).

      Stop with:
        vyomi down

      Full docs:
        https://github.com/vyomi-cloud/appliance/blob/main/README.md
    EOS
  end

  test do
    # Both invocations should work — vyomi as primary, cloud-learn as the
    # back-compat shim. `help` runs without Multipass / Docker present.
    assert_match "vyomi", shell_output("#{bin}/vyomi help 2>&1", 0)
    # Shim should also work but prints the deprecation warning to stderr
    # (which our shell_output capture includes when 2>&1).
    assert_match "cloud-learn", shell_output("#{bin}/cloud-learn help 2>&1", 0)
  end
end
