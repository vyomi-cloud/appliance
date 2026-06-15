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
  url "https://github.com/vyomi-cloud/appliance/archive/refs/tags/v1.0.0.tar.gz"
  sha256 "REPLACED_BY_RELEASE_WORKFLOW"
  license :cannot_represent  # BSL 1.1 — not in SPDX simple form
  version "1.0.0"

  # Note: multipass and Docker Desktop ship as casks, not formulae, so we
  # can't `depends_on` them directly from a Formula. They're listed in
  # `caveats` instead — users install them via `brew install --cask`, OR
  # `cloud-learn up` itself offers to run `brew install --cask multipass`
  # for them on first launch (see maybe_install_multipass in scripts/cloud-learn).

  def install
    # Ship the launcher + the appliance compose + the source the appliance VM
    # syncs in as /workspace/cloud-learn.
    libexec.install Dir["*"]

    # Wrapper that sets CLOUD_LEARN_HOME and shells into the bundled launcher
    (bin/"cloud-learn").write <<~EOS
      #!/usr/bin/env bash
      export CLOUD_LEARN_HOME="#{libexec}"
      export CLOUDLEARN_DISTRIBUTION_MODE="appliance"
      exec bash "#{libexec}/scripts/cloud-learn" "$@"
    EOS
    chmod 0555, bin/"cloud-learn"

    # Bash + zsh completions (lightweight; just lists the subcommands)
    (bash_completion/"cloud-learn").write <<~EOS
      _cloud_learn() {
        local cur="${COMP_WORDS[COMP_CWORD]}"
        local cmds="up down stop restart status doctor help"
        COMPREPLY=( $(compgen -W "$cmds" -- "$cur") )
      }
      complete -F _cloud_learn cloud-learn
    EOS
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
        cloud-learn up                # boots VM + simulator (5-10 min first run)
        open http://192.168.x.x:9000  # URL printed in the launcher banner

      Stop with:
        cloud-learn down

      Full docs:
        https://github.com/vyomi-cloud/appliance/blob/main/README.md
    EOS
  end

  test do
    # `cloud-learn help` runs without needing Multipass or Docker present.
    assert_match "cloud-learn", shell_output("#{bin}/cloud-learn help 2>&1", 0)
  end
end
