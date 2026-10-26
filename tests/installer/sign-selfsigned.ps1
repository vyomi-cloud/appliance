<#
  Sign a Vyomi MSI with a SELF-SIGNED code-signing certificate, for testing the
  signing pipeline before the real Artifact Signing certificate is live.

  Creates (or reuses) "CN=<Subject>" in the current user's store, trusts it on
  THIS machine only (Local Machine Root + Trusted Publishers), and signs the MSI
  with signtool (SHA-256, timestamped when the timestamp server is reachable).

  A self-signed signature is valid only where the certificate is trusted: on any
  other PC it still shows "unknown publisher". Never ship a self-signed MSI.

    pwsh tests/installer/sign-selfsigned.ps1 -Msi cloud-learn-3.0.8-x64.msi [-Out signed.msi]

  Run as Administrator (trusting the certificate writes to the machine stores).
#>
param(
  [Parameter(Mandatory)] [string] $Msi,
  [string] $Out = "",
  [string] $Subject = "Vyomi Test Signing"
)
$ErrorActionPreference = "Stop"
$Msi = (Resolve-Path $Msi).Path
if (-not $Out) { $Out = $Msi }
elseif ($Out -ne $Msi) { Copy-Item $Msi $Out -Force }
$Out = (Resolve-Path $Out).Path

$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
  Where-Object { $_.Subject -eq "CN=$Subject" -and $_.NotAfter -gt (Get-Date).AddDays(1) } | Select-Object -First 1
if (-not $cert) {
  $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=$Subject" `
    -CertStoreLocation Cert:\CurrentUser\My -KeyUsage DigitalSignature -KeyAlgorithm RSA -KeyLength 3072 `
    -HashAlgorithm SHA256 -NotAfter (Get-Date).AddDays(30)
  Write-Host "Created self-signed certificate $($cert.Thumbprint) (CN=$Subject)"
}

# Trust it on this machine only, so Windows reports the signature as Valid here.
$cer = Join-Path $env:TEMP "vyomi-test-signing.cer"
Export-Certificate -Cert $cert -FilePath $cer | Out-Null
foreach ($store in "Root", "TrustedPublisher") {
  Import-Certificate -FilePath $cer -CertStoreLocation "Cert:\LocalMachine\$store" | Out-Null
}

$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match "\\x64\\" } | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { throw "signtool.exe not found: install the Windows SDK." }

& $signtool.FullName sign /fd SHA256 /sha1 $cert.Thumbprint /tr http://timestamp.digicert.com /td SHA256 /d "Vyomi" $Out
if ($LASTEXITCODE -ne 0) {
  Write-Warning "Timestamped signing failed (timestamp server unreachable?); signing without a timestamp."
  & $signtool.FullName sign /fd SHA256 /sha1 $cert.Thumbprint /d "Vyomi" $Out
  if ($LASTEXITCODE -ne 0) { throw "signtool failed ($LASTEXITCODE)" }
}

$sig = Get-AuthenticodeSignature $Out
Write-Host "Signed $Out — $($sig.Status) — $($sig.SignerCertificate.Subject)"
if ($sig.Status -ne "Valid") { throw "Signature is $($sig.Status), expected Valid" }
