$ErrorActionPreference = 'Stop'
$packageName = 'cloud-learn'
$version     = '1.0.0'
$url64       = "https://github.com/sudhirkumarganti/cloud-learn/releases/download/v$version/cloud-learn-$version-x64.msi"
$checksum64  = 'REPLACED_BY_RELEASE_WORKFLOW'

$packageArgs = @{
  packageName    = $packageName
  fileType       = 'msi'
  url64bit       = $url64
  checksum64     = $checksum64
  checksumType64 = 'sha256'
  silentArgs     = '/qn /norestart /l*v "$($env:TEMP)\cloud-learn-install.log"'
  validExitCodes = @(0, 1641, 3010)
}

Install-ChocolateyPackage @packageArgs

Write-Host ""
Write-Host "==> CloudLearn installed. Run 'cloud-learn up' to start the simulator."
Write-Host "==> Docs: https://github.com/sudhirkumarganti/cloud-learn"

# Multipass dependency check
if (-not (Get-Command multipass -ErrorAction SilentlyContinue)) {
  Write-Host ""
  Write-Host "==> Note: Multipass not detected." -ForegroundColor Yellow
  Write-Host "    Install with: choco install multipass"
  Write-Host "    Or:           https://multipass.run/install"
}
