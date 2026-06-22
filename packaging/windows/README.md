# Windows packaging (MSI)

`cloudlearn.wxs` is the WiX v4 source for the Vyomi Windows installer. The
MSI bundles the full launcher (the same file set as the `.tar.gz` / `.deb` /
`.rpm`), installs it to `%ProgramFiles%\Vyomi`, drops a `vyomi.cmd` shim on
the system `PATH`, and adds a Start-menu shortcut. `vyomi up` then boots the
appliance VM via `scripts\cloud-learn.ps1`.

## How it's built (CI)

The `windows-msi` job in `.github/workflows/release.yml` builds it on every
release:

1. Download the release source tarball and extract it to `stage\`.
2. Generate `stage\bin\vyomi.cmd` (the PATH shim → forwards to the launcher).
3. `dotnet tool install --global wix`
4. `wix build packaging\windows\cloudlearn.wxs -arch x64 -d Version=<ver> -d StageDir=<abs>\stage -o dist\cloud-learn-<ver>-x64.msi`
5. (opt-in) sign via Azure Trusted Signing, then attach the MSI to the
   GitHub Release. `winget-submit` (winget-releaser) consumes it.

## Build locally (on Windows)

```powershell
$ver = "2.1.0"
mkdir stage, stage\bin
tar -xzf cloud-learn-$ver.tar.gz -C stage --strip-components=1
'@echo off',
'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\cloud-learn.ps1" %*' |
  Set-Content stage\bin\vyomi.cmd -Encoding ascii
dotnet tool install --global wix
wix build packaging\windows\cloudlearn.wxs -arch x64 `
  -d Version=$ver -d "StageDir=$((Resolve-Path stage).Path)" `
  -o "dist\cloud-learn-$ver-x64.msi"
```

## Runtime expectations

- Multipass on the host (the launcher auto-installs it via winget on first
  `vyomi up`). Multipass needs Hyper-V (Win 10/11 Pro/Enterprise) or VirtualBox.
- ~32 GB free disk for the VM image + container layers.
- The MSI installs the launcher only; the simulator stack runs inside the
  Multipass VM.

## Code signing

Unsigned MSIs trip SmartScreen ("unknown publisher"). Signing is opt-in:
set the repo variable `ENABLE_MSI_SIGNING=true` and provide the Azure Trusted
Signing secrets/vars (`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`,
`AZURE_CLIENT_SECRET`, `AZURE_SIGNING_ENDPOINT`, `AZURE_SIGNING_ACCOUNT`,
`AZURE_SIGNING_PROFILE`). Azure Trusted Signing is the recommended path
(cheap, CI-native, SmartScreen-clean); an EV cert is the alternative.
