# CloudLearn RPM spec — Fedora/RHEL/CentOS/openSUSE.
#
# Build:    rpmbuild -bb packaging/rpm/cloud-learn.spec --define "_topdir $(pwd)/dist/rpmbuild"
# Install:  sudo dnf install ./dist/rpmbuild/RPMS/noarch/cloud-learn-1.0.0-1.noarch.rpm
#
# The release CI uses `fpm` to build this without needing the full rpmbuild
# toolchain — this .spec is the canonical reference.

Name:          cloud-learn
Version:       1.0.0
Release:       1%{?dist}
Summary:       Local multi-cloud simulator (AWS/GCP/Azure) with real backends
License:       MIT
URL:           https://github.com/sudhirkumarganti/cloud-learn
Source0:       https://github.com/sudhirkumarganti/cloud-learn/archive/refs/tags/v%{version}.tar.gz
BuildArch:     noarch

Requires:      bash
Requires:      curl
Requires:      ca-certificates
# multipass is in COPR/snap on most RPM distros — recommend, don't hard-require
Recommends:    multipass
Recommends:    docker-ce
Suggests:      qemu-kvm

%description
CloudLearn is a local-first multi-cloud simulator that gives you AWS, GCP,
and Azure-like experiences on your laptop. Standard provider SDKs (boto3,
aws-sdk-java, google-cloud-*, azure-sdk-for-*) and CLIs (aws, gcloud,
gsutil, bq, az, terraform) work natively against the simulator by
overriding the endpoint URL — no shim required.

The package ships the launcher; the full simulator stack runs inside a
Multipass VM that 'cloud-learn up' provisions.

%prep
%setup -q -n cloud-learn-%{version}

%build
# Nothing to compile — pure Python + bundled scripts

%install
mkdir -p %{buildroot}/usr/lib/cloud-learn
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}/usr/share/doc/cloud-learn
# Phone-home script lives in /usr/share so it stays a tiny standalone
# shell script — no dependency on the bundled Python tree under
# /usr/lib/cloud-learn (which a hardened sysadmin may chmod 0700).
mkdir -p %{buildroot}/usr/share/vyomi/packaging/common

# Keep in sync with scripts/cloud-learn (appliance_sync_source_into_vm) +
# release.yml. routes/setup_cython.py/packaging/cloudsim-backbone were omitted;
# packaging/{firestore,vault,elasticmq} are bind-mounted by the compose file, so
# omitting them makes Docker stub the mount sources as dirs → containers crash
# (exit 126) → simulator never starts. Verified by scripts/verify-bundle.sh.
cp -r core providers packs routes static scripts packaging cloudsim-backbone \
      server.py setup_cython.py requirements.txt VERSION Dockerfile \
      docker-compose.yml docker-compose.appliance.yml .env.example \
      %{buildroot}/usr/lib/cloud-learn/

install -m 0755 packaging/common/phone-home.sh \
        %{buildroot}/usr/share/vyomi/packaging/common/phone-home.sh
install -m 0644 VERSION \
        %{buildroot}/usr/share/vyomi/packaging/common/VERSION

cat > %{buildroot}/usr/bin/cloud-learn <<'EOF'
#!/usr/bin/env bash
export CLOUD_LEARN_HOME="${CLOUD_LEARN_HOME:-/usr/lib/cloud-learn}"
export CLOUDLEARN_DISTRIBUTION_MODE="${CLOUDLEARN_DISTRIBUTION_MODE:-appliance}"
exec bash "$CLOUD_LEARN_HOME/scripts/cloud-learn" "$@"
EOF
chmod 0755 %{buildroot}/usr/bin/cloud-learn

install -m 644 README.md LICENSE CHANGELOG.md %{buildroot}/usr/share/doc/cloud-learn/ 2>/dev/null || :

%files
/usr/lib/cloud-learn
/usr/bin/cloud-learn
/usr/share/vyomi
%doc /usr/share/doc/cloud-learn

%post
echo "==> CloudLearn installed. Run 'cloud-learn up' to start the simulator."
echo "==> Docs: https://github.com/sudhirkumarganti/cloud-learn"
if ! command -v multipass >/dev/null 2>&1; then
  echo "==> Note: Multipass not detected. Install: sudo snap install multipass"
fi

# Install-funnel phone-home (anonymous; opt-out via VYOMI_NO_TELEMETRY=1).
# Backgrounded so a slow network never extends the rpm transaction.
if [ -x /usr/share/vyomi/packaging/common/phone-home.sh ]; then
  ( /bin/sh /usr/share/vyomi/packaging/common/phone-home.sh rpm >/dev/null 2>&1 & ) || :
fi

%preun
# Stop the appliance VM cleanly on removal
if [ "$1" = "0" ] && command -v cloud-learn >/dev/null 2>&1; then
  cloud-learn down >/dev/null 2>&1 || :
fi

%changelog
* Thu Jun 19 2026 Vyomi <support@vyomi.cloud> - 2.0.6-1
- Install-funnel phone-home + Docker Hub metadata rebrand to Vyomi.
- See full changelog: /usr/share/doc/cloud-learn/CHANGELOG.md
* Sun Jun 01 2026 Vyomi <support@vyomi.cloud> - 1.0.0-1
- First GA release. 3 cloud providers, 8 real backends, 4-tier licensing,
  multi-tenant + cross-tenant RBAC + SSO, Terraform export/import, Helm chart.
- See full changelog: /usr/share/doc/cloud-learn/CHANGELOG.md
